"""Tests for scoring/dimensions.py — rules-based attractiveness dimensions.

``latent_digital_upside`` calls Agent B's
``cp_workers.signals.latent_upside.latent_digital_upside_dimension``. That
file may not exist yet (parallel build) or may already exist with the real
formula. Either way, these tests inject a fake module into
``sys.modules["cp_workers.signals.latent_upside"]`` with the exact
signature pinned in CONTRACT.md before calling the wrapper, so the test
suite never depends on Agent B's landing order or needs live network/API
access.
"""
from __future__ import annotations

import sys
import types

import pytest

from cp_workers.scoring import dimensions


def _install_fake_latent_upside(monkeypatch):
    """Installs a fake cp_workers.signals.latent_upside module implementing
    the exact formula from spec 04 §3 / CONTRACT.md so the wrapper test is
    self-contained regardless of whether Agent B's real file exists yet.
    """

    def latent_digital_upside_dimension(review_strength, digital_maturity, distribution_breadth):
        raw = 5 * review_strength * (1 - (digital_maturity - 1) / 4)
        if distribution_breadth < 0.3:
            raw += 0.5
        return min(raw, 5.0)

    fake_module = types.ModuleType("cp_workers.signals.latent_upside")
    fake_module.latent_digital_upside_dimension = latent_digital_upside_dimension
    monkeypatch.setitem(sys.modules, "cp_workers.signals.latent_upside", fake_module)


class TestFinancialQuality:
    def test_no_data_returns_neutral_default(self):
        raw, evidence, rationale = dimensions.financial_quality(None, None, None, None)
        assert raw == 2.5
        assert "neutral" in rationale

    def test_positive_net_assets_scores_higher_than_negative(self):
        raw_pos, _, _ = dimensions.financial_quality({"net_assets": 100_000}, None, None, None)
        raw_neg, _, _ = dimensions.financial_quality({"net_assets": -100_000}, None, None, None)
        assert raw_pos > raw_neg

    def test_low_confidence_estimate_caps_at_three(self):
        raw, evidence, rationale = dimensions.financial_quality(
            {"net_assets": 500_000, "cash": 400_000, "total_assets": 500_000},
            {"confidence": "low"},
            None,
            None,
        )
        assert raw <= 3.0
        assert evidence["confidence_capped"] is True

    def test_high_confidence_not_capped(self):
        raw, evidence, rationale = dimensions.financial_quality(
            {"net_assets": 500_000, "cash": 400_000, "total_assets": 500_000},
            {"confidence": "high"},
            {"confidence": "high"},
            None,
        )
        assert "confidence_capped" not in evidence

    def test_declining_net_asset_trend_scores_low(self):
        raw, evidence, _ = dimensions.financial_quality(
            {"net_assets": 100_000},
            None,
            None,
            None,
            previous_balance_sheet={"net_assets": 500_000},
        )
        assert evidence["net_asset_trend"] == "declining"

    def test_improving_net_asset_trend(self):
        raw, evidence, _ = dimensions.financial_quality(
            {"net_assets": 500_000},
            None,
            None,
            None,
            previous_balance_sheet={"net_assets": 100_000},
        )
        assert evidence["net_asset_trend"] == "improving"

    def test_score_always_in_bounds(self):
        raw, _, _ = dimensions.financial_quality(
            {"net_assets": 999_999_999, "cash": 999_999_999, "total_assets": 1, "creditors": 0},
            None,
            None,
            None,
        )
        assert 0.0 <= raw <= 5.0


class TestDealAccessibility:
    def test_no_signals_no_unadvised(self):
        raw, evidence, _ = dimensions.deal_accessibility({}, False)
        assert raw == 0.0

    def test_strongest_signal_drives_score(self):
        raw, evidence, _ = dimensions.deal_accessibility(
            {"director_retirement_window": 0.8, "long_single_owner_tenure": 0.2}, False
        )
        assert raw == pytest.approx(4.0)
        assert evidence["strongest_signal"] == 0.8

    def test_unadvised_adds_bonus(self):
        raw_advised, _, _ = dimensions.deal_accessibility({"director_retirement_window": 0.8}, False)
        raw_unadvised, _, _ = dimensions.deal_accessibility({"director_retirement_window": 0.8}, True)
        assert raw_unadvised > raw_advised

    def test_capped_at_five(self):
        raw, _, _ = dimensions.deal_accessibility({"director_retirement_window": 1.0}, True)
        assert raw <= 5.0

    def test_none_values_ignored(self):
        raw, evidence, _ = dimensions.deal_accessibility(
            {"director_retirement_window": None, "long_single_owner_tenure": 0.4}, False
        )
        assert raw == pytest.approx(2.0)


class TestMarketConsolidation:
    def test_both_zero(self):
        raw, evidence, _ = dimensions.market_consolidation(0.0, 0.0)
        assert raw == 0.0

    def test_fragmented_weighted_more_than_adjacency(self):
        raw_frag, _, _ = dimensions.market_consolidation(1.0, 0.0)
        raw_adj, _, _ = dimensions.market_consolidation(0.0, 1.0)
        assert raw_frag > raw_adj

    def test_none_inputs_treated_as_zero(self):
        raw, _, _ = dimensions.market_consolidation(None, None)
        assert raw == 0.0

    def test_both_max_capped_at_five(self):
        raw, _, _ = dimensions.market_consolidation(1.0, 1.0)
        assert raw == 5.0


class TestLatentDigitalUpsideWrapper:
    def test_calls_agent_b_formula_with_given_inputs(self, monkeypatch):
        _install_fake_latent_upside(monkeypatch)
        raw, evidence, rationale = dimensions.latent_digital_upside(0.8, 2, 0.5)
        expected = 5 * 0.8 * (1 - (2 - 1) / 4)
        assert raw == pytest.approx(round(expected, 2))
        assert evidence["review_strength"] == 0.8
        assert evidence["digital_maturity"] == 2
        assert evidence["distribution_breadth"] == 0.5

    def test_low_distribution_breadth_bonus_applied(self, monkeypatch):
        _install_fake_latent_upside(monkeypatch)
        raw_low_dist, _, _ = dimensions.latent_digital_upside(0.5, 3, 0.1)
        raw_high_dist, _, _ = dimensions.latent_digital_upside(0.5, 3, 0.9)
        assert raw_low_dist > raw_high_dist

    def test_capped_at_five(self, monkeypatch):
        _install_fake_latent_upside(monkeypatch)
        raw, _, _ = dimensions.latent_digital_upside(1.0, 1, 0.0)
        assert raw <= 5.0

    def test_missing_inputs_use_conservative_defaults(self, monkeypatch):
        _install_fake_latent_upside(monkeypatch)
        raw, evidence, rationale = dimensions.latent_digital_upside(None, None, None)
        assert evidence["review_strength_missing"] is True
        assert evidence["digital_maturity_missing"] is True
        assert evidence["distribution_breadth_missing"] is True
        # defaults: review_strength=0.0 -> raw should be 0 regardless of digital_maturity default
        assert raw == 0.0

    def test_import_is_lazy_module_import_does_not_fail(self):
        # Importing the dimensions module itself must never require Agent
        # B's file to exist yet — only calling the function does.
        import importlib

        importlib.reload(dimensions)
