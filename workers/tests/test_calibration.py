"""Tests for scoring/calibration.py — spec 04 §4 monthly drift audit."""
from __future__ import annotations

import json
import uuid

import pytest

from cp_workers.scoring import calibration
from tests.fakes import FakeSupabaseClient


class _ContentBlock:
    def __init__(self, text):
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_ContentBlock(text)]


class _ScriptedClient:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0

        class _Messages:
            def create(_inner_self, **kwargs):
                self.calls += 1
                return _Response(self.text)

        self.messages = _Messages()


def _llm_payload(bce: int, tc: int, diff: int) -> str:
    return json.dumps(
        {
            "brand_customer_equity": {"score_0_to_5": bce, "rationale_one_line": "r", "evidence": ["e"]},
            "team_continuity": {"score_0_to_5": tc, "rationale_one_line": "r", "evidence": ["e"]},
            "differentiation": {"score_0_to_5": diff, "rationale_one_line": "r", "evidence": ["e"]},
            "tech_product_dependency": False,
            "total_owner_dependency": False,
            "customer_channel_concentration": False,
        }
    )


def _client_with_company(company_number: str) -> tuple[FakeSupabaseClient, str]:
    client = FakeSupabaseClient()
    company_id = str(uuid.uuid4())
    client.seed(
        "companies",
        [
            {
                "id": company_id,
                "company_number": company_number,
                "legal_name": "Benchmark Co",
                "sector_tags": ["skincare-personal-care"],
                "sector_tag_source": "rules",
                "company_status": "active",
                "incorporation_date": "2005-01-01",
                "balance_sheet": {"net_assets": 200_000},
                "employee_count": 30,
            }
        ],
    )
    return client, company_id


class TestFirstRunEstablishesBaseline:
    def test_no_prior_baseline_reports_no_drift(self, monkeypatch):
        client, _company_id = _client_with_company("12345678")
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        llm_client = _ScriptedClient(_llm_payload(4, 3, 2))
        report = calibration.run_calibration_audit(["12345678"], llm_client=llm_client)

        assert report["had_prior_baseline"] is False
        assert report["alert"] is False
        assert report["drifted"] == []
        assert report["scored"] == 1

    def test_baseline_persisted_to_jobs_table(self, monkeypatch):
        client, _company_id = _client_with_company("12345678")
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        calibration.run_calibration_audit(["12345678"], llm_client=_ScriptedClient(_llm_payload(4, 3, 2)))

        job_rows = [r for r in client.tables["jobs"] if r["job_name"] == calibration.CALIBRATION_JOB_NAME]
        assert len(job_rows) == 1
        assert job_rows[0]["stats"]["scores"]["12345678"]["brand_customer_equity"] == 4.0


class TestDriftDetection:
    def test_flags_dimension_that_moved_more_than_one_point(self, monkeypatch):
        client, _company_id = _client_with_company("12345678")
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        calibration.run_calibration_audit(["12345678"], llm_client=_ScriptedClient(_llm_payload(4, 3, 2)))
        # second run: brand_customer_equity jumps from 4 -> 1 (delta 3, > 1 point threshold)
        report = calibration.run_calibration_audit(["12345678"], llm_client=_ScriptedClient(_llm_payload(1, 3, 2)))

        assert report["had_prior_baseline"] is True
        assert report["alert"] is True
        dims_flagged = {d["dimension"] for d in report["drifted"]}
        assert "brand_customer_equity" in dims_flagged
        assert "team_continuity" not in dims_flagged
        assert "differentiation" not in dims_flagged

    def test_small_movement_within_one_point_does_not_alert(self, monkeypatch):
        client, _company_id = _client_with_company("12345678")
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        calibration.run_calibration_audit(["12345678"], llm_client=_ScriptedClient(_llm_payload(4, 3, 2)))
        report = calibration.run_calibration_audit(["12345678"], llm_client=_ScriptedClient(_llm_payload(4, 4, 2)))

        # team_continuity moved by exactly 1 -- not > 1, so must not alert
        assert report["alert"] is False
        assert report["drifted"] == []

    def test_baseline_rolls_forward_after_each_run(self, monkeypatch):
        client, _company_id = _client_with_company("12345678")
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        calibration.run_calibration_audit(["12345678"], llm_client=_ScriptedClient(_llm_payload(4, 3, 2)))
        calibration.run_calibration_audit(["12345678"], llm_client=_ScriptedClient(_llm_payload(1, 3, 2)))
        # third run compares against the second run's scores (1,3,2), not the first (4,3,2)
        report = calibration.run_calibration_audit(["12345678"], llm_client=_ScriptedClient(_llm_payload(1, 3, 2)))

        assert report["alert"] is False
        assert report["drifted"] == []


class TestErrorHandling:
    def test_unknown_company_number_collected_as_error_not_raised(self, monkeypatch):
        client, _company_id = _client_with_company("12345678")
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        report = calibration.run_calibration_audit(
            ["99999999"], llm_client=_ScriptedClient(_llm_payload(4, 3, 2))
        )
        assert report["scored"] == 0
        assert len(report["errors"]) == 1
        assert report["errors"][0]["company_number"] == "99999999"

    def test_one_bad_company_does_not_block_the_rest(self, monkeypatch):
        client, _company_id = _client_with_company("12345678")
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        report = calibration.run_calibration_audit(
            ["12345678", "99999999"], llm_client=_ScriptedClient(_llm_payload(4, 3, 2))
        )
        assert report["scored"] == 1
        assert len(report["errors"]) == 1
