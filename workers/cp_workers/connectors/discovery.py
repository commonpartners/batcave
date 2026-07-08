"""Bulk discovery, sector classification, universe refresh, CSV intake, and
the Phase-0 Excel export (spec 02 §2-3 + §7; spec 06 Phase 0).

Module path: ``cp_workers.connectors.discovery``. Plain functions, no CLI
decorators — the integration pass wires these into ``cli.py``.
"""
from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from openpyxl import Workbook

from cp_workers import db
from cp_workers.config import settings
from cp_workers.connectors.companies_house import CompaniesHouseClient
from cp_workers.signals import succession

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "sector_classify.md"

RUBRIC_DIMENSION_COLUMNS = (
    "brand_customer_equity",
    "latent_digital_upside",
    "financial_quality",
    "deal_accessibility",
    "team_continuity",
    "market_consolidation",
    "differentiation",
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class DiscoverStats:
    rows_scanned: int = 0
    candidates: int = 0
    upserted: int = 0
    filtered_out: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class IntakeReport:
    total_rows: int = 0
    resolved: int = 0
    created: int = 0
    unresolved: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Taxonomy helpers (pure, DB-independent — testable in isolation)
# ---------------------------------------------------------------------------


def _fetch_taxonomy_rules() -> list[dict]:
    client = db.get_client()
    resp = client.table("taxonomy_rules").select("*").eq("active", True).execute()
    return resp.data or []


def _extract_sic_codes(row: dict) -> list[str]:
    """CH Free Company Data Product has up to 4 'SICCode.SicText_N' columns,
    each like '20420 - Manufacture of perfumes and toilet preparations'."""
    codes = []
    for i in range(1, 5):
        raw = row.get(f"SICCode.SicText_{i}") or row.get(f"SICCode.SicText_{i} ")
        if not raw:
            continue
        raw = raw.strip()
        if not raw or raw.lower().startswith("none"):
            continue
        code = raw.split("-", 1)[0].strip()
        if code:
            codes.append(code)
    return codes


def _row_text(name: str, website_text: str | None = None) -> str:
    return f"{name} {website_text or ''}".lower()


def _keyword_hit(text: str, keywords: list[str]) -> bool:
    return any(kw.lower() in text for kw in keywords)


def is_taxonomy_candidate(name: str, sic_codes: list[str], taxonomy_rules: list[dict]) -> bool:
    """Spec 02 §3: a company is a discovery candidate if any SIC code in the
    taxonomy seed list matches, OR the name matches an include-keyword."""
    text = _row_text(name)
    sic_set = set(sic_codes)
    for rule in taxonomy_rules:
        if sic_set & set(rule.get("sic_codes") or []):
            return True
        if _keyword_hit(text, rule.get("include_keywords") or []):
            return True
    return False


def passes_universe_filters(
    *,
    status: str | None,
    incorporation_date: date | None,
    name: str,
    min_age_years: int,
    taxonomy_rules: list[dict],
    today: date,
) -> tuple[bool, str | None]:
    """Spec 02 §2: active, no insolvency/strike-off, incorporation >= min age,
    not excluded by keyword. Returns (passes, reason_if_not)."""
    if not status or status.strip().lower() != "active":
        return False, f"status is '{status}', not active"
    if incorporation_date is None:
        return False, "no incorporation date on record"
    age_years = (today - incorporation_date).days / 365.25
    if age_years < min_age_years:
        return False, f"company age {age_years:.1f}y < min {min_age_years}y"
    text = _row_text(name)
    for rule in taxonomy_rules:
        if _keyword_hit(text, rule.get("exclude_keywords") or []):
            return False, "matched an exclude keyword"
    return True, None


def _parse_ch_date(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_snapshot_row(row: dict) -> dict:
    """Normalise a Free Company Data Product CSV row: strip whitespace from
    keys (some historical exports have leading spaces) and pull out the
    fields discovery needs."""
    clean = {k.strip(): v for k, v in row.items() if k is not None}
    return {
        "legal_name": (clean.get("CompanyName") or "").strip(),
        "company_number": (clean.get("CompanyNumber") or "").strip(),
        "company_status": (clean.get("CompanyStatus") or "").strip(),
        "incorporation_date": _parse_ch_date(clean.get("IncorporationDate")),
        "sic_codes": _extract_sic_codes(clean),
        "country": (clean.get("CountryOfOrigin") or "").strip(),
    }


def _open_snapshot_text(snapshot_path: str):
    """Yields a text-mode file handle for the CSV inside the snapshot,
    whether it's a raw CSV or the zipped Free Company Data Product."""
    path = Path(snapshot_path)
    if path.suffix.lower() == ".zip":
        zf = zipfile.ZipFile(path)
        member = next((n for n in zf.namelist() if n.lower().endswith(".csv")), None)
        if member is None:
            raise ValueError(f"no CSV found inside {snapshot_path}")
        return io.TextIOWrapper(zf.open(member), encoding="utf-8-sig", newline="")
    return open(path, "r", encoding="utf-8-sig", newline="")


def discover_universe(snapshot_path: str) -> DiscoverStats:
    """Stream-parse the Free Company Data Product CSV, apply taxonomy +
    universe filters locally (zero API quota per spec 02 §3a), and upsert
    survivors as ``companies`` (lifecycle='discovered')."""
    stats = DiscoverStats()
    taxonomy_rules = _fetch_taxonomy_rules()
    min_age_years = int(db.get_config("min_company_age_years", 8))
    today = datetime.now().date()

    fh = _open_snapshot_text(snapshot_path)
    try:
        reader = csv.DictReader(fh)
        for row in reader:
            stats.rows_scanned += 1
            try:
                normalized = _normalize_snapshot_row(row)
                if not normalized["company_number"] or not normalized["legal_name"]:
                    stats.filtered_out += 1
                    continue
                if not is_taxonomy_candidate(
                    normalized["legal_name"], normalized["sic_codes"], taxonomy_rules
                ):
                    stats.filtered_out += 1
                    continue
                stats.candidates += 1
                ok, _reason = passes_universe_filters(
                    status=normalized["company_status"],
                    incorporation_date=normalized["incorporation_date"],
                    name=normalized["legal_name"],
                    min_age_years=min_age_years,
                    taxonomy_rules=taxonomy_rules,
                    today=today,
                )
                if not ok:
                    stats.filtered_out += 1
                    continue
                db.upsert_company(
                    normalized["company_number"],
                    {
                        "legal_name": normalized["legal_name"],
                        "incorporation_date": normalized["incorporation_date"].isoformat()
                        if normalized["incorporation_date"]
                        else None,
                        "company_status": normalized["company_status"] or None,
                        "sic_codes": normalized["sic_codes"] or None,
                        "lifecycle": "discovered",
                    },
                )
                stats.upserted += 1
            except Exception as exc:  # noqa: BLE001 - one bad row must never abort the scan
                stats.errors.append(f"{row.get('CompanyNumber', '?')}: {exc}")
    finally:
        fh.close()
    return stats


# ---------------------------------------------------------------------------
# Sector classification
# ---------------------------------------------------------------------------


def _rules_classify(
    name: str, website_text: str | None, sic_codes: list[str], taxonomy_rules: list[dict]
) -> tuple[str, float, str] | None:
    """Returns (tag, confidence, 'rules') on a confident match, or a confident
    'uncategorised' when nothing matches at all. Returns None when the
    signal is genuinely ambiguous (SIC hit but weak keywords, or vice versa)
    — the caller then falls back to the LLM classifier (spec 02 §2)."""
    text = _row_text(name, website_text)
    sic_set = set(sic_codes or [])
    partial_hit = False

    for rule in taxonomy_rules:
        sic_hit = bool(sic_set & set(rule.get("sic_codes") or []))
        include_hit = _keyword_hit(text, rule.get("include_keywords") or [])
        exclude_hit = _keyword_hit(text, rule.get("exclude_keywords") or [])

        if exclude_hit and not (sic_hit and include_hit):
            continue  # excluded for this rule unless product line evidence overrides it

        if sic_hit and include_hit:
            return rule["sector_tag"], 0.95, "rules"
        if sic_hit or include_hit:
            partial_hit = True

    if partial_hit:
        return None
    return "uncategorised", 0.9, "rules"


def _llm_classify_default(name: str, website_text: str | None, sic_codes: list[str]) -> tuple[str, float, str]:
    """Calls Claude with ``prompts/sector_classify.md`` for ambiguous cases."""
    if not settings.anthropic_api_key:
        return "needs-review", 0.0, "no anthropic_api_key configured"
    try:
        import json

        import anthropic

        prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
        # Strip the YAML front-matter (between the leading '---' markers).
        body = prompt_template.split("---", 2)[-1] if prompt_template.startswith("---") else prompt_template

        user_content = (
            f"{body}\n\n## Company to classify\n"
            f"Name: {name}\n"
            f"SIC codes: {', '.join(sic_codes) if sic_codes else '(none)'}\n"
            f"Website text (may be empty): {(website_text or '')[:4000]}\n"
        )

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=300,
            temperature=0,
            messages=[{"role": "user", "content": user_content}],
        )
        raw_text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        parsed = json.loads(raw_text)
        tag = str(parsed["sector_tag"])
        confidence = float(parsed["confidence"])
        rationale = str(parsed.get("rationale", "llm classification"))
        return tag, confidence, rationale
    except Exception as exc:  # noqa: BLE001 - LLM classification must never raise/fabricate
        logger.warning("sector_classify LLM fallback failed: %s", exc)
        return "needs-review", 0.0, f"LLM classification failed: {exc}"


def classify_sector(
    name: str,
    website_text: str | None,
    sic_codes: list[str],
    *,
    taxonomy_rules: list[dict] | None = None,
    llm_classify: Callable[[str, str | None, list[str]], tuple[str, float, str]] | None = None,
) -> tuple[str, float, str]:
    """SIC match + keyword rules -> ('rules'); ambiguous -> LLM fallback
    ('llm'); confidence < 0.7 -> tag forced to 'needs-review' regardless of
    source (spec 02 §2)."""
    rules = taxonomy_rules if taxonomy_rules is not None else _fetch_taxonomy_rules()
    result = _rules_classify(name, website_text, sic_codes, rules)
    if result is not None:
        tag, confidence, source = result
    else:
        classify_fn = llm_classify or _llm_classify_default
        tag, confidence, _rationale = classify_fn(name, website_text, sic_codes)
        source = "llm"

    if confidence < 0.7:
        tag = "needs-review"
    return tag, confidence, source


# ---------------------------------------------------------------------------
# CH officer/PSC -> succession `people` shape
# ---------------------------------------------------------------------------


def _psc_ownership_band(natures_of_control: list[str] | None) -> str | None:
    text = " ".join(natures_of_control or [])
    if "75-to-100" in text or "over-75" in text:
        return "75-100"
    if "50-to-75" in text:
        return "50-75"
    if "25-to-50" in text:
        return "25-50"
    return None


def officers_and_psc_to_people(officers_payload: dict, psc_payload: dict, now: date) -> list[dict]:
    """Map raw CH officers + PSC API payloads into the ``people`` shape the
    succession signal functions expect (see signals/succession.py docstring).

    Note: ``other_active_directorships`` requires the officer's cross-company
    appointments list, an endpoint outside this client's method set — left
    ``None`` (unknown) rather than guessed; ``long_single_owner_tenure`` still
    scores on tenure alone in that case (unknown never disqualifies, only a
    confirmed count > 2 does)."""
    people: list[dict] = []

    for item in (officers_payload or {}).get("items", []):
        role_raw = (item.get("officer_role") or "").lower()
        if "director" in role_raw:
            role = "director"
        elif "secretary" in role_raw:
            role = "secretary"
        else:
            continue
        appointed_on = _parse_ch_date(item.get("appointed_on"))
        resigned_on = _parse_ch_date(item.get("resigned_on"))
        is_active = resigned_on is None
        tenure_years = None
        if appointed_on and is_active:
            tenure_years = (now - appointed_on).days / 365.25
        dob = item.get("date_of_birth") or {}
        people.append(
            {
                "name": item.get("name"),
                "role": role,
                "is_active": is_active,
                "birth_year": dob.get("year"),
                "birth_month": dob.get("month"),
                "ownership_pct_band": None,
                "tenure_years": tenure_years,
                "other_active_directorships": None,
            }
        )

    for item in (psc_payload or {}).get("items", []):
        dob = item.get("date_of_birth") or {}
        people.append(
            {
                "name": item.get("name"),
                "role": "psc",
                "is_active": item.get("ceased_on") is None,
                "birth_year": dob.get("year"),
                "birth_month": dob.get("month"),
                "ownership_pct_band": _psc_ownership_band(item.get("natures_of_control")),
                "tenure_years": None,
                "other_active_directorships": None,
            }
        )

    return people


# ---------------------------------------------------------------------------
# Universe refresh
# ---------------------------------------------------------------------------


def refresh_universe_company(company_number: str, client: CompaniesHouseClient | None = None) -> bool:
    """Re-fetch profile/officers/PSC/filing-history for a universe company;
    content-hash diff per endpoint; returns whether anything changed."""
    owns_client = client is None
    client = client or CompaniesHouseClient()
    try:
        company = db.get_company_by_number(company_number)
        if company is None:
            raise ValueError(f"unknown company_number {company_number!r} — not in the universe yet")
        company_id = company["id"]

        changed = False
        fetchers = {
            "companies_house_profile": client.get_profile,
            "companies_house_officers": client.get_officers,
            "companies_house_psc": client.get_psc,
            "companies_house_filings": client.get_filing_history,
        }
        profile_payload: dict | None = None
        for source, fetch in fetchers.items():
            prev_hash = db.last_source_hash(company_id=company_id, source=source)
            try:
                payload = fetch(company_number)
            except Exception as exc:  # noqa: BLE001 - one endpoint failing must not sink the refresh
                logger.warning("refresh_universe_company(%s): %s fetch failed: %s", company_number, source, exc)
                continue
            if source == "companies_house_profile":
                profile_payload = payload
            new_hash = db.content_hash(payload)
            if prev_hash is None or prev_hash != new_hash:
                changed = True

        if profile_payload is not None:
            db.upsert_company(
                company_number,
                {
                    "legal_name": profile_payload.get("company_name"),
                    "company_status": profile_payload.get("company_status"),
                    "sic_codes": profile_payload.get("sic_codes"),
                    "registered_address": profile_payload.get("registered_office_address"),
                    "incorporation_date": profile_payload.get("date_of_creation"),
                },
            )
        return changed
    finally:
        if owns_client:
            client.close()


# ---------------------------------------------------------------------------
# Manual intake
# ---------------------------------------------------------------------------


def intake_from_csv(path: str, client: CompaniesHouseClient | None = None) -> IntakeReport:
    """Resolve name/number rows to ``company_number`` via CH search, upsert
    ``companies``, report unresolved rows (spec 02 §7)."""
    owns_client = client is None
    client = client or CompaniesHouseClient()
    report = IntakeReport()
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                report.total_rows += 1
                clean = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k is not None}
                number = clean.get("company_number") or clean.get("number")
                name = clean.get("name") or clean.get("company_name")
                website = clean.get("website")

                resolved_number = None
                resolved_name = None
                try:
                    if number:
                        profile = client.get_profile(number)
                        resolved_number = number
                        resolved_name = profile.get("company_name", name)
                    elif name:
                        search = client.advanced_search(company_name_includes=name)
                        items = search.get("items") or []
                        match = next(
                            (i for i in items if (i.get("company_name") or "").strip().lower() == name.lower()),
                            items[0] if items else None,
                        )
                        if match:
                            resolved_number = match.get("company_number")
                            resolved_name = match.get("company_name", name)
                    else:
                        report.unresolved.append({"row": row, "reason": "no company_number or name column"})
                        continue

                    if not resolved_number:
                        report.unresolved.append({"row": row, "reason": "no CH match found"})
                        continue

                    db.upsert_company(
                        resolved_number,
                        {
                            "legal_name": resolved_name or name,
                            "website": website or None,
                            "lifecycle": "discovered",
                        },
                    )
                    report.resolved += 1
                    report.created += 1
                except Exception as exc:  # noqa: BLE001 - a bad row must not abort the whole intake
                    report.unresolved.append({"row": row, "reason": str(exc)})
        return report
    finally:
        if owns_client:
            client.close()


# ---------------------------------------------------------------------------
# Phase-0 export
# ---------------------------------------------------------------------------


def export_phase0(company_numbers: list[str], out_path: str, client: CompaniesHouseClient | None = None) -> None:
    """Pull CH data, compute succession signals, write one xlsx row per
    company with empty rubric dimension columns (spec 06 Phase 0)."""
    owns_client = client is None
    client = client or CompaniesHouseClient()
    today = datetime.now().date()

    wb = Workbook()
    ws = wb.active
    ws.title = "phase0"
    headers = [
        "company_number",
        "legal_name",
        "incorporation_date",
        "company_status",
        "sic_codes",
        "director_retirement_window_value",
        "director_retirement_window_rationale",
        "long_single_owner_tenure_value",
        "long_single_owner_tenure_rationale",
        "board_psc_event_recent_value",
        "board_psc_event_recent_rationale",
        *RUBRIC_DIMENSION_COLUMNS,
        "notes",
    ]
    ws.append(headers)

    try:
        for number in company_numbers:
            try:
                profile = client.get_profile(number)
                officers = client.get_officers(number)
                psc = client.get_psc(number)
            except Exception as exc:  # noqa: BLE001 - one company failing must not abort the export
                ws.append([number, f"ERROR: {exc}"] + [None] * (len(headers) - 2))
                continue

            people = officers_and_psc_to_people(officers, psc, today)
            events: list[dict] = []  # no filing-history diff wired up yet for Phase 0

            retirement_value, _retirement_evidence, retirement_rationale = succession.director_retirement_window(
                people, today
            )
            tenure_value, _tenure_evidence, tenure_rationale = succession.long_single_owner_tenure(people)
            psc_event_value, _psc_evidence, psc_event_rationale = succession.board_psc_event_recent(events, today)

            row = [
                number,
                profile.get("company_name"),
                profile.get("date_of_creation"),
                profile.get("company_status"),
                ", ".join(profile.get("sic_codes") or []),
                retirement_value,
                retirement_rationale,
                tenure_value,
                tenure_rationale,
                psc_event_value,
                psc_event_rationale,
                *([None] * len(RUBRIC_DIMENSION_COLUMNS)),
                None,
            ]
            ws.append(row)
    finally:
        if owns_client:
            client.close()

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
