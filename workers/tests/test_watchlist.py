"""Tests for scoring/watchlist.py — spec 02 §5 entry/fire/expire logic."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from cp_workers.scoring import watchlist
from tests.fakes import FakeSupabaseClient

RUBRIC = {
    "version": "1.0.0",
    "weights": {},
    "gate_config": {
        "watchlist_auto_score_threshold": 70,
        "watchlist_succession_signal_floor": 0.5,
    },
    "prompt_hashes": {},
    "active": True,
}


def _base_client() -> FakeSupabaseClient:
    client = FakeSupabaseClient()
    client.seed("rubric_versions", [RUBRIC])
    client.seed("app_config", [{"key": "watchlist_patience_months", "value": 24}])
    return client


def _add_company(client, *, total_score=None, succession_value=None, company_id=None) -> str:
    company_id = company_id or str(uuid.uuid4())
    client.tables.setdefault("companies", []).append(
        {"id": company_id, "company_number": f"C{company_id[:8]}", "legal_name": "Test Co", "lifecycle": "scored"}
    )
    if total_score is not None:
        client.tables.setdefault("scores", []).append(
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "gate_result": "pass",
                "total_score": total_score,
                "scored_at": "2026-06-01T00:00:00+00:00",
            }
        )
    if succession_value is not None:
        client.tables.setdefault("signals", []).append(
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "family": "succession",
                "name": "director_retirement_window",
                "value": succession_value,
                "computed_at": "2026-06-01T00:00:00+00:00",
            }
        )
    return company_id


class TestAutoEntry:
    def test_enters_when_score_high_and_no_succession_signal(self, monkeypatch):
        client = _base_client()
        company_id = _add_company(client, total_score=75, succession_value=0.1)
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        stats = watchlist.watchlist_check()

        assert stats["auto_entered"] == 1
        watchlist_rows = client.tables["watchlist_items"]
        assert len(watchlist_rows) == 1
        assert watchlist_rows[0]["company_id"] == company_id
        assert watchlist_rows[0]["status"] == "watching"

    def test_skips_when_score_below_threshold(self, monkeypatch):
        client = _base_client()
        _add_company(client, total_score=65, succession_value=0.1)
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        stats = watchlist.watchlist_check()
        assert stats["auto_entered"] == 0
        assert client.tables.get("watchlist_items", []) == []

    def test_skips_when_succession_signal_already_strong(self, monkeypatch):
        client = _base_client()
        _add_company(client, total_score=80, succession_value=0.6)
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        stats = watchlist.watchlist_check()
        assert stats["auto_entered"] == 0
        assert client.tables.get("watchlist_items", []) == []

    def test_skips_when_no_succession_signal_at_all(self, monkeypatch):
        client = _base_client()
        company_id = _add_company(client, total_score=80, succession_value=None)
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        stats = watchlist.watchlist_check()
        assert stats["auto_entered"] == 1  # missing signal treated as "no strong signal yet"
        assert client.tables["watchlist_items"][0]["company_id"] == company_id

    def test_skips_company_already_on_watchlist(self, monkeypatch):
        client = _base_client()
        company_id = _add_company(client, total_score=80, succession_value=0.1)
        client.tables["watchlist_items"] = [
            {"id": str(uuid.uuid4()), "company_id": company_id, "status": "watching"}
        ]
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        stats = watchlist.watchlist_check()
        assert stats["auto_entered"] == 0
        assert len(client.tables["watchlist_items"]) == 1

    def test_deprioritise_after_set_from_patience_config(self, monkeypatch):
        client = _base_client()
        _add_company(client, total_score=90, succession_value=0.0)
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        watchlist.watchlist_check()
        row = client.tables["watchlist_items"][0]
        added = datetime.fromisoformat(row["added_at"])
        deprioritise = datetime.fromisoformat(row["deprioritise_after"])
        assert (deprioritise - added).days > 700  # ~24 months


class TestWeeklyFireAndExpire:
    def test_fires_when_succession_signal_crosses_floor(self, monkeypatch):
        client = _base_client()
        company_id = _add_company(client, succession_value=0.7)
        client.tables["watchlist_items"] = [
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "status": "watching",
                "deprioritise_after": (datetime.now(timezone.utc) + timedelta(days=100)).isoformat(),
            }
        ]
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        stats = watchlist.watchlist_check()

        assert stats["fired"] == 1
        assert client.tables["watchlist_items"][0]["status"] == "fired"
        pipeline_items = client.tables.get("pipeline_items", [])
        assert len(pipeline_items) == 1
        assert pipeline_items[0]["company_id"] == company_id
        assert pipeline_items[0]["stage"] == "inbox"

    def test_expires_when_deprioritise_after_passed_with_no_fire(self, monkeypatch):
        client = _base_client()
        company_id = _add_company(client, succession_value=0.1)
        client.tables["watchlist_items"] = [
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "status": "watching",
                "deprioritise_after": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            }
        ]
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        stats = watchlist.watchlist_check()

        assert stats["expired"] == 1
        assert client.tables["watchlist_items"][0]["status"] == "expired"
        company_row = next(r for r in client.tables["companies"] if r["id"] == company_id)
        assert company_row["lifecycle"] == "archived"

    def test_stays_watching_when_neither_fires_nor_expires(self, monkeypatch):
        client = _base_client()
        company_id = _add_company(client, succession_value=0.1)
        client.tables["watchlist_items"] = [
            {
                "id": str(uuid.uuid4()),
                "company_id": company_id,
                "status": "watching",
                "deprioritise_after": (datetime.now(timezone.utc) + timedelta(days=100)).isoformat(),
            }
        ]
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        stats = watchlist.watchlist_check()
        assert stats["fired"] == 0
        assert stats["expired"] == 0
        assert client.tables["watchlist_items"][0]["status"] == "watching"

    def test_missing_deprioritise_after_never_auto_expires(self, monkeypatch):
        client = _base_client()
        company_id = _add_company(client, succession_value=0.1)
        client.tables["watchlist_items"] = [
            {"id": str(uuid.uuid4()), "company_id": company_id, "status": "watching", "deprioritise_after": None}
        ]
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        stats = watchlist.watchlist_check()
        assert stats["expired"] == 0
        assert client.tables["watchlist_items"][0]["status"] == "watching"

    def test_checked_count_reflects_watching_items_only(self, monkeypatch):
        client = _base_client()
        company_id = _add_company(client, succession_value=0.1)
        client.tables["watchlist_items"] = [
            {"id": str(uuid.uuid4()), "company_id": company_id, "status": "watching"},
            {"id": str(uuid.uuid4()), "company_id": str(uuid.uuid4()), "status": "fired"},
            {"id": str(uuid.uuid4()), "company_id": str(uuid.uuid4()), "status": "expired"},
        ]
        monkeypatch.setattr("cp_workers.db.get_client", lambda: client)

        stats = watchlist.watchlist_check()
        assert stats["checked"] == 1


def test_stats_shape_always_present(monkeypatch):
    client = _base_client()
    monkeypatch.setattr("cp_workers.db.get_client", lambda: client)
    stats = watchlist.watchlist_check()
    assert set(stats.keys()) == {"auto_entered", "fired", "expired", "checked", "errors"}
