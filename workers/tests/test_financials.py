"""Tests for enrichment/financials.py."""
from __future__ import annotations

from cp_workers.enrichment.financials import estimate_financials


def test_filed_accounts_used_when_present_high_confidence():
    balance_sheet = {"turnover_pence": 500_000_00, "ebitda_pence": 50_000_00, "as_of": "2025-01-01"}
    revenue, ebitda = estimate_financials(balance_sheet, employee_count=10, sector_tag="skincare-personal-care")

    assert revenue["method"] == "filed"
    assert revenue["confidence"] == "high"
    assert revenue["value_pence"] == 500_000_00
    assert ebitda["method"] == "filed"
    assert ebitda["value_pence"] == 50_000_00


def test_benchmark_fallback_when_no_filed_pnl():
    revenue, ebitda = estimate_financials({}, employee_count=5, sector_tag="skincare-personal-care")

    assert revenue["method"] == "benchmark"
    assert revenue["confidence"] == "med"
    assert revenue["value_pence"] > 0
    assert ebitda["method"] == "benchmark"
    assert 0 < ebitda["value_pence"] < revenue["value_pence"]


def test_unknown_sector_falls_back_to_default_bucket_low_confidence():
    revenue, ebitda = estimate_financials({}, employee_count=5, sector_tag="widgets")
    assert revenue["confidence"] == "low"
    assert ebitda["confidence"] == "low"


def test_missing_employee_count_degrades_gracefully_never_errors():
    revenue, ebitda = estimate_financials({}, employee_count=None, sector_tag="skincare-personal-care")
    assert revenue["confidence"] == "low"
    assert revenue["value_pence"] == 0
    assert ebitda["value_pence"] == 0


def test_missing_balance_sheet_never_errors():
    revenue, ebitda = estimate_financials(None, employee_count=8, sector_tag="skincare-personal-care")
    assert revenue["method"] == "benchmark"
    assert ebitda["method"] == "benchmark"


def test_never_presented_as_facts_always_carries_confidence_and_method():
    revenue, ebitda = estimate_financials({}, employee_count=3, sector_tag=None)
    for estimate in (revenue, ebitda):
        assert set(estimate.keys()) >= {"value_pence", "source", "method", "confidence", "as_of"}
        assert estimate["confidence"] in ("high", "med", "low")
