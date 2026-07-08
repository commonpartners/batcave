"""Tests for connectors/discovery.py: taxonomy matching, universe filters,
sector classification, and the CH officers/PSC -> people mapping."""
from __future__ import annotations

from datetime import date

import pytest

from cp_workers.connectors.discovery import (
    classify_sector,
    is_taxonomy_candidate,
    officers_and_psc_to_people,
    passes_universe_filters,
)

TAXONOMY_RULES = [
    {
        "sector_tag": "skincare-personal-care",
        "sic_codes": [
            "20420", "46450", "47750", "20411", "20412", "96020", "86900",
            "47910", "47190", "47990",
        ],
        "include_keywords": [
            "skincare", "skin care", "cosmetics", "beauty", "botanical", "organic",
            "natural", "serum", "balm", "soap", "bath", "body care", "haircare",
            "aromatherapy", "spa",
        ],
        "exclude_keywords": [
            "software", "app", "platform", "clinic", "surgery", "pharma",
            "medical device", "salon-only",
        ],
        "active": True,
    }
]


# ---------------------------------------------------------------------------
# is_taxonomy_candidate
# ---------------------------------------------------------------------------


def test_candidate_via_sic_code():
    assert is_taxonomy_candidate("Generic Trading Ltd", ["20420"], TAXONOMY_RULES) is True


def test_candidate_via_keyword():
    assert is_taxonomy_candidate("Willow Botanical Skincare Ltd", ["62012"], TAXONOMY_RULES) is True


def test_not_a_candidate():
    assert is_taxonomy_candidate("Generic IT Services Ltd", ["62012"], TAXONOMY_RULES) is False


# ---------------------------------------------------------------------------
# passes_universe_filters
# ---------------------------------------------------------------------------


def test_universe_filters_pass():
    ok, reason = passes_universe_filters(
        status="Active",
        incorporation_date=date(2010, 1, 1),
        name="Willow Botanical Skincare Ltd",
        min_age_years=8,
        taxonomy_rules=TAXONOMY_RULES,
        today=date(2026, 7, 8),
    )
    assert ok is True
    assert reason is None


def test_universe_filters_rejects_non_active_status():
    ok, reason = passes_universe_filters(
        status="Liquidation",
        incorporation_date=date(2010, 1, 1),
        name="Willow Botanical Skincare Ltd",
        min_age_years=8,
        taxonomy_rules=TAXONOMY_RULES,
        today=date(2026, 7, 8),
    )
    assert ok is False
    assert "active" in reason


def test_universe_filters_rejects_too_young():
    ok, reason = passes_universe_filters(
        status="Active",
        incorporation_date=date(2024, 1, 1),
        name="Willow Botanical Skincare Ltd",
        min_age_years=8,
        taxonomy_rules=TAXONOMY_RULES,
        today=date(2026, 7, 8),
    )
    assert ok is False
    assert "age" in reason


def test_universe_filters_rejects_exclude_keyword():
    ok, reason = passes_universe_filters(
        status="Active",
        incorporation_date=date(2010, 1, 1),
        name="Skincare Software Platform Ltd",
        min_age_years=8,
        taxonomy_rules=TAXONOMY_RULES,
        today=date(2026, 7, 8),
    )
    assert ok is False
    assert "exclude" in reason


def test_universe_filters_rejects_missing_incorporation_date():
    ok, reason = passes_universe_filters(
        status="Active",
        incorporation_date=None,
        name="Willow Botanical Skincare Ltd",
        min_age_years=8,
        taxonomy_rules=TAXONOMY_RULES,
        today=date(2026, 7, 8),
    )
    assert ok is False
    assert "incorporation" in reason


# ---------------------------------------------------------------------------
# classify_sector
# ---------------------------------------------------------------------------


def test_classify_sector_confident_rules_match():
    tag, confidence, source = classify_sector(
        "Willow Botanical Skincare Ltd", None, ["20420"], taxonomy_rules=TAXONOMY_RULES
    )
    assert tag == "skincare-personal-care"
    assert confidence >= 0.7
    assert source == "rules"


def test_classify_sector_no_signal_at_all():
    tag, confidence, source = classify_sector(
        "Generic IT Consultancy Ltd", None, ["62012"], taxonomy_rules=TAXONOMY_RULES
    )
    assert tag == "uncategorised"
    assert source == "rules"
    assert confidence >= 0.7


def test_classify_sector_ambiguous_falls_back_to_llm():
    calls = []

    def fake_llm(name, website_text, sic_codes):
        calls.append((name, website_text, sic_codes))
        return "skincare-personal-care", 0.85, "brand website confirms skincare product line"

    # SIC hit (47910) but no include-keyword hit -> ambiguous per spec 02 §2.
    tag, confidence, source = classify_sector(
        "Riverside Trading Co Ltd",
        "we sell homeware and gifts online",
        ["47910"],
        taxonomy_rules=TAXONOMY_RULES,
        llm_classify=fake_llm,
    )
    assert calls  # LLM fallback was actually invoked
    assert tag == "skincare-personal-care"
    assert confidence == 0.85
    assert source == "llm"


def test_classify_sector_low_confidence_llm_forces_needs_review():
    def fake_llm(name, website_text, sic_codes):
        return "skincare-personal-care", 0.4, "genuinely unclear from available data"

    tag, confidence, source = classify_sector(
        "Riverside Trading Co Ltd",
        None,
        ["47910"],
        taxonomy_rules=TAXONOMY_RULES,
        llm_classify=fake_llm,
    )
    assert tag == "needs-review"
    assert confidence == 0.4
    assert source == "llm"


def test_classify_sector_exclude_keyword_overridden_by_strong_product_evidence():
    # "clinic" is an exclude keyword, but SIC + "beauty" include-keyword both
    # hit -> spec 02 §2's "unless product line evident" carve-out applies.
    tag, confidence, source = classify_sector(
        "Beauty Clinic Skincare Products Ltd", None, ["20420"], taxonomy_rules=TAXONOMY_RULES
    )
    assert tag == "skincare-personal-care"
    assert source == "rules"


# ---------------------------------------------------------------------------
# officers_and_psc_to_people
# ---------------------------------------------------------------------------


def test_officers_and_psc_to_people_mapping():
    officers = {
        "items": [
            {
                "name": "SMITH, John",
                "officer_role": "director",
                "appointed_on": "2010-01-01",
                "date_of_birth": {"month": 5, "year": 1960},
            },
            {
                "name": "DOE, Jane",
                "officer_role": "secretary",
                "appointed_on": "2015-01-01",
                "resigned_on": "2020-01-01",
            },
        ]
    }
    psc = {
        "items": [
            {
                "name": "SMITH, John",
                "date_of_birth": {"month": 5, "year": 1960},
                "natures_of_control": ["ownership-of-shares-25-to-50-percent"],
            }
        ]
    }
    people = officers_and_psc_to_people(officers, psc, date(2026, 7, 8))

    director = next(p for p in people if p["role"] == "director")
    assert director["is_active"] is True
    assert director["birth_year"] == 1960
    assert director["tenure_years"] == pytest.approx((date(2026, 7, 8) - date(2010, 1, 1)).days / 365.25)

    secretary = next(p for p in people if p["role"] == "secretary")
    assert secretary["is_active"] is False

    psc_person = next(p for p in people if p["role"] == "psc")
    assert psc_person["ownership_pct_band"] == "25-50"
    assert psc_person["is_active"] is True


def test_officers_and_psc_to_people_skips_uninteresting_roles():
    officers = {"items": [{"name": "X", "officer_role": "llp-member"}]}
    people = officers_and_psc_to_people(officers, {}, date(2026, 7, 8))
    assert people == []
