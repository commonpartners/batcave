"""compute_pregate is pure — the persistence half (run_pregate /
enrichment_candidates) is thin Supabase plumbing exercised in integration."""
from datetime import date

from cp_workers.scoring.pregate import DEFAULT_WEIGHTS, compute_pregate

NOW = date(2026, 7, 8)


def _company(**overrides) -> dict:
    base = {
        "company_number": "01234567",
        "size_band": "fit-now",
        "sector_tags": ["skincare-personal-care"],
        "sector_tag_source": "rules",
        "incorporation_date": "2000-01-01",
        "company_status": "active",
        "balance_sheet": {"net_assets": 500_000_00},
    }
    base.update(overrides)
    return base


FULL_SUCCESSION = {
    "director_retirement_window": 1.0,
    "long_single_owner_tenure": 0.8,
    "board_psc_event_recent": 0.0,
}


def test_perfect_candidate_scores_high():
    score, detail = compute_pregate(_company(), FULL_SUCCESSION, now=NOW)
    assert score == 1.0
    assert detail["components"]["succession"] == 1.0


def test_succession_uses_max_of_family():
    score, detail = compute_pregate(
        _company(), {"long_single_owner_tenure": 0.6}, now=NOW
    )
    assert detail["components"]["succession"] == 0.6


def test_no_succession_still_scores_other_components():
    score, detail = compute_pregate(_company(), {}, now=NOW)
    assert detail["components"]["succession"] == 0.0
    assert score == round(1.0 * 0.25 + 1.0 * 0.20 + 1.0 * 0.15, 4)


def test_size_band_mapping():
    for band, expected in [("fit-now", 1.0), ("stretch", 0.6), ("unknown", 0.5), ("too-small", 0.0)]:
        _, detail = compute_pregate(_company(size_band=band), {}, now=NOW)
        assert detail["components"]["size_fit"] == expected


def test_needs_review_sector_discounted():
    _, detail = compute_pregate(
        _company(sector_tags=["needs-review"]), {}, now=NOW
    )
    assert detail["components"]["sector_confidence"] == 0.4


def test_llm_classified_sector_mid_confidence():
    _, detail = compute_pregate(_company(sector_tag_source="llm"), {}, now=NOW)
    assert detail["components"]["sector_confidence"] == 0.7


def test_foundations_penalise_young_inactive_negative_assets():
    company = _company(
        incorporation_date="2023-01-01",
        company_status="liquidation",
        balance_sheet={"net_assets": -10_000},
    )
    _, detail = compute_pregate(company, {}, now=NOW)
    assert detail["components"]["foundations"] == 0.0


def test_missing_balance_sheet_is_neutral_not_zero():
    _, detail = compute_pregate(_company(balance_sheet=None), {}, now=NOW)
    # age(1.0) + active(1.0) + unknown net assets(0.5) / 3
    assert detail["components"]["foundations"] == round(2.5 / 3, 4)


def test_weights_config_overrides_defaults():
    weights = {"succession": 1.0, "size_fit": 0.0, "sector_confidence": 0.0, "foundations": 0.0}
    score, _ = compute_pregate(_company(size_band="too-small"), FULL_SUCCESSION, weights=weights, now=NOW)
    assert score == 1.0


def test_default_weights_sum_to_one():
    assert round(sum(DEFAULT_WEIGHTS.values()), 6) == 1.0


def test_missing_incorporation_date_fails_age_part_gracefully():
    _, detail = compute_pregate(_company(incorporation_date=None), {}, now=NOW)
    assert detail["inputs"]["company_age_years"] is None
    assert 0.0 <= detail["components"]["foundations"] <= 1.0
