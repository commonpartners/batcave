"""Enrichment orchestration (spec 03 §8).

`enrich_company` runs every enrichment step independently — one step failing
never blocks the others — with `tenacity` retries (3 attempts, exponential
backoff) per step. Per-field freshness comes for free from `source_records`
(each step calls `db.record_source` before parsing, per spec 00 §4); on
completion the company's `lifecycle` becomes `enriched`.

Failure discipline (spec 03 §8): a step that still fails after retries is
recorded in the returned `EnrichReport.failures` list (step, error) rather
than raising. When an in-flight `jobs` row is passed in via the optional
`job=` kwarg, failures are also appended to that job's `stats.failures` so a
future `cli.py enrich --pending` wrapper can roll them up into
`jobs.stats.failures` for 3-strike `enrichment-blocked` surfacing (spec 03
§8) without this module needing to own job lifecycle itself (that's
`cp_workers.jobs`, shared infra).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

from tenacity import Retrying, stop_after_attempt, wait_exponential

from cp_workers import db
from cp_workers.enrichment import distribution, financials, reviews, social, webtech, website
from cp_workers.enrichment.digital_maturity import compute_digital_maturity
from cp_workers.signals import latent_upside

_RETRY_ATTEMPTS = 3
_RETRY_WAIT_MIN = 1
_RETRY_WAIT_MAX = 8


@dataclass
class EnrichReport:
    """Result of one `enrich_company` run."""

    company_number: str
    lifecycle: str = "discovered"
    completed_steps: list[str] = field(default_factory=list)
    skipped_steps: list[str] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    fields_updated: dict[str, Any] = field(default_factory=dict)


def _run_step(name: str, fn: Callable[[], Any], report: EnrichReport, job: dict | None = None) -> Any | None:
    """Run one enrichment step with tenacity retries; never lets it raise out.

    On success, returns the step's result and appends `name` to
    `report.completed_steps`. On exhausted retries, appends a failure entry to
    `report.failures` (and to `job["stats"]["failures"]` if a job was passed
    in) and returns `None` — the caller is expected to treat `None` as "no
    data from this step this run, previous data (if any) stands."
    """
    retryer = Retrying(
        stop=stop_after_attempt(_RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=1, min=_RETRY_WAIT_MIN, max=_RETRY_WAIT_MAX),
        reraise=True,
    )
    try:
        result = retryer(fn)
        report.completed_steps.append(name)
        return result
    except Exception as exc:  # noqa: BLE001 - a failing step must never block the others
        error_text = str(exc)
        report.failures.append({"step": name, "error": error_text})
        if job is not None:
            stats = job.setdefault("stats", {}) or {}
            job["stats"] = stats
            stats.setdefault("failures", []).append(
                {
                    "company_number": report.company_number,
                    "step": name,
                    "error": error_text,
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
        return None


def _company_age_years(incorporation_date: str | date | None) -> float:
    if not incorporation_date:
        return 0.0
    if isinstance(incorporation_date, str):
        try:
            incorporation_date = date.fromisoformat(incorporation_date[:10])
        except ValueError:
            return 0.0
    today = datetime.now(timezone.utc).date()
    return max(0.0, (today - incorporation_date).days / 365.25)


def _domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    from urllib.parse import urlparse

    netloc = urlparse(url).netloc or url
    return netloc.removeprefix("www.")


def enrich_company(company_number: str, *, job: dict | None = None) -> EnrichReport:
    """Enrich one company end-to-end. Every step is independent and retried.

    `job` is an optional in-flight `jobs` row (as returned by
    `cp_workers.jobs.start_job`) — when provided, per-step failures are also
    appended to `job["stats"]["failures"]` so the caller's eventual
    `jobs.finish_job(job, ..., stats=job["stats"])` call captures them (spec 03
    §8). This is additive/optional and doesn't change the core
    `enrich_company(company_number)` contract shape.
    """
    report = EnrichReport(company_number=company_number)

    company = db.get_company_by_number(company_number)
    if company is None:
        raise ValueError(f"no company found for company_number={company_number!r}; discover it first")

    company_id = company["id"]
    fields: dict[str, Any] = {}

    # -- 1. Website resolution -------------------------------------------------
    def _resolve() -> tuple[str | None, float]:
        existing_url = company.get("website")
        if existing_url:
            return existing_url, 1.0
        return website.resolve_website(
            company.get("legal_name", ""),
            company.get("trading_names") or [],
            company_number=company_number,
        )

    resolved = _run_step("website_resolve", _resolve, report, job)
    resolved_url, resolve_confidence = resolved if resolved else (None, 0.0)
    if resolved_url and resolved_url != company.get("website"):
        fields["website"] = resolved_url
    if not resolved_url:
        report.skipped_steps.extend(["website_crawl", "webtech", "website_extract"])

    pages: dict[str, dict[str, Any]] = {}
    homepage_html = ""
    homepage_headers: dict[str, str] = {}

    # -- 2. Crawl (skip-unchanged tracked here so §4's LLM call can skip too) --
    crawl_unchanged = False
    if resolved_url:
        previous_crawl_hash = db.last_source_hash(company_id=company_id, source="website_crawl")

        def _crawl() -> dict[str, Any]:
            result = website.crawl_website(resolved_url)
            db.record_source(
                company_id=company_id,
                source="website_crawl",
                source_url=resolved_url,
                raw=result,
            )
            return result

        crawl_result = _run_step("website_crawl", _crawl, report, job)
        if crawl_result:
            pages = crawl_result.get("pages", {})
            homepage_page = pages.get(resolved_url) or next(iter(pages.values()), {})
            homepage_html = homepage_page.get("html", "")
            homepage_headers = homepage_page.get("headers", {})
            # Same payload shape `record_source` hashed internally, so this
            # comparison is apples-to-apples with what's stored in
            # `source_records.content_hash` (spec 03 §1 skip-unchanged).
            crawl_unchanged = previous_crawl_hash is not None and previous_crawl_hash == db.content_hash(crawl_result)

    # -- 3. Web-tech (deterministic, no LLM) ------------------------------------
    # No resolved website at all -> explicitly "not functional" rather than an
    # empty dict, so `compute_digital_maturity` correctly lands on score 1
    # instead of defaulting `site_functional` to True.
    detected_webtech: dict[str, Any] = {"site_functional": False}
    if resolved_url:
        def _webtech() -> dict[str, Any]:
            return webtech.detect_webtech(homepage_html, homepage_headers)

        detected_webtech = _run_step("webtech", _webtech, report, job) or {"site_functional": False}

    # -- 4. LLM extraction (skip-unchanged: spec 03 §1 "skip re-extraction and
    #       any downstream LLM call" when the crawled content hasn't changed) --
    extracted_profile: dict[str, Any] = {}
    if resolved_url and pages:
        if crawl_unchanged:
            report.skipped_steps.append("website_extract")
        else:
            page_texts = {url: p.get("text", "") for url, p in pages.items()}

            def _extract() -> dict[str, Any]:
                return website.extract_profile(page_texts)

            extracted_profile = _run_step("website_extract", _extract, report, job) or {}

    has_ecommerce = bool(extracted_profile.get("has_ecommerce", False))
    if extracted_profile.get("trading_names"):
        fields["trading_names"] = sorted(
            set((company.get("trading_names") or [])) | set(extracted_profile["trading_names"])
        )
    if extracted_profile.get("heritage_summary") or extracted_profile.get("product_range_summary"):
        fields["summary"] = extracted_profile.get("heritage_summary") or extracted_profile.get(
            "product_range_summary"
        )

    # -- 5. Reviews --------------------------------------------------------------
    domain = _domain_from_url(resolved_url)
    trustpilot_current: dict[str, Any] | None = None
    trustpilot_previous: dict[str, Any] | None = None

    if domain:
        # Capture the previous fetch *before* this run's fetch potentially
        # inserts a new source_records row, so the trend comparison is always
        # "this run vs the last completed run", never "this run vs itself".
        trustpilot_previous = _previous_source_raw(company_id, "trustpilot", offset=0)

        def _reviews_trustpilot() -> dict[str, Any] | None:
            result = reviews.fetch_trustpilot(domain)
            if result is not None:
                db.record_source(
                    company_id=company_id, source="trustpilot", source_url=f"https://uk.trustpilot.com/review/{domain}", raw=result
                )
            return result

        trustpilot_current = _run_step("reviews_trustpilot", _reviews_trustpilot, report, job)

    def _reviews_google() -> dict[str, Any] | None:
        result = reviews.fetch_google_reviews(company.get("legal_name", ""))
        if result is not None:
            db.record_source(company_id=company_id, source="google_reviews", source_url=None, raw=result)
        return result

    google_current = _run_step("reviews_google", _reviews_google, report, job)

    review_source = trustpilot_current or google_current
    computed_review_strength = 0.0
    computed_review_trend = "flat"
    if review_source:
        computed_review_strength = reviews.review_strength(review_source.get("rating"), review_source.get("count"))
        computed_review_trend = reviews.review_trend(trustpilot_current, trustpilot_previous)
    else:
        report.skipped_steps.append("reviews")

    # -- 6. Social (best-effort) --------------------------------------------------
    def _social() -> dict[str, Any]:
        handles = website.extract_social_handles(homepage_html)
        result = social.fetch_social(handles)
        if result:
            db.record_source(company_id=company_id, source="social", source_url=None, raw=result)
        return result

    social_result = _run_step("social", _social, report, job) or {}
    if not social_result:
        report.skipped_steps.append("social")

    # -- 7. Distribution -----------------------------------------------------------
    notable_stockists = extracted_profile.get("stockists_mentioned") or []

    def _distribution() -> float:
        return distribution.distribution_breadth(notable_stockists, None)

    computed_distribution_breadth = _run_step("distribution", _distribution, report, job)
    if computed_distribution_breadth is None:
        computed_distribution_breadth = 0.0

    # -- 8. Financials ---------------------------------------------------------------
    def _financials() -> tuple[dict[str, Any], dict[str, Any]]:
        return financials.estimate_financials(
            company.get("balance_sheet"),
            company.get("employee_count"),
            (company.get("sector_tags") or [None])[0],
        )

    financials_result = _run_step("financials", _financials, report, job)
    if financials_result:
        fields["revenue_estimate"], fields["ebitda_estimate"] = financials_result

    # -- 9. Digital maturity (pure, deterministic) ------------------------------------
    def _maturity() -> int:
        return compute_digital_maturity(detected_webtech, has_ecommerce)

    computed_digital_maturity = _run_step("digital_maturity", _maturity, report, job)
    if computed_digital_maturity is not None:
        fields["digital_maturity"] = computed_digital_maturity
    else:
        computed_digital_maturity = company.get("digital_maturity") or 1

    # -- 10. Latent-upside signals -----------------------------------------------------
    def _signals() -> list[dict[str, Any]]:
        rows = []
        rsdw_value, rsdw_evidence, rsdw_rationale = latent_upside.reviews_strong_digital_weak(
            computed_review_strength, computed_digital_maturity
        )
        # `distribution_breadth`/`review_trend` have no dedicated `companies`
        # column in the actual SQL (spec 03 §6 implies them, but
        # 0002_companies.sql doesn't define them) — carried here as signal
        # evidence so the scoring engine (Agent C) has a place to read the raw
        # ingredients for `latent_digital_upside_dimension` from.
        rsdw_evidence = {
            **rsdw_evidence,
            "review_trend": computed_review_trend,
            "distribution_breadth": computed_distribution_breadth,
        }
        rows.append(("reviews_strong_digital_weak", rsdw_value, rsdw_evidence, rsdw_rationale))

        nd_value, nd_evidence, nd_rationale = latent_upside.narrow_distribution(
            computed_review_strength, len(notable_stockists), bool(computed_distribution_breadth and computed_distribution_breadth > 0.5)
        )
        rows.append(("narrow_distribution", nd_value, nd_evidence, nd_rationale))

        heritage_evidence = bool(extracted_profile.get("heritage_summary"))
        hu_value, hu_evidence, hu_rationale = latent_upside.heritage_underexploited(
            _company_age_years(company.get("incorporation_date")), heritage_evidence, computed_digital_maturity
        )
        rows.append(("heritage_underexploited", hu_value, hu_evidence, hu_rationale))

        client = db.get_client()
        for name, value, evidence, rationale in rows:
            client.table("signals").insert(
                {
                    "company_id": company_id,
                    "family": "latent_upside",
                    "name": name,
                    "value": value,
                    "evidence": evidence,
                    "rationale": rationale,
                    "signal_version": "1.0.0",
                }
            ).execute()
        return rows

    _run_step("latent_upside_signals", _signals, report, job)

    # -- Persist --------------------------------------------------------------------
    fields["lifecycle"] = "enriched"
    db.upsert_company(company_number, fields)

    report.lifecycle = "enriched"
    report.fields_updated = fields
    return report


def _previous_source_raw(company_id: str, source: str, offset: int = 1) -> dict[str, Any] | None:
    """Second-most-recent `raw` payload for (company_id, source) — used to
    compute trend vs the previous fetch. `offset=1` skips the just-recorded
    row (the current fetch) to get the one before it."""
    client = db.get_client()
    resp = (
        client.table("source_records")
        .select("raw")
        .eq("company_id", company_id)
        .eq("source", source)
        .order("fetched_at", desc=True)
        .limit(offset + 1)
        .execute()
    )
    rows = resp.data or []
    if len(rows) <= offset:
        return None
    return rows[offset].get("raw")
