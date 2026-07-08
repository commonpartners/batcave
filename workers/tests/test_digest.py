"""Tests for scoring/digest.py — spec 02 §6 weekly digest build + send."""
from __future__ import annotations

import dataclasses
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from cp_workers.scoring import digest
from tests.fakes import FakeSupabaseClient


def _with_settings(module, **overrides):
    """Settings is a frozen dataclass, so tests can't mutate the singleton
    in place -- swap the module's ``settings`` reference for a replacement
    instance instead (this also guarantees a real ANTHROPIC/RESEND key
    picked up from a local .env never leaks into a test as a live call)."""
    return dataclasses.replace(module.settings, **overrides)

RUBRIC = {
    "version": "1.0.0",
    "weights": {},
    "gate_config": {"shortlist_threshold": 60},
    "prompt_hashes": {},
    "active": True,
}

NOW = datetime.now(timezone.utc)
RECENT = (NOW - timedelta(days=1)).isoformat()
OLD = (NOW - timedelta(days=30)).isoformat()


def _client_with_digest_data() -> FakeSupabaseClient:
    client = FakeSupabaseClient()
    client.seed("rubric_versions", [RUBRIC])

    qualifier_id = str(uuid.uuid4())
    held_id = str(uuid.uuid4())
    fired_id = str(uuid.uuid4())
    stale_id = str(uuid.uuid4())

    client.seed(
        "companies",
        [
            {"id": qualifier_id, "company_number": "11111111", "legal_name": "Qualifier Co"},
            {"id": held_id, "company_number": "22222222", "legal_name": "Held Co"},
            {"id": fired_id, "company_number": "33333333", "legal_name": "Fired Co"},
            {"id": stale_id, "company_number": "44444444", "legal_name": "Stale Co"},
        ],
    )
    client.seed(
        "scores",
        [
            {
                "id": str(uuid.uuid4()),
                "company_id": qualifier_id,
                "gate_result": "pass",
                "total_score": 82,
                "value_angles": ["digitise"],
                "scored_at": RECENT,
            },
            {
                "id": str(uuid.uuid4()),
                "company_id": held_id,
                "gate_result": "hold",
                "total_score": None,
                "gate_detail": {"size": {"result": "hold", "reason": "size_band=unknown"}},
                "scored_at": RECENT,
            },
            {
                "id": str(uuid.uuid4()),
                "company_id": stale_id,
                "gate_result": "pass",
                "total_score": 95,
                "value_angles": [],
                "scored_at": OLD,  # outside the lookback window
            },
        ],
    )
    client.seed(
        "watchlist_items",
        [
            {
                "id": str(uuid.uuid4()),
                "company_id": fired_id,
                "status": "fired",
                "reason": "succession signal crossed 0.5",
                "updated_at": RECENT,
            }
        ],
    )
    client.seed(
        "jobs",
        [
            {
                "id": str(uuid.uuid4()),
                "job_name": "score",
                "run_key": "2026-W28",
                "status": "succeeded",
                "started_at": RECENT,
                "stats": {},
            },
            {
                "id": str(uuid.uuid4()),
                "job_name": "refresh",
                "run_key": "2026-W28",
                "status": "failed",
                "started_at": RECENT,
                "stats": {"failures": [{"company": "55555555", "error": "timeout"}]},
                "error": "run aborted",
            },
        ],
    )
    return client


class TestBuildDigest:
    def test_includes_new_qualifiers_above_threshold(self, monkeypatch):
        client = _client_with_digest_data()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        content = digest.build_digest(since=NOW - timedelta(days=7))

        names = {q["name"] for q in content["new_qualifiers"]}
        assert "Qualifier Co" in names
        assert "Stale Co" not in names  # outside the lookback window

    def test_qualifier_includes_score_angle_and_link(self, monkeypatch):
        client = _client_with_digest_data()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
        content = digest.build_digest(since=NOW - timedelta(days=7))
        qualifier = next(q for q in content["new_qualifiers"] if q["name"] == "Qualifier Co")
        assert qualifier["score"] == 82
        assert qualifier["angle"] == "digitise"
        assert qualifier["link"] == "/companies/11111111"

    def test_includes_watchlist_fires(self, monkeypatch):
        client = _client_with_digest_data()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
        content = digest.build_digest(since=NOW - timedelta(days=7))
        names = {f["name"] for f in content["watchlist_fires"]}
        assert "Fired Co" in names

    def test_includes_newly_held_with_failing_test(self, monkeypatch):
        client = _client_with_digest_data()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
        content = digest.build_digest(since=NOW - timedelta(days=7))
        held = next(h for h in content["newly_held"] if h["name"] == "Held Co")
        assert "size" in held["failing_tests"]

    def test_run_health_reports_job_counts_and_failures(self, monkeypatch):
        client = _client_with_digest_data()
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
        content = digest.build_digest(since=NOW - timedelta(days=7))
        jobs_by_name = {j["job_name"]: j for j in content["run_health"]["jobs"]}
        assert jobs_by_name["score"]["succeeded"] == 1
        assert jobs_by_name["refresh"]["failed"] == 1
        assert len(jobs_by_name["refresh"]["failures"]) >= 1

    def test_empty_database_never_raises(self, monkeypatch):
        client = FakeSupabaseClient()
        client.seed("rubric_versions", [RUBRIC])
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
        content = digest.build_digest()
        assert content["new_qualifiers"] == []
        assert content["watchlist_fires"] == []
        assert content["newly_held"] == []


class TestSendDigest:
    def test_no_api_key_skips_without_raising(self, monkeypatch):
        monkeypatch.setattr(digest, "settings", _with_settings(digest, resend_api_key="", digest_to="julia@thebothy.club"))
        result = digest.send_digest({"generated_at": "2026-07-08", "new_qualifiers": [], "watchlist_fires": [], "newly_held": [], "run_health": {"jobs": []}})
        assert result["sent"] is False
        assert "RESEND_API_KEY" in result["reason"]

    def test_no_recipients_skips_without_raising(self, monkeypatch):
        monkeypatch.setattr(digest, "settings", _with_settings(digest, resend_api_key="fake-key", digest_to=""))
        result = digest.send_digest({"generated_at": "2026-07-08", "new_qualifiers": [], "watchlist_fires": [], "newly_held": [], "run_health": {"jobs": []}})
        assert result["sent"] is False
        assert "recipients" in result["reason"]

    def test_sends_via_resend_when_configured(self, monkeypatch):
        monkeypatch.setattr(
            digest,
            "settings",
            _with_settings(digest, resend_api_key="fake-key", digest_to="julia@thebothy.club,ben@example.com"),
        )

        sent_payloads = []
        fake_resend = types.ModuleType("resend")
        fake_resend.api_key = None

        class FakeEmails:
            @staticmethod
            def send(payload):
                sent_payloads.append(payload)
                return {"id": "fake-email-id"}

        fake_resend.Emails = FakeEmails
        monkeypatch.setitem(sys.modules, "resend", fake_resend)

        result = digest.send_digest(
            {"generated_at": "2026-07-08", "new_qualifiers": [], "watchlist_fires": [], "newly_held": [], "run_health": {"jobs": []}}
        )

        assert result["sent"] is True
        assert len(sent_payloads) == 1
        assert sent_payloads[0]["to"] == ["julia@thebothy.club", "ben@example.com"]

    def test_send_failure_never_raises(self, monkeypatch):
        monkeypatch.setattr(
            digest, "settings", _with_settings(digest, resend_api_key="fake-key", digest_to="julia@thebothy.club")
        )

        fake_resend = types.ModuleType("resend")

        class FailingEmails:
            @staticmethod
            def send(payload):
                raise RuntimeError("resend API down")

        fake_resend.Emails = FailingEmails
        monkeypatch.setitem(sys.modules, "resend", fake_resend)

        result = digest.send_digest(
            {"generated_at": "2026-07-08", "new_qualifiers": [], "watchlist_fires": [], "newly_held": [], "run_health": {"jobs": []}}
        )
        assert result["sent"] is False
        assert "resend send failed" in result["reason"]
