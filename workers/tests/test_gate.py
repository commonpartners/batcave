"""Exhaustive tests for scoring/gate.py — every test's pass/hold/fail boundary,
plus compute_size_band across missing-data combinations (spec 04 §2)."""
from __future__ import annotations

import copy

import pytest

from cp_workers.scoring.gate import compute_size_band, run_gate

GATE_CONFIG = {
    "min_company_age_years": 8,
    "shortlist_threshold": 60,
    "watchlist_auto_score_threshold": 70,
    "watchlist_succession_signal_floor": 0.5,
    "situation_succession_signal_floor": 0.3,
    "size_band_thresholds": {
        "fit_now_ev_max_gbp": 5_000_000,
        "stretch_ebitda_max_gbp": 10_000_000,
    },
}

BASE_PROFILE = {
    "sector_tags": ["skincare-personal-care"],
    "sector_tag_source": "rules",
    "product_type": "physical_product",
    "ebitda_estimate": {"value_pence": 200_000_000, "confidence": "high"},  # £2,000,000
    "revenue_estimate": None,
    "balance_sheet": {"net_assets": 100_000},
    "employee_count": 25,
    "company_age_years": 10,
    "company_status": "active",
    "insolvency_events": False,
    "pre_revenue": False,
    "shrinking": False,
    "plausibly_profitable": None,
    "succession_signal_max": 0.6,
    "recently_funded": False,
    "country": "UK",
}


def profile(**overrides):
    p = copy.deepcopy(BASE_PROFILE)
    p.update(overrides)
    return p


# --------------------------------------------------------------------------
# compute_size_band
# --------------------------------------------------------------------------
class TestComputeSizeBand:
    def test_ebitda_fit_now(self):
        assert (
            compute_size_band({"value_pence": 200_000_000}, None, None, None, GATE_CONFIG["size_band_thresholds"])
            == "fit-now"
        )

    def test_ebitda_stretch(self):
        assert (
            compute_size_band({"value_pence": 700_000_000}, None, None, None, GATE_CONFIG["size_band_thresholds"])
            == "stretch"
        )

    def test_ebitda_too_large(self):
        assert (
            compute_size_band({"value_pence": 1_200_000_000}, None, None, None, GATE_CONFIG["size_band_thresholds"])
            == "too-large"
        )

    def test_ebitda_too_small(self):
        assert (
            compute_size_band({"value_pence": 5_000_000}, None, None, None, GATE_CONFIG["size_band_thresholds"])
            == "too-small"
        )

    def test_revenue_fallback_when_ebitda_missing(self):
        # £3,000,000 revenue * 10% fallback margin = £300,000 EBITDA-implied -> fit-now
        band = compute_size_band(
            None, {"value_pence": 300_000_000}, None, None, GATE_CONFIG["size_band_thresholds"]
        )
        assert band == "fit-now"

    def test_balance_sheet_employee_fallback_when_ebitda_and_revenue_missing(self):
        # 20 employees * £15,000/head proxy = £300,000 -> fit-now
        band = compute_size_band(
            None, None, {"net_assets": 50_000}, 20, GATE_CONFIG["size_band_thresholds"]
        )
        assert band == "fit-now"

    def test_balance_sheet_without_net_assets_does_not_guess(self):
        band = compute_size_band(None, None, {"cash": 1_000}, 20, GATE_CONFIG["size_band_thresholds"])
        assert band == "unknown"

    def test_all_missing_is_unknown_never_raises(self):
        assert compute_size_band(None, None, None, None, GATE_CONFIG["size_band_thresholds"]) == "unknown"

    def test_missing_thresholds_is_unknown(self):
        assert compute_size_band({"value_pence": 200_000_000}, None, None, None, {}) == "unknown"

    def test_boundary_exactly_at_fit_now_max(self):
        assert (
            compute_size_band({"value_pence": 500_000_000}, None, None, None, GATE_CONFIG["size_band_thresholds"])
            == "fit-now"
        )

    def test_boundary_exactly_at_stretch_max(self):
        assert (
            compute_size_band({"value_pence": 1_000_000_000}, None, None, None, GATE_CONFIG["size_band_thresholds"])
            == "stretch"
        )


# --------------------------------------------------------------------------
# run_gate — overall pass baseline
# --------------------------------------------------------------------------
def test_all_pass_baseline():
    result = run_gate(BASE_PROFILE, GATE_CONFIG)
    assert result["result"] == "pass"
    for test_name, detail in result["detail"].items():
        assert detail["result"] == "pass", f"{test_name} unexpectedly not pass: {detail}"


# --------------------------------------------------------------------------
# sector test
# --------------------------------------------------------------------------
class TestSector:
    def test_pass_launch_tag(self):
        r = run_gate(profile(sector_tags=["skincare-personal-care"]), GATE_CONFIG)
        assert r["detail"]["sector"]["result"] == "pass"

    def test_hold_needs_review_tag(self):
        r = run_gate(profile(sector_tags=["needs-review"]), GATE_CONFIG)
        assert r["detail"]["sector"]["result"] == "hold"

    def test_hold_needs_review_source(self):
        r = run_gate(profile(sector_tag_source="needs-review"), GATE_CONFIG)
        assert r["detail"]["sector"]["result"] == "hold"

    def test_hold_empty_tags(self):
        r = run_gate(profile(sector_tags=[]), GATE_CONFIG)
        assert r["detail"]["sector"]["result"] == "hold"

    def test_fail_excluded_tag(self):
        r = run_gate(profile(sector_tags=["software"]), GATE_CONFIG)
        assert r["detail"]["sector"]["result"] == "fail"

    def test_fail_out_of_scope_tag(self):
        r = run_gate(profile(sector_tags=["home-fragrance"]), GATE_CONFIG)
        assert r["detail"]["sector"]["result"] == "fail"


# --------------------------------------------------------------------------
# product type test
# --------------------------------------------------------------------------
class TestProductType:
    def test_pass_physical_product(self):
        assert run_gate(profile(product_type="physical_product"), GATE_CONFIG)["detail"]["product_type"]["result"] == "pass"

    def test_pass_service(self):
        assert run_gate(profile(product_type="service"), GATE_CONFIG)["detail"]["product_type"]["result"] == "pass"

    def test_fail_tech_product(self):
        assert run_gate(profile(product_type="tech_product"), GATE_CONFIG)["detail"]["product_type"]["result"] == "fail"

    def test_hold_ambiguous(self):
        assert run_gate(profile(product_type="ambiguous"), GATE_CONFIG)["detail"]["product_type"]["result"] == "hold"

    def test_hold_missing(self):
        assert run_gate(profile(product_type=None), GATE_CONFIG)["detail"]["product_type"]["result"] == "hold"


# --------------------------------------------------------------------------
# size test
# --------------------------------------------------------------------------
class TestSize:
    def test_pass_fit_now(self):
        r = run_gate(profile(size_band="fit-now"), GATE_CONFIG)
        assert r["detail"]["size"]["result"] == "pass"

    def test_fail_too_small(self):
        r = run_gate(profile(size_band="too-small"), GATE_CONFIG)
        assert r["detail"]["size"]["result"] == "fail"

    @pytest.mark.parametrize("band", ["stretch", "too-large", "unknown"])
    def test_hold_bands(self, band):
        r = run_gate(profile(size_band=band), GATE_CONFIG)
        assert r["detail"]["size"]["result"] == "hold"

    def test_computes_band_when_not_precomputed(self):
        p = profile()
        p.pop("size_band", None)
        r = run_gate(p, GATE_CONFIG)
        assert r["detail"]["size"]["result"] == "pass"  # BASE ebitda -> fit-now


# --------------------------------------------------------------------------
# foundations test
# --------------------------------------------------------------------------
class TestFoundations:
    def test_pass_baseline(self):
        assert run_gate(BASE_PROFILE, GATE_CONFIG)["detail"]["foundations"]["result"] == "pass"

    def test_fail_pre_revenue(self):
        r = run_gate(profile(pre_revenue=True), GATE_CONFIG)
        assert r["detail"]["foundations"]["result"] == "fail"

    def test_fail_insolvency_events(self):
        r = run_gate(profile(insolvency_events=True), GATE_CONFIG)
        assert r["detail"]["foundations"]["result"] == "fail"

    def test_fail_negative_net_assets_and_shrinking(self):
        r = run_gate(profile(balance_sheet={"net_assets": -10_000}, shrinking=True), GATE_CONFIG)
        assert r["detail"]["foundations"]["result"] == "fail"

    def test_hold_negative_net_assets_not_shrinking(self):
        r = run_gate(profile(balance_sheet={"net_assets": -10_000}, shrinking=False), GATE_CONFIG)
        assert r["detail"]["foundations"]["result"] == "hold"

    def test_hold_missing_age(self):
        r = run_gate(profile(company_age_years=None), GATE_CONFIG)
        assert r["detail"]["foundations"]["result"] == "hold"

    def test_hold_missing_status(self):
        r = run_gate(profile(company_status=None), GATE_CONFIG)
        assert r["detail"]["foundations"]["result"] == "hold"

    def test_hold_missing_net_assets(self):
        r = run_gate(profile(balance_sheet={}), GATE_CONFIG)
        assert r["detail"]["foundations"]["result"] == "hold"

    def test_hold_age_below_min(self):
        r = run_gate(profile(company_age_years=3), GATE_CONFIG)
        assert r["detail"]["foundations"]["result"] == "hold"

    def test_hold_not_active(self):
        r = run_gate(profile(company_status="dissolved"), GATE_CONFIG)
        assert r["detail"]["foundations"]["result"] == "hold"

    def test_pass_plausibly_profitable_with_nonpositive_net_assets(self):
        r = run_gate(
            profile(balance_sheet={"net_assets": 0}, plausibly_profitable=True),
            GATE_CONFIG,
        )
        assert r["detail"]["foundations"]["result"] == "pass"


# --------------------------------------------------------------------------
# situation test — never fails
# --------------------------------------------------------------------------
class TestSituation:
    def test_pass_strong_succession_signal(self):
        r = run_gate(profile(succession_signal_max=0.5), GATE_CONFIG)
        assert r["detail"]["situation"]["result"] == "pass"

    def test_pass_exactly_at_floor(self):
        r = run_gate(profile(succession_signal_max=0.3), GATE_CONFIG)
        assert r["detail"]["situation"]["result"] == "pass"

    def test_hold_weak_signal(self):
        r = run_gate(profile(succession_signal_max=0.1), GATE_CONFIG)
        assert r["detail"]["situation"]["result"] == "hold"

    def test_hold_missing_signal(self):
        r = run_gate(profile(succession_signal_max=None), GATE_CONFIG)
        assert r["detail"]["situation"]["result"] == "hold"

    def test_hold_recently_funded_never_fails(self):
        r = run_gate(profile(recently_funded=True, succession_signal_max=0.9), GATE_CONFIG)
        assert r["detail"]["situation"]["result"] == "hold"

    def test_situation_never_returns_fail(self):
        for signal in (None, 0.0, 0.1, 0.3, 0.5, 1.0):
            for funded in (True, False):
                r = run_gate(profile(succession_signal_max=signal, recently_funded=funded), GATE_CONFIG)
                assert r["detail"]["situation"]["result"] in ("pass", "hold")


# --------------------------------------------------------------------------
# geography test
# --------------------------------------------------------------------------
class TestGeography:
    def test_pass_uk(self):
        assert run_gate(profile(country="UK"), GATE_CONFIG)["detail"]["geography"]["result"] == "pass"

    def test_hold_non_uk(self):
        assert run_gate(profile(country="IE"), GATE_CONFIG)["detail"]["geography"]["result"] == "hold"

    def test_geography_never_returns_fail(self):
        for country in ("UK", "IE", "US", None):
            r = run_gate(profile(country=country), GATE_CONFIG)
            assert r["detail"]["geography"]["result"] in ("pass", "hold")


# --------------------------------------------------------------------------
# overall aggregation
# --------------------------------------------------------------------------
class TestOverallAggregation:
    def test_any_fail_wins(self):
        r = run_gate(profile(product_type="tech_product", country="IE"), GATE_CONFIG)
        assert r["result"] == "fail"

    def test_hold_when_no_fail_but_a_hold_present(self):
        r = run_gate(profile(country="IE"), GATE_CONFIG)
        assert r["result"] == "hold"

    def test_pass_when_everything_passes(self):
        r = run_gate(BASE_PROFILE, GATE_CONFIG)
        assert r["result"] == "pass"

    def test_never_crashes_on_completely_empty_profile(self):
        r = run_gate({}, {})
        assert r["result"] in ("pass", "hold", "fail")
        assert set(r["detail"].keys()) == {
            "sector",
            "product_type",
            "size",
            "foundations",
            "situation",
            "geography",
        }
