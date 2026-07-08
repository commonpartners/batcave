"""Edge-case tests for signals/latent_upside.py, especially the exact
`latent_digital_upside_dimension` formula the scoring engine imports directly
(CONTRACT.md: "the ONLY place this formula is implemented")."""
from __future__ import annotations

import pytest

from cp_workers.signals.latent_upside import (
    heritage_underexploited,
    latent_digital_upside_dimension,
    narrow_distribution,
    reviews_strong_digital_weak,
)


class TestLatentDigitalUpsideDimension:
    def test_formula_matches_spec_exactly_digital_maturity_1(self):
        # digital_maturity=1 -> (1 - (1-1)/4) = 1 -> full weight on review_strength
        review_strength = 0.8
        result = latent_digital_upside_dimension(review_strength, digital_maturity=1, distribution_breadth=0.9)
        expected = 5 * review_strength * (1 - (1 - 1) / 4)
        assert result == pytest.approx(expected)
        assert result == pytest.approx(4.0)

    def test_formula_matches_spec_exactly_digital_maturity_5(self):
        # digital_maturity=5 -> (1 - (5-1)/4) = 0 -> score should be exactly 0
        # regardless of review_strength (no distribution bonus applied since
        # distribution_breadth is high here).
        result = latent_digital_upside_dimension(0.9, digital_maturity=5, distribution_breadth=0.9)
        assert result == pytest.approx(0.0)

    def test_distribution_bonus_applied_below_threshold(self):
        review_strength = 0.5
        digital_maturity = 3
        base = 5 * review_strength * (1 - (digital_maturity - 1) / 4)
        with_bonus = latent_digital_upside_dimension(review_strength, digital_maturity, distribution_breadth=0.29)
        assert with_bonus == pytest.approx(base + 0.5)

    def test_distribution_bonus_not_applied_at_threshold(self):
        # distribution_breadth == 0.3 is NOT < 0.3, so no bonus.
        review_strength = 0.5
        digital_maturity = 3
        base = 5 * review_strength * (1 - (digital_maturity - 1) / 4)
        no_bonus = latent_digital_upside_dimension(review_strength, digital_maturity, distribution_breadth=0.3)
        assert no_bonus == pytest.approx(base)

    def test_distribution_bonus_not_applied_just_above_threshold(self):
        review_strength = 0.5
        digital_maturity = 3
        base = 5 * review_strength * (1 - (digital_maturity - 1) / 4)
        result = latent_digital_upside_dimension(review_strength, digital_maturity, distribution_breadth=0.301)
        assert result == pytest.approx(base)

    def test_capped_at_5(self):
        # review_strength=1, digital_maturity=1 -> base 5.0, + 0.5 bonus would
        # exceed 5 -- must clamp to exactly 5.0.
        result = latent_digital_upside_dimension(1.0, digital_maturity=1, distribution_breadth=0.0)
        assert result == 5.0

    def test_floored_at_0(self):
        result = latent_digital_upside_dimension(0.0, digital_maturity=5, distribution_breadth=1.0)
        assert result == 0.0

    def test_digital_maturity_clamped_to_valid_range(self):
        # Defensive: out-of-range digital_maturity should not blow up the formula.
        result = latent_digital_upside_dimension(0.5, digital_maturity=10, distribution_breadth=1.0)
        assert 0.0 <= result <= 5.0


class TestReviewsStrongDigitalWeak:
    def test_matches_spec_formula(self):
        review_strength = 0.7
        digital_maturity = 2
        value, evidence, rationale = reviews_strong_digital_weak(review_strength, digital_maturity)
        expected = review_strength * (1 - (digital_maturity - 1) / 4)
        assert value == pytest.approx(expected)
        assert evidence["review_strength"] == review_strength
        assert evidence["digital_maturity"] == digital_maturity
        assert isinstance(rationale, str) and rationale

    def test_zero_review_strength_never_errors(self):
        value, _evidence, _rationale = reviews_strong_digital_weak(0.0, 5)
        assert value == 0.0


class TestNarrowDistribution:
    def test_narrow_with_no_stockists_and_no_marketplace(self):
        value, evidence, rationale = narrow_distribution(0.8, notable_stockists_count=0, marketplace_presence=False)
        assert value > 0
        assert evidence["notable_stockists_count"] == 0
        assert "narrow" in rationale.lower() or "distribution" in rationale.lower()

    def test_broad_distribution_scores_low(self):
        value, _evidence, _rationale = narrow_distribution(0.8, notable_stockists_count=10, marketplace_presence=True)
        assert value < 0.3

    def test_zero_review_strength_never_errors(self):
        value, _evidence, _rationale = narrow_distribution(0.0, notable_stockists_count=0, marketplace_presence=False)
        assert value == 0.0


class TestHeritageUnderexploited:
    def test_old_recognised_low_maturity_brand_scores_high(self):
        value, evidence, rationale = heritage_underexploited(
            company_age_years=30, brand_recognition_evidence=True, digital_maturity=1
        )
        assert value > 0.5
        assert evidence["company_age_years"] == 30

    def test_no_brand_recognition_scores_zero(self):
        value, _evidence, rationale = heritage_underexploited(
            company_age_years=40, brand_recognition_evidence=False, digital_maturity=1
        )
        assert value == 0.0
        assert "recognition" in rationale.lower() or "unproven" in rationale.lower()

    def test_young_company_never_errors(self):
        value, _evidence, _rationale = heritage_underexploited(
            company_age_years=0, brand_recognition_evidence=True, digital_maturity=1
        )
        assert value == 0.0

    def test_high_digital_maturity_reduces_value(self):
        low_maturity_value, _, _ = heritage_underexploited(25, True, digital_maturity=1)
        high_maturity_value, _, _ = heritage_underexploited(25, True, digital_maturity=5)
        assert high_maturity_value < low_maturity_value
        assert high_maturity_value == pytest.approx(0.0)
