"""Tests for enrichment/social.py -- best-effort, must never raise."""
from __future__ import annotations

from types import SimpleNamespace

import httpx

from cp_workers.enrichment import social


def _fake_resp(status_code: int) -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code)


def test_empty_handles_returns_empty_dict():
    assert social.fetch_social({}) == {}
    assert social.fetch_social(None) == {}  # type: ignore[arg-type]


def test_unsupported_platform_is_ignored():
    result = social.fetch_social({"twitter": "thebrand"})
    assert result == {}


def test_found_profile_marks_found_true(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_resp(200))
    result = social.fetch_social({"instagram": "thebrand"})
    assert result["instagram"]["found"] is True
    assert result["instagram"]["handle"] == "thebrand"


def test_404_marks_found_false_no_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _fake_resp(404))
    result = social.fetch_social({"instagram": "doesnotexist"})
    assert result["instagram"]["found"] is False


def test_network_failure_degrades_gracefully_never_raises(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "get", _raise)
    result = social.fetch_social({"instagram": "thebrand", "tiktok": "thebrand"})
    assert result["instagram"]["found"] is False
    assert result["instagram"]["confidence"] == "low"
    assert result["tiktok"]["found"] is False


def test_one_platform_failure_does_not_affect_others(monkeypatch):
    def flaky_get(url, **kwargs):
        if "instagram" in url:
            raise httpx.ConnectError("boom")
        return _fake_resp(200)

    monkeypatch.setattr(httpx, "get", flaky_get)
    result = social.fetch_social({"instagram": "thebrand", "facebook": "thebrand"})
    assert result["instagram"]["found"] is False
    assert result["facebook"]["found"] is True
