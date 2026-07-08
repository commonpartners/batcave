"""Tests for scoring/pipeline.py — end-to-end score_company against a fake
in-memory Supabase client (tests/fakes.py) and a scripted fake Anthropic
client. No live network/DB/API calls anywhere in this file.

Covers: full pass-gate scoring run persists scores + score_dimensions +
pipeline_items + lifecycle; the LLM-cache-hit-skips-API-call path (spec 04
§3); gate hold/fail companies never call the LLM at all (spec 04 §1 cost
ordering); unknown company / unknown rubric version raise clearly.
"""
from __future__ import annotations

import json
import sys
import types
import uuid

import pytest

from cp_workers.scoring import pipeline
from tests.fakes import FakeSupabaseClient

VALID_LLM_RESPONSE = {
    "brand_customer_equity": {"score_0_to_5": 4, "rationale_one_line": "Strong reviews.", "evidence": ["4.6 stars, 300 reviews"]},
    "team_continuity": {"score_0_to_5": 3, "rationale_one_line": "Small team evidenced.", "evidence": ["About page lists 5 staff"]},
    "differentiation": {"score_0_to_5": 2, "rationale_one_line": "Generic claims only.", "evidence": ["natural ingredients"]},
    "tech_product_dependency": False,
    "total_owner_dependency": False,
    "customer_channel_concentration": False,
}


class _ContentBlock:
    def __init__(self, text):
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_ContentBlock(text)]


class _CountingMessages:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return _Response(self.text)


class _CountingClient:
    def __init__(self, text: str = None):
        self.messages = _CountingMessages(text or json.dumps(VALID_LLM_RESPONSE))


RUBRIC = {
    "version": "1.0.0",
    "weights": {
        "brand_customer_equity": 25,
        "latent_digital_upside": 20,
        "financial_quality": 20,
        "deal_accessibility": 10,
        "team_continuity": 10,
        "market_consolidation": 10,
        "differentiation": 5,
    },
    "gate_config": {
        "min_company_age_years": 8,
        "shortlist_threshold": 60,
        "watchlist_auto_score_threshold": 70,
        "watchlist_succession_signal_floor": 0.5,
        "situation_succession_signal_floor": 0.3,
        "size_band_thresholds": {"fit_now_ev_max_gbp": 5_000_000, "stretch_ebitda_max_gbp": 10_000_000},
    },
    "prompt_hashes": {},
    "active": True,
}


@pytest.fixture(autouse=True)
def fake_latent_upside(monkeypatch):
    def latent_digital_upside_dimension(review_strength, digital_maturity, distribution_breadth):
        raw = 5 * review_strength * (1 - (digital_maturity - 1) / 4)
        if distribution_breadth < 0.3:
            raw += 0.5
        return min(raw, 5.0)

    fake_module = types.ModuleType("cp_workers.signals.latent_upside")
    fake_module.latent_digital_upside_dimension = latent_digital_upside_dimension
    monkeypatch.setitem(sys.modules, "cp_workers.signals.latent_upside", fake_module)


def _make_client_with_pass_company() -> tuple[FakeSupabaseClient, str, str]:
    client = FakeSupabaseClient()
    client.seed("rubric_versions", [RUBRIC])

    company_id = str(uuid.uuid4())
    company_number = "12345678"
    client.seed(
        "companies",
        [
            {
                "id": company_id,
                "company_number": company_number,
                "legal_name": "Lovely Skincare Ltd",
                "sector_tags": ["skincare-personal-care"],
                "sector_tag_source": "rules",
                "company_status": "active",
                "incorporation_date": "2010-01-01",
                "balance_sheet": {"net_assets": 100_000},
                "employee_count": 25,
                "revenue_estimate": None,
                "ebitda_estimate": {"value_pence": 200_000_000, "confidence": "high"},
                "digital_maturity": 2,
                "website": "https://lovelyskincare.example",
                "summary": "A nice skincare brand",
                "region": "London",
                "lifecycle": "enriched",
            }
        ],
    )

    # Deliberately only ONE active person: team_evidence_present must come
    # out False, so succession_continuity does NOT also qualify as a value
    # angle alongside rollup_buy_and_build/distribution_expansion below --
    # keeping qualifying angles at exactly 2 so these tests exercise the
    # qualitative-dims LLM call in isolation, without also triggering the
    # separate value-angle tie-break call on the same mock client.
    person_a = str(uuid.uuid4())
    client.seed(
        "company_people",
        [
            {"id": str(uuid.uuid4()), "company_id": company_id, "person_id": person_a, "role": "director", "is_active": True},
        ],
    )

    client.seed(
        "signals",
        [
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "family": "succession",
                "name": "director_retirement_window",
                "value": 0.6,
                "evidence": {},
                "computed_at": "2026-06-01T00:00:00+00:00",
            },
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "family": "latent_upside",
                "name": "reviews_strong_digital_weak",
                "value": 0.5,
                "evidence": {"review_strength": 0.8, "review_trend": "improving"},
                "computed_at": "2026-06-01T00:00:00+00:00",
            },
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "family": "latent_upside",
                "name": "narrow_distribution",
                "value": 0.7,
                "evidence": {
                    "notable_stockists_count": 1,
                    "marketplace_presence": False,
                    "distribution_breadth": 0.2,
                },
                "computed_at": "2026-06-01T00:00:00+00:00",
            },
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "family": "consolidation",
                "name": "fragmented_subcategory",
                "value": 0.7,
                "evidence": {},
                "computed_at": "2026-06-01T00:00:00+00:00",
            },
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "family": "consolidation",
                "name": "adjacency",
                "value": 0.0,
                "evidence": {},
                "computed_at": "2026-06-01T00:00:00+00:00",
            },
        ],
    )

    client.seed(
        "source_records",
        [
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "source": "website_crawl",
                "raw": {"home": "Welcome to our lovely natural skincare brand, run by Jane and a team of 5."},
                "fetched_at": "2026-06-01T00:00:00+00:00",
            },
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "source": "trustpilot",
                "raw": {"rating": 4.6, "count": 300},
                "fetched_at": "2026-06-01T00:00:00+00:00",
            },
        ],
    )
    return client, company_id, company_number


class TestScoreCompanyPassPath:
    def test_full_run_persists_score_and_dimensions(self, monkeypatch):
        client, company_id, company_number = _make_client_with_pass_company()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
        llm_client = _CountingClient()

        result = pipeline.score_company(company_number, llm_client=llm_client)

        assert result["gate_result"] == "pass"
        assert result["total_score"] is not None
        assert 0 <= result["total_score"] <= 100
        assert result["used_cache"] is False
        assert llm_client.messages.calls == 1

        scores_rows = client.tables["scores"]
        assert len(scores_rows) == 1
        assert scores_rows[0]["gate_result"] == "pass"

        dim_names = {row["dimension"] for row in client.tables["score_dimensions"]}
        assert dim_names == {
            "financial_quality",
            "deal_accessibility",
            "market_consolidation",
            "latent_digital_upside",
            "brand_customer_equity",
            "team_continuity",
            "differentiation",
        }

    def test_lifecycle_updated_to_scored(self, monkeypatch):
        client, company_id, company_number = _make_client_with_pass_company()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
        pipeline.score_company(company_number, llm_client=_CountingClient())
        company_row = next(r for r in client.tables["companies"] if r["id"] == company_id)
        assert company_row["lifecycle"] == "scored"
        assert company_row["size_band"] == "fit-now"

    def test_pipeline_item_created_for_qualifying_score(self, monkeypatch):
        client, company_id, company_number = _make_client_with_pass_company()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
        result = pipeline.score_company(company_number, llm_client=_CountingClient())

        assert result["total_score"] >= 60  # our fixture data scores comfortably above threshold
        pipeline_items = client.tables.get("pipeline_items", [])
        assert len(pipeline_items) == 1
        assert pipeline_items[0]["company_id"] == company_id
        assert pipeline_items[0]["stage"] == "inbox"

    def test_existing_progressed_pipeline_item_is_not_regressed(self, monkeypatch):
        client, company_id, company_number = _make_client_with_pass_company()
        client.seed(
            "pipeline_items",
            [{"id": str(uuid.uuid4()), "company_id": company_id, "stage": "shortlist"}],
        )
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
        pipeline.score_company(company_number, llm_client=_CountingClient())
        pipeline_items = client.tables["pipeline_items"]
        assert len(pipeline_items) == 1
        assert pipeline_items[0]["stage"] == "shortlist"  # untouched, never regressed to inbox


class TestLlmCacheHitSkipsApiCall:
    def test_second_run_with_unchanged_profile_skips_llm_call(self, monkeypatch):
        client, company_id, company_number = _make_client_with_pass_company()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        llm_client_1 = _CountingClient()
        first = pipeline.score_company(company_number, llm_client=llm_client_1)
        assert llm_client_1.messages.calls == 1
        assert first["used_cache"] is False

        llm_client_2 = _CountingClient()
        second = pipeline.score_company(company_number, llm_client=llm_client_2)
        assert llm_client_2.messages.calls == 0  # cache hit -- never touched the mock at all
        assert second["used_cache"] is True
        assert second["total_score"] == first["total_score"]

        # no duplicate scores row was inserted for the unchanged profile
        assert len(client.tables["scores"]) == 1

    def test_changed_profile_busts_the_cache_and_calls_llm_again(self, monkeypatch):
        client, company_id, company_number = _make_client_with_pass_company()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        pipeline.score_company(company_number, llm_client=_CountingClient())
        assert len(client.tables["scores"]) == 1

        # Mutate employee_count -- changes profile_hash without flipping the
        # gate result (unlike mutating balance_sheet, which would also turn
        # foundations to hold and confound this test with the hold-skips-LLM
        # behaviour tested separately below).
        company_row = next(r for r in client.tables["companies"] if r["id"] == company_id)
        company_row["employee_count"] = 30

        llm_client_2 = _CountingClient()
        pipeline.score_company(company_number, llm_client=llm_client_2)
        assert llm_client_2.messages.calls == 1
        assert len(client.tables["scores"]) == 2


class TestGateHoldOrFailNeverCallsLlm:
    def test_gate_fail_company_never_calls_llm(self, monkeypatch):
        client, company_id, company_number = _make_client_with_pass_company()
        company_row = next(r for r in client.tables["companies"] if r["id"] == company_id)
        company_row["sector_tags"] = ["software"]  # excluded sector -> hard fail
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        llm_client = _CountingClient()
        result = pipeline.score_company(company_number, llm_client=llm_client)

        assert result["gate_result"] == "fail"
        assert result["total_score"] is None
        assert llm_client.messages.calls == 0

    def test_gate_hold_company_never_calls_llm(self, monkeypatch):
        client, company_id, company_number = _make_client_with_pass_company()
        company_row = next(r for r in client.tables["companies"] if r["id"] == company_id)
        company_row["incorporation_date"] = "2024-01-01"  # too young -> foundations hold
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        llm_client = _CountingClient()
        result = pipeline.score_company(company_number, llm_client=llm_client)

        assert result["gate_result"] == "hold"
        assert result["total_score"] is None
        assert llm_client.messages.calls == 0

    def test_rules_dimensions_still_persisted_for_held_company(self, monkeypatch):
        client, company_id, company_number = _make_client_with_pass_company()
        company_row = next(r for r in client.tables["companies"] if r["id"] == company_id)
        company_row["incorporation_date"] = "2024-01-01"
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        pipeline.score_company(company_number, llm_client=_CountingClient())
        dim_names = {row["dimension"] for row in client.tables["score_dimensions"]}
        assert dim_names == {
            "financial_quality",
            "deal_accessibility",
            "market_consolidation",
            "latent_digital_upside",
        }

    def test_no_pipeline_item_for_held_company(self, monkeypatch):
        client, company_id, company_number = _make_client_with_pass_company()
        company_row = next(r for r in client.tables["companies"] if r["id"] == company_id)
        company_row["incorporation_date"] = "2024-01-01"
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        pipeline.score_company(company_number, llm_client=_CountingClient())
        assert client.tables.get("pipeline_items", []) == []


class TestErrorHandling:
    def test_unknown_company_number_raises(self, monkeypatch):
        client, _company_id, _company_number = _make_client_with_pass_company()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
        with pytest.raises(ValueError):
            pipeline.score_company("00000000")

    def test_unknown_rubric_version_raises(self, monkeypatch):
        client, _company_id, company_number = _make_client_with_pass_company()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
        with pytest.raises(ValueError):
            pipeline.score_company(company_number, rubric_version="9.9.9")


class TestScoringIncompleteFlag:
    def test_llm_failure_flags_scoring_incomplete_but_still_persists(self, monkeypatch):
        client, company_id, company_number = _make_client_with_pass_company()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        broken_client = _CountingClient(text="not json")
        result = pipeline.score_company(company_number, llm_client=broken_client)

        assert "scoring-incomplete" in result["red_flags"]
        # total_score still computed from whatever dimensions ARE available (rules only)
        assert result["total_score"] is not None
        llm_dims = {"brand_customer_equity", "team_continuity", "differentiation"}
        persisted_llm_rows = [
            row for row in client.tables["score_dimensions"] if row["dimension"] in llm_dims
        ]
        assert persisted_llm_rows == []
