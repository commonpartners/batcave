"""Tests for scoring/value_angles.py — spec 04 §6, max 2 angles returned."""
from __future__ import annotations

from cp_workers.scoring import value_angles


class TestQualifyingValueAngles:
    def test_digitise_qualifies(self):
        profile = {"latent_digital_upside_raw": 4.5, "digital_maturity": 1}
        assert "digitise" in value_angles.qualifying_value_angles(profile)

    def test_digitise_does_not_qualify_below_threshold(self):
        profile = {"latent_digital_upside_raw": 3.9, "digital_maturity": 1}
        assert "digitise" not in value_angles.qualifying_value_angles(profile)

    def test_digitise_does_not_qualify_high_digital_maturity(self):
        profile = {"latent_digital_upside_raw": 4.5, "digital_maturity": 3}
        assert "digitise" not in value_angles.qualifying_value_angles(profile)

    def test_performance_market_qualifies(self):
        profile = {"review_strength": 0.7, "ad_pixels_present": False, "has_ecommerce": True}
        assert "performance_market" in value_angles.qualifying_value_angles(profile)

    def test_performance_market_needs_all_three_conditions(self):
        profile = {"review_strength": 0.7, "ad_pixels_present": True, "has_ecommerce": True}
        assert "performance_market" not in value_angles.qualifying_value_angles(profile)

    def test_rollup_buy_and_build_qualifies(self):
        profile = {"fragmented_subcategory": 0.6}
        assert "rollup_buy_and_build" in value_angles.qualifying_value_angles(profile)

    def test_rollup_buy_and_build_below_threshold(self):
        profile = {"fragmented_subcategory": 0.59}
        assert "rollup_buy_and_build" not in value_angles.qualifying_value_angles(profile)

    def test_succession_continuity_qualifies(self):
        profile = {"succession_signal_max": 0.5, "team_evidence_present": True}
        assert "succession_continuity" in value_angles.qualifying_value_angles(profile)

    def test_succession_continuity_needs_team_evidence(self):
        profile = {"succession_signal_max": 0.9, "team_evidence_present": False}
        assert "succession_continuity" not in value_angles.qualifying_value_angles(profile)

    def test_distribution_expansion_qualifies(self):
        profile = {"narrow_distribution": 0.6}
        assert "distribution_expansion" in value_angles.qualifying_value_angles(profile)

    def test_no_angles_qualify_on_empty_profile(self):
        assert value_angles.qualifying_value_angles({}) == []

    def test_multiple_angles_can_qualify_simultaneously(self):
        profile = {
            "latent_digital_upside_raw": 5,
            "digital_maturity": 1,
            "fragmented_subcategory": 0.9,
            "narrow_distribution": 0.9,
        }
        qualifying = value_angles.qualifying_value_angles(profile)
        assert set(qualifying) == {"digitise", "rollup_buy_and_build", "distribution_expansion"}


class TestSelectValueAngles:
    def test_returns_all_when_two_or_fewer_qualify(self):
        result = value_angles.select_value_angles(["digitise", "rollup_buy_and_build"], {})
        assert result == ["digitise", "rollup_buy_and_build"]

    def test_returns_single_when_one_qualifies(self):
        assert value_angles.select_value_angles(["digitise"], {}) == ["digitise"]

    def test_returns_empty_when_none_qualify(self):
        assert value_angles.select_value_angles([], {}) == []

    def test_max_two_returned_even_without_tie_break(self):
        qualifying = ["digitise", "performance_market", "rollup_buy_and_build"]
        result = value_angles.select_value_angles(qualifying, {})
        assert len(result) == 2

    def test_llm_tie_break_stub_picks_when_more_than_two_qualify(self):
        qualifying = ["digitise", "performance_market", "rollup_buy_and_build", "distribution_expansion"]

        def stub_tie_break(qualifying_angles, profile):
            return ["performance_market", "distribution_expansion"]

        result = value_angles.select_value_angles(qualifying, {}, llm_tie_break=stub_tie_break)
        assert result == ["performance_market", "distribution_expansion"]

    def test_tie_break_result_filtered_to_qualifying_set(self):
        qualifying = ["digitise", "performance_market", "rollup_buy_and_build"]

        def stub_tie_break(qualifying_angles, profile):
            # LLM hallucinates an angle that wasn't actually qualifying —
            # must be filtered out, never trusted blindly.
            return ["digitise", "succession_continuity"]

        result = value_angles.select_value_angles(qualifying, {}, llm_tie_break=stub_tie_break)
        assert result == ["digitise"]
        assert len(result) <= 2

    def test_falls_back_to_deterministic_ranking_when_tie_break_returns_nothing(self):
        qualifying = ["digitise", "performance_market", "rollup_buy_and_build"]

        def empty_tie_break(qualifying_angles, profile):
            return []

        result = value_angles.select_value_angles(qualifying, {}, llm_tie_break=empty_tie_break)
        assert len(result) == 2
        assert all(a in qualifying for a in result)

    def test_deterministic_ranking_uses_signal_strength(self):
        qualifying = ["performance_market", "rollup_buy_and_build", "distribution_expansion"]
        profile = {
            "review_strength": 0.9,
            "fragmented_subcategory": 0.1,
            "narrow_distribution": 0.05,
        }
        result = value_angles.select_value_angles(qualifying, profile)
        assert result[0] == "performance_market"
        assert len(result) == 2

    def test_dedupes_qualifying_list(self):
        result = value_angles.select_value_angles(["digitise", "digitise"], {})
        assert result == ["digitise"]


def test_llm_tie_break_value_angles_never_raises_without_client(monkeypatch):
    # No client and no API key configured -> must return [] rather than raise.
    # Force this regardless of a real key in a local .env, so this test can
    # never make a live API call.
    import dataclasses

    monkeypatch.setattr(
        value_angles, "settings", dataclasses.replace(value_angles.settings, anthropic_api_key=None)
    )
    result = value_angles.llm_tie_break_value_angles(
        ["digitise", "performance_market", "rollup_buy_and_build"], {}
    )
    assert result == []


def test_llm_tie_break_value_angles_uses_mocked_client():
    class FakeContentBlock:
        text = '{"selected_angles": ["digitise", "rollup_buy_and_build"]}'

    class FakeResponse:
        content = [FakeContentBlock()]

    class FakeMessages:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    result = value_angles.llm_tie_break_value_angles(
        ["digitise", "performance_market", "rollup_buy_and_build"], {}, client=FakeClient()
    )
    assert result == ["digitise", "rollup_buy_and_build"]


def test_llm_tie_break_value_angles_swallows_bad_json():
    class FakeContentBlock:
        text = "not json at all"

    class FakeResponse:
        content = [FakeContentBlock()]

    class FakeMessages:
        def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        messages = FakeMessages()

    result = value_angles.llm_tie_break_value_angles(["digitise", "performance_market"], {}, client=FakeClient())
    assert result == []
