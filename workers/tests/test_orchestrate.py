"""Tests for enrichment/orchestrate.py.

Every external boundary (db.*, and each enrichment submodule's public
functions) is monkeypatched -- no live network or Supabase calls. Focus:
each step is independent (one failing never blocks the others or the final
`lifecycle='enriched'`), and missing-website/missing-reviews cases degrade
gracefully rather than raising.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cp_workers import db
from cp_workers.enrichment import financials, orchestrate, reviews, social, webtech, website


class FakeTable:
    def __init__(self, name: str, store: dict[str, list[dict]]):
        self.name = name
        self.store = store

    def insert(self, row):
        self.store.setdefault(self.name, []).append(row)
        return self

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class FakeClient:
    def __init__(self):
        self.store: dict[str, list[dict]] = {}

    def table(self, name):
        return FakeTable(name, self.store)


def _fake_company(**overrides) -> dict:
    base = {
        "id": "company-uuid-1",
        "company_number": "01234567",
        "legal_name": "Acme Botanicals Ltd",
        "trading_names": [],
        "website": None,
        "balance_sheet": {},
        "employee_count": 5,
        "sector_tags": ["skincare-personal-care"],
        "incorporation_date": "2000-01-01",
        "digital_maturity": None,
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    # Keep retry backoff at ~0 so failing-step tests don't actually sleep.
    monkeypatch.setattr(orchestrate, "_RETRY_WAIT_MIN", 0)
    monkeypatch.setattr(orchestrate, "_RETRY_WAIT_MAX", 0)


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(db, "get_client", lambda: client)
    return client


@pytest.fixture
def patch_db(monkeypatch, fake_client):
    monkeypatch.setattr(db, "record_source", lambda **kwargs: {"id": "src-1", **kwargs})
    monkeypatch.setattr(db, "last_source_hash", lambda **kwargs: None)

    upserts: list[tuple[str, dict]] = []

    def fake_upsert(company_number, fields):
        upserts.append((company_number, fields))
        return {"company_number": company_number, **fields}

    monkeypatch.setattr(db, "upsert_company", fake_upsert)
    return upserts


class TestMissingWebsiteDegrades:
    def test_missing_website_never_raises_and_completes(self, monkeypatch, patch_db):
        company = _fake_company(website=None)
        monkeypatch.setattr(db, "get_company_by_number", lambda number: company)
        monkeypatch.setattr(website, "resolve_website", lambda *a, **k: (None, 0.2))
        monkeypatch.setattr(reviews, "fetch_trustpilot", lambda domain: None)
        monkeypatch.setattr(reviews, "fetch_google_reviews", lambda query: None)

        report = orchestrate.enrich_company("01234567")

        assert report.lifecycle == "enriched"
        assert "website_crawl" in report.skipped_steps
        assert "webtech" in report.skipped_steps
        assert "website_extract" in report.skipped_steps
        assert "reviews" in report.skipped_steps
        assert report.fields_updated["digital_maturity"] == 1
        assert report.fields_updated["lifecycle"] == "enriched"
        assert patch_db  # upsert_company was called


class TestMissingReviewsDegrades:
    def test_missing_reviews_never_raises_and_completes(self, monkeypatch, patch_db):
        company = _fake_company(website="https://acmebotanicals.co.uk")
        monkeypatch.setattr(db, "get_company_by_number", lambda number: company)
        monkeypatch.setattr(
            website,
            "crawl_website",
            lambda url: {
                "pages": {url: {"text": "some page text", "html": "<html></html>", "headers": {}, "status": 200, "fetched_via": "http"}},
                "homepage": url,
            },
        )
        monkeypatch.setattr(webtech, "detect_webtech", lambda html, headers: {"site_functional": True})
        monkeypatch.setattr(website, "extract_profile", lambda page_texts: {})
        monkeypatch.setattr(reviews, "fetch_trustpilot", lambda domain: None)
        monkeypatch.setattr(reviews, "fetch_google_reviews", lambda query: None)
        monkeypatch.setattr(social, "fetch_social", lambda handles: {})

        report = orchestrate.enrich_company("01234567")

        assert report.lifecycle == "enriched"
        assert "reviews" in report.skipped_steps
        assert not any(f["step"].startswith("reviews") for f in report.failures)


class TestStepIndependence:
    def test_one_step_failing_never_blocks_the_others(self, monkeypatch, patch_db):
        company = _fake_company(website="https://acmebotanicals.co.uk")
        monkeypatch.setattr(db, "get_company_by_number", lambda number: company)
        monkeypatch.setattr(
            website,
            "crawl_website",
            lambda url: {
                "pages": {url: {"text": "great skincare brand", "html": "<html></html>", "headers": {}, "status": 200, "fetched_via": "http"}},
                "homepage": url,
            },
        )
        monkeypatch.setattr(webtech, "detect_webtech", lambda html, headers: {"site_functional": True, "platform": "shopify"})
        monkeypatch.setattr(website, "extract_profile", lambda page_texts: {"has_ecommerce": True, "stockists_mentioned": []})
        monkeypatch.setattr(reviews, "fetch_trustpilot", lambda domain: {"rating": 4.6, "count": 300})
        monkeypatch.setattr(reviews, "fetch_google_reviews", lambda query: None)
        monkeypatch.setattr(social, "fetch_social", lambda handles: {})

        def _always_fails(*args, **kwargs):
            raise RuntimeError("financial data provider is down")

        monkeypatch.setattr(financials, "estimate_financials", _always_fails)

        report = orchestrate.enrich_company("01234567")

        # The financials step failed after retries exhausted...
        assert any(f["step"] == "financials" for f in report.failures)
        # ...but everything else still completed and the company still reaches
        # lifecycle='enriched' (spec 03 §8: "one failing never blocks others").
        assert report.lifecycle == "enriched"
        assert "digital_maturity" in report.fields_updated
        assert "revenue_estimate" not in report.fields_updated
        assert "reviews_trustpilot" in report.completed_steps

    def test_unknown_company_raises_clear_error(self, monkeypatch, patch_db):
        monkeypatch.setattr(db, "get_company_by_number", lambda number: None)
        with pytest.raises(ValueError):
            orchestrate.enrich_company("99999999")

    def test_failures_recorded_onto_passed_in_job_stats(self, monkeypatch, patch_db):
        company = _fake_company(website="https://acmebotanicals.co.uk")
        monkeypatch.setattr(db, "get_company_by_number", lambda number: company)
        monkeypatch.setattr(website, "crawl_website", lambda url: (_ for _ in ()).throw(RuntimeError("crawl down")))
        monkeypatch.setattr(reviews, "fetch_trustpilot", lambda domain: None)
        monkeypatch.setattr(reviews, "fetch_google_reviews", lambda query: None)
        monkeypatch.setattr(social, "fetch_social", lambda handles: {})

        job = {"id": "job-1", "stats": {}}
        report = orchestrate.enrich_company("01234567", job=job)

        assert any(f["step"] == "website_crawl" for f in report.failures)
        assert any(f["step"] == "website_crawl" for f in job["stats"]["failures"])
        assert report.lifecycle == "enriched"


class TestSignalsWritten:
    def test_writes_three_latent_upside_signal_rows(self, monkeypatch, patch_db, fake_client):
        company = _fake_company(website="https://acmebotanicals.co.uk")
        monkeypatch.setattr(db, "get_company_by_number", lambda number: company)
        monkeypatch.setattr(
            website,
            "crawl_website",
            lambda url: {
                "pages": {url: {"text": "heritage skincare", "html": "<html></html>", "headers": {}, "status": 200, "fetched_via": "http"}},
                "homepage": url,
            },
        )
        monkeypatch.setattr(webtech, "detect_webtech", lambda html, headers: {"site_functional": True})
        monkeypatch.setattr(
            website, "extract_profile", lambda page_texts: {"has_ecommerce": True, "heritage_summary": "Since 1980"}
        )
        monkeypatch.setattr(reviews, "fetch_trustpilot", lambda domain: {"rating": 4.5, "count": 150})
        monkeypatch.setattr(reviews, "fetch_google_reviews", lambda query: None)
        monkeypatch.setattr(social, "fetch_social", lambda handles: {})

        orchestrate.enrich_company("01234567")

        signal_rows = fake_client.store.get("signals", [])
        names = {row["name"] for row in signal_rows}
        assert names == {"reviews_strong_digital_weak", "narrow_distribution", "heritage_underexploited"}
        for row in signal_rows:
            assert row["family"] == "latent_upside"
            assert 0.0 <= row["value"] <= 1.0
