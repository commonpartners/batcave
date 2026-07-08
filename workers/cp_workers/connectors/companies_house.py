"""Companies House REST client + iXBRL parsing (spec 02 §1).

Every network call goes through :func:`CompaniesHouseClient._request`, which
enforces the shared 600-req/5-min token bucket and backs off per
``Retry-After`` on 429. Every successful response is written to
``source_records`` via ``cp_workers.db.record_source`` *before* the caller
gets parsed data back, per spec 00 §4 "provenance everywhere".

``parse_ixbrl`` is a standalone pure-ish function (its only side effect is
logging) that never raises — malformed/unexpected documents just yield ``{}``.
"""
from __future__ import annotations

import decimal
import email.utils
import logging
import threading
import time
from typing import Any, Callable

import httpx
from lxml import etree

from cp_workers import db
from cp_workers.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.company-information.service.gov.uk"

# Shared rate limit per spec 00 §4 / 02 §1.
_BUCKET_CAPACITY = 600
_BUCKET_WINDOW_SECONDS = 300.0
_DEFAULT_RETRY_AFTER_SECONDS = 5.0


class CompaniesHouseError(RuntimeError):
    """Raised for non-recoverable Companies House API failures."""


class TokenBucket:
    """Simple token-bucket throttle: ``capacity`` tokens refilling over ``window``.

    Thread-safe (a single shared instance is meant to be reused across every
    call the process makes, since the 600/5min limit is per API key, not per
    client instance).
    """

    def __init__(
        self,
        capacity: int = _BUCKET_CAPACITY,
        window_seconds: float = _BUCKET_WINDOW_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.capacity = capacity
        self.refill_rate = capacity / window_seconds  # tokens per second
        self._tokens = float(capacity)
        self._clock = clock
        self._sleep = sleep_fn
        self._last_refill = clock()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now

    def acquire(self) -> None:
        """Block until a token is available, then consume one."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                wait_seconds = deficit / self.refill_rate
            self._sleep(max(wait_seconds, 0.001))


def _parse_retry_after(value: str | None, *, default: float = _DEFAULT_RETRY_AFTER_SECONDS) -> float:
    """Retry-After can be either an integer number of seconds or an HTTP-date."""
    if not value:
        return default
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt is None:
            return default
        now = email.utils.parsedate_to_datetime(email.utils.formatdate(usegmt=True))
        return max(0.0, (dt - now).total_seconds())
    except (TypeError, ValueError):
        return default


class CompaniesHouseClient:
    """Throttled Companies House REST client.

    Basic auth: API key as username, blank password (per CH docs).
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        http_client: httpx.Client | None = None,
        bucket: TokenBucket | None = None,
        max_retries: int = 6,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.companies_house_api_key
        self._base_url = base_url.rstrip("/")
        self._http = http_client or httpx.Client(timeout=30.0)
        self._owns_http = http_client is None
        self._bucket = bucket or TokenBucket()
        self._max_retries = max_retries
        self._sleep = sleep_fn

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "CompaniesHouseClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- low level -----------------------------------------------------

    def _auth(self) -> tuple[str, str]:
        if not self._api_key:
            raise CompaniesHouseError(
                "COMPANIES_HOUSE_API_KEY is not configured (see .env.example)"
            )
        return (self._api_key, "")

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_response: httpx.Response | None = None
        for _attempt in range(self._max_retries + 1):
            self._bucket.acquire()
            response = self._http.request(method, url, auth=self._auth(), **kwargs)
            if response.status_code != 429:
                return response
            last_response = response
            wait_seconds = _parse_retry_after(response.headers.get("Retry-After"))
            logger.warning(
                "Companies House 429 on %s %s; backing off %.1fs per Retry-After",
                method,
                url,
                wait_seconds,
            )
            self._sleep(wait_seconds)
        assert last_response is not None
        raise CompaniesHouseError(
            f"Companies House rate limit exceeded after {self._max_retries} retries: {url}"
        )

    def _get_json(self, path: str, *, source: str, company_number: str | None, params: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        response = self._request("GET", url, params=params)
        response.raise_for_status()
        payload = response.json()
        self._record(source=source, source_url=url, raw=payload, company_number=company_number)
        return payload

    def _record(self, *, source: str, source_url: str, raw: Any, company_number: str | None) -> None:
        company_id = None
        if company_number:
            existing = db.get_company_by_number(company_number)
            company_id = existing["id"] if existing else None
        db.record_source(company_id=company_id, source=source, source_url=source_url, raw=raw)

    # -- endpoints -------------------------------------------------------

    def get_profile(self, number: str) -> dict:
        return self._get_json(
            f"/company/{number}",
            source="companies_house_profile",
            company_number=number,
        )

    def get_officers(self, number: str) -> dict:
        return self._get_json(
            f"/company/{number}/officers",
            source="companies_house_officers",
            company_number=number,
        )

    def get_psc(self, number: str) -> dict:
        return self._get_json(
            f"/company/{number}/persons-with-significant-control",
            source="companies_house_psc",
            company_number=number,
        )

    def get_filing_history(self, number: str) -> dict:
        return self._get_json(
            f"/company/{number}/filing-history",
            source="companies_house_filings",
            company_number=number,
        )

    def advanced_search(
        self,
        sic_codes: list[str] | None = None,
        status: str | None = "active",
        incorp_from: str | None = None,
        incorp_to: str | None = None,
        *,
        company_name_includes: str | None = None,
        start_index: int = 0,
        size: int = 100,
    ) -> dict:
        """`/advanced-search/companies` — used for discovery refinement and name
        resolution (intake). Not tied to a single company, so we record
        provenance with ``company_id=None`` under the closest available
        ``source_records.source`` enum value (``companies_house_profile`` —
        there is no dedicated "search" source in the schema, spec 01 §5).
        """
        params: dict[str, Any] = {"start_index": start_index, "size": size}
        if sic_codes:
            params["sic_codes"] = ",".join(sic_codes)
        if status:
            params["company_status"] = status
        if incorp_from:
            params["incorporated_from"] = incorp_from
        if incorp_to:
            params["incorporated_to"] = incorp_to
        if company_name_includes:
            params["company_name_includes"] = company_name_includes

        url = f"{self._base_url}/advanced-search/companies"
        response = self._request("GET", url, params=params)
        response.raise_for_status()
        payload = response.json()
        db.record_source(company_id=None, source="companies_house_profile", source_url=url, raw=payload)
        return payload

    def get_document(self, metadata_url: str) -> bytes:
        """Fetch a filing document (e.g. iXBRL accounts) given the
        ``links.document_metadata`` URL from a filing-history item.

        Two-step CH document API: GET the metadata resource to discover
        available content types, then GET ``{metadata_url}/content`` with the
        matching Accept header to get the raw bytes.
        """
        meta_response = self._request("GET", metadata_url)
        meta_response.raise_for_status()
        metadata = meta_response.json()
        resources = metadata.get("resources", {}) if isinstance(metadata, dict) else {}
        content_type = next(
            (ct for ct in ("application/xhtml+xml", "text/html", "application/xml") if ct in resources),
            None,
        )
        content_url = f"{metadata_url.rstrip('/')}/content"
        headers = {"Accept": content_type} if content_type else {}
        content_response = self._request("GET", content_url, headers=headers, follow_redirects=True)
        content_response.raise_for_status()
        # Per spec 01 §5, large HTML payloads belong in the raw-html storage
        # bucket with only the path stored in `raw`; uploading to Supabase
        # Storage is not implemented here, so we record metadata about the
        # fetch rather than the full document body.
        db.record_source(
            company_id=None,
            source="ixbrl_accounts",
            source_url=content_url,
            raw={
                "content_type": content_response.headers.get("content-type"),
                "byte_length": len(content_response.content),
                "metadata_url": metadata_url,
            },
        )
        return content_response.content


# ---------------------------------------------------------------------------
# iXBRL parsing (spec 02 §1)
# ---------------------------------------------------------------------------

# Balance-sheet + employee-count concepts we look for, keyed by our own field
# name -> tuple of acceptable XBRL concept local names (namespace-stripped),
# matched against the `name` attribute of `ix:nonFraction` / `ix:nonNumeric`
# elements. Covers the FRS 102/105 (uk-gaap / core) taxonomies most small
# company accounts use.
_CONCEPT_MAP: dict[str, tuple[str, ...]] = {
    "fixed_assets": ("FixedAssets", "TangibleFixedAssets", "PropertyPlantEquipment"),
    "current_assets": ("CurrentAssets",),
    "cash": ("CashBankInHand", "CashBankOnHand"),
    "creditors_due_within_one_year": ("CreditorsDueWithinOneYear",),
    "creditors_due_after_one_year": ("CreditorsDueAfterOneYear",),
    "net_assets": (
        "NetAssetsLiabilitiesIncludingPensionAssetLiability",
        "NetAssetsLiabilities",
    ),
    "shareholders_funds": ("ShareholderFunds",),
    "average_employees": ("AverageNumberEmployeesDuringPeriod", "EmployeesTotal"),
}

_MONEY_FIELDS = {
    "fixed_assets",
    "current_assets",
    "cash",
    "creditors_due_within_one_year",
    "creditors_due_after_one_year",
    "net_assets",
    "shareholders_funds",
}

_NULL_MARKERS = {"", "-", "–", "—"}


def _local_name(tag: str) -> str:
    return tag.rpartition("}")[2] if "}" in tag else tag.rpartition(":")[2]


def _element_text(element: etree._Element) -> str:
    """Concatenate text content, skipping any ix:exclude commentary nodes."""
    parts = []
    for node in element.iter():
        if _local_name(node.tag) == "exclude":
            continue
        if node.text:
            parts.append(node.text)
    return "".join(parts).strip()


def _parse_numeric(element: etree._Element, text: str) -> decimal.Decimal | None:
    text = text.strip()
    if text in _NULL_MARKERS:
        return None
    sign = -1 if element.get("sign", "") == "-" else 1
    scale = element.get("scale", "0")
    cleaned = text.replace(",", "").replace(" ", "")
    try:
        value = decimal.Decimal(cleaned)
        value *= decimal.Decimal(10) ** decimal.Decimal(scale or "0")
        return sign * value
    except (decimal.InvalidOperation, ValueError):
        return None


def parse_ixbrl(document_bytes: bytes) -> dict:
    """Extract balance-sheet facts + average employee count from an iXBRL
    (or plain XBRL) accounts document (spec 02 §1).

    Returns ``{}`` (after logging) on any parsing failure or malformed input
    — this must never raise, since document quality across small-company
    filings varies wildly.
    """
    if not document_bytes:
        return {}
    try:
        cleaned = document_bytes[document_bytes.find(b"<") :] if b"<" in document_bytes else document_bytes
        parser = etree.XMLParser(recover=True, resolve_entities=False, huge_tree=True)
        root = etree.fromstring(cleaned, parser=parser)
        if root is None:
            logger.warning("parse_ixbrl: document did not parse to any element tree")
            return {}

        found: dict[str, decimal.Decimal] = {}
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            name_attr = element.get("name")
            if not name_attr:
                continue
            concept = name_attr.rpartition(":")[2]
            for field_name, concept_names in _CONCEPT_MAP.items():
                if field_name in found:
                    continue
                if concept in concept_names:
                    text = _element_text(element)
                    value = _parse_numeric(element, text)
                    if value is not None:
                        found[field_name] = value
                    break

        def money_pence(field_name: str) -> int | None:
            value = found.get(field_name)
            if value is None:
                return None
            return int((value * 100).to_integral_value(rounding=decimal.ROUND_HALF_UP))

        total_assets = None
        fixed = found.get("fixed_assets")
        current = found.get("current_assets")
        if fixed is not None or current is not None:
            total_assets = money_pence("fixed_assets") or 0
            total_assets += money_pence("current_assets") or 0

        creditors = None
        within = found.get("creditors_due_within_one_year")
        after = found.get("creditors_due_after_one_year")
        if within is not None or after is not None:
            creditors = (money_pence("creditors_due_within_one_year") or 0) + (
                money_pence("creditors_due_after_one_year") or 0
            )

        balance_sheet = {
            "total_assets": total_assets,
            "net_assets": money_pence("net_assets"),
            "cash": money_pence("cash"),
            "creditors": creditors,
            "shareholders_funds": money_pence("shareholders_funds"),
        }

        employee_count = None
        if "average_employees" in found:
            employee_count = int(found["average_employees"].to_integral_value(rounding=decimal.ROUND_HALF_UP))

        if not any(v is not None for v in balance_sheet.values()) and employee_count is None:
            logger.info("parse_ixbrl: no recognised balance-sheet or employee-count concepts found")
            return {}

        return {"balance_sheet": balance_sheet, "employee_count": employee_count}
    except Exception:  # noqa: BLE001 - parsing must never be fatal (spec 02 §1)
        logger.exception("parse_ixbrl: failed to parse document, returning {}")
        return {}
