"""Tests for scoring/red_flags.py — spec 04 §5 six flags.

Red flags must never touch a score value; these tests only assert on flag
lists/evidence, matching the module's contract that flags and scores are
kept strictly separate (spec 04 §5).
"""
from __future__ import annotations

from cp_workers.scoring import red_flags


class TestStructuralDecline:
    def test_flags_when_declining_and_net_assets_shrinking(self):
        flags, evidence = red_flags.detect_rules_red_flags(
            {"review_trend": "declining", "net_assets_shrinking": True}
        )
        assert "structural_decline" in flags
        assert evidence["structural_decline"]["net_assets_shrinking"] is True

    def test_flags_when_declining_and_employee_count_falling(self):
        flags, _ = red_flags.detect_rules_red_flags(
            {"review_trend": "declining", "employee_count_falling": True}
        )
        assert "structural_decline" in flags

    def test_no_flag_when_declining_but_nothing_else_shrinking(self):
        flags, _ = red_flags.detect_rules_red_flags({"review_trend": "declining"})
        assert "structural_decline" not in flags

    def test_no_flag_when_not_declining(self):
        flags, _ = red_flags.detect_rules_red_flags(
            {"review_trend": "improving", "net_assets_shrinking": True}
        )
        assert "structural_decline" not in flags


class TestCustomerChannelConcentration:
    def test_flags_when_dominant_share_above_threshold(self):
        flags, evidence = red_flags.detect_rules_red_flags({"dominant_channel_share": 0.9})
        assert "customer_channel_concentration" in flags

    def test_no_flag_below_threshold(self):
        flags, _ = red_flags.detect_rules_red_flags({"dominant_channel_share": 0.5})
        assert "customer_channel_concentration" not in flags

    def test_no_flag_when_share_unknown_deferred_to_llm(self):
        flags, _ = red_flags.detect_rules_red_flags({})
        assert "customer_channel_concentration" not in flags


class TestRegulatoryExposure:
    def test_flags_on_keyword_hit(self):
        flags, evidence = red_flags.detect_rules_red_flags(
            {"website_text": "Our serum is clinically proven to reverse ageing."}
        )
        assert "regulatory_exposure" in flags
        assert evidence["regulatory_exposure"]["keyword_matched"] == "clinically proven"

    def test_no_flag_without_keyword(self):
        flags, _ = red_flags.detect_rules_red_flags({"website_text": "A lovely natural body balm."})
        assert "regulatory_exposure" not in flags

    def test_no_flag_missing_website_text(self):
        flags, _ = red_flags.detect_rules_red_flags({})
        assert "regulatory_exposure" not in flags

    def test_case_insensitive_match(self):
        flags, _ = red_flags.detect_rules_red_flags({"website_text": "CLINICALLY PROVEN results."})
        assert "regulatory_exposure" in flags


class TestOwnerNotWilling:
    def test_never_inferred_only_manual_flag(self):
        # even with every other automatic signal present, owner_not_willing
        # must stay absent unless the manual field is explicitly set.
        flags, _ = red_flags.detect_rules_red_flags(
            {"review_trend": "declining", "net_assets_shrinking": True, "dominant_channel_share": 0.95}
        )
        assert "owner_not_willing" not in flags

    def test_present_when_manual_flag_set(self):
        flags, evidence = red_flags.detect_rules_red_flags({"owner_not_willing_manual": True})
        assert "owner_not_willing" in flags
        assert evidence["owner_not_willing"]["source"] == "manual"


class TestMergeLlmRedFlags:
    def test_adds_tech_product_dependency(self):
        merged = red_flags.merge_llm_red_flags([], {"tech_product_dependency": True})
        assert "tech_product_dependency" in merged

    def test_adds_total_owner_dependency(self):
        merged = red_flags.merge_llm_red_flags([], {"total_owner_dependency": True})
        assert "total_owner_dependency" in merged

    def test_adds_customer_channel_concentration_if_not_already_present(self):
        merged = red_flags.merge_llm_red_flags([], {"customer_channel_concentration": True})
        assert merged.count("customer_channel_concentration") == 1

    def test_does_not_duplicate_existing_rules_flag(self):
        merged = red_flags.merge_llm_red_flags(
            ["customer_channel_concentration"], {"customer_channel_concentration": True}
        )
        assert merged.count("customer_channel_concentration") == 1

    def test_false_or_missing_llm_flags_add_nothing(self):
        merged = red_flags.merge_llm_red_flags(
            ["structural_decline"],
            {"tech_product_dependency": False, "total_owner_dependency": None},
        )
        assert merged == ["structural_decline"]

    def test_none_llm_flags_dict_is_safe(self):
        merged = red_flags.merge_llm_red_flags(["structural_decline"], None)
        assert merged == ["structural_decline"]

    def test_preserves_rules_flags_untouched(self):
        rules_flags = ["structural_decline", "owner_not_willing"]
        merged = red_flags.merge_llm_red_flags(rules_flags, {})
        assert merged[:2] == rules_flags


def test_all_red_flags_constant_matches_spec():
    assert set(red_flags.ALL_RED_FLAGS) == {
        "tech_product_dependency",
        "structural_decline",
        "customer_channel_concentration",
        "regulatory_exposure",
        "owner_not_willing",
        "total_owner_dependency",
    }
