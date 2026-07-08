"""Tests for enrichment/reviews.py. No live HTTP calls -- httpx.get is
monkeypatched everywhere a network call would otherwise happen."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from cp_workers.enrichment import reviews


def _fake_response(status_code: int, text: str = "", json_data: dict | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://example.test")
    if json_data is not None:
        return httpx.Response(status_code, json=json_data, request=request)
    return httpx.Response(status_code, text=text, request=request)


TRUSTPILOT_HTML = """
<html><body>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Organization",
 "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.6", "reviewCount": "312"}}
</script>
</body></html>
"""


class TestFetchTrustpilot:
    def test_parses_aggregate_rating_from_json_ld(self, monkeypatch):
        monkeypatch.setattr(reviews, "_get_trustpilot_page", lambda url: _fake_response(200, text=TRUSTPILOT_HTML))
        result = reviews.fetch_trustpilot("thebrand.co.uk")
        assert result is not None
        assert result["rating"] == pytest.approx(4.6)
        assert result["count"] == 312
        assert "fetched_at" in result

    def test_missing_domain_returns_none_never_errors(self):
        assert reviews.fetch_trustpilot("") is None
        assert reviews.fetch_trustpilot(None) is None  # type: ignore[arg-type]

    def test_blocked_or_non_200_returns_none(self, monkeypatch):
        monkeypatch.setattr(reviews, "_get_trustpilot_page", lambda url: _fake_response(403, text="blocked"))
        assert reviews.fetch_trustpilot("thebrand.co.uk") is None

    def test_network_failure_returns_none_never_raises(self, monkeypatch):
        def _raise(url):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr(reviews, "_get_trustpilot_page", _raise)
        assert reviews.fetch_trustpilot("thebrand.co.uk") is None

    def test_no_ld_json_block_returns_none(self, monkeypatch):
        monkeypatch.setattr(reviews, "_get_trustpilot_page", lambda url: _fake_response(200, text="<html></html>"))
        assert reviews.fetch_trustpilot("thebrand.co.uk") is None


class TestFetchGoogleReviews:
    def test_skips_when_no_api_key_configured(self, monkeypatch):
        monkeypatch.setattr(reviews, "settings", SimpleNamespace(google_places_api_key=None))
        assert reviews.fetch_google_reviews("The Brand, London") is None

    def test_empty_query_returns_none(self, monkeypatch):
        monkeypatch.setattr(reviews, "settings", SimpleNamespace(google_places_api_key="fake-key"))
        assert reviews.fetch_google_reviews("") is None

    def test_api_failure_returns_none_never_raises(self, monkeypatch):
        monkeypatch.setattr(reviews, "settings", SimpleNamespace(google_places_api_key="fake-key"))

        def _raise(*args, **kwargs):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr(httpx, "get", _raise)
        assert reviews.fetch_google_reviews("The Brand, London") is None


class TestReviewStrength:
    def test_zero_for_missing_rating_or_count(self):
        assert reviews.review_strength(None, 100) == 0.0
        assert reviews.review_strength(4.5, None) == 0.0
        assert reviews.review_strength(4.5, 0) == 0.0

    def test_higher_rating_scores_higher_at_same_volume(self):
        low = reviews.review_strength(3.0, 200)
        high = reviews.review_strength(4.9, 200)
        assert high > low

    def test_higher_volume_scores_higher_at_same_rating(self):
        low_volume = reviews.review_strength(4.5, 10)
        high_volume = reviews.review_strength(4.5, 1000)
        assert high_volume > low_volume

    def test_bounded_0_to_1(self):
        assert 0.0 <= reviews.review_strength(5.0, 1_000_000) <= 1.0
        assert 0.0 <= reviews.review_strength(4.3, 100) <= 1.0


class TestReviewTrend:
    def test_missing_previous_defaults_to_flat(self):
        current = {"rating": 4.5, "count": 100}
        assert reviews.review_trend(current, None) == "flat"

    def test_missing_current_defaults_to_flat(self):
        previous = {"rating": 4.5, "count": 100}
        assert reviews.review_trend(None, previous) == "flat"

    def test_improving_when_rating_rises(self):
        current = {"rating": 4.8, "count": 120}
        previous = {"rating": 4.4, "count": 100}
        assert reviews.review_trend(current, previous) == "improving"

    def test_declining_when_rating_falls(self):
        current = {"rating": 3.9, "count": 90}
        previous = {"rating": 4.5, "count": 100}
        assert reviews.review_trend(current, previous) == "declining"

    def test_flat_when_no_meaningful_movement(self):
        current = {"rating": 4.5, "count": 101}
        previous = {"rating": 4.48, "count": 100}
        assert reviews.review_trend(current, previous) == "flat"

    def test_zero_previous_count_never_divides_by_zero(self):
        current = {"rating": 4.5, "count": 5}
        previous = {"rating": 0.0, "count": 0}
        # Must not raise ZeroDivisionError.
        result = reviews.review_trend(current, previous)
        assert result in ("improving", "flat", "declining")
