"""Reviews (spec 03 §3).

Trustpilot: fetch `uk.trustpilot.com/review/{domain}` and parse the JSON-LD
`aggregateRating` block (server-rendered, stable schema) rather than scraping
the visible DOM — survives their frontend redesigns. Honest UA, one retry, and
if blocked we mark reviews missing and move on rather than hammering.

Google reviews: Places API if a key is configured, else skip entirely — we do
not scrape Google.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from cp_workers.config import settings

_USER_AGENT = "CommonPartnersBot/0.1 (+https://thebothy.club; deal-research enrichment; contact julia@thebothy.club)"
_TIMEOUT_SECONDS = 10.0

_LD_JSON_PATTERN = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _find_aggregate_rating(ld_json_blobs: list[str]) -> dict[str, Any] | None:
    for blob in ld_json_blobs:
        try:
            data = json.loads(blob)
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            rating = candidate.get("aggregateRating")
            if isinstance(rating, dict):
                return rating
    return None


def _parse_trustpilot_html(html: str) -> dict[str, Any] | None:
    blobs = _LD_JSON_PATTERN.findall(html or "")
    rating = _find_aggregate_rating(blobs)
    if not rating:
        return None
    try:
        value = float(rating.get("ratingValue"))
        count = int(rating.get("reviewCount") or rating.get("ratingCount") or 0)
    except (TypeError, ValueError):
        return None
    return {"rating": value, "count": count}


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4), reraise=False)
def _get_trustpilot_page(url: str) -> httpx.Response:
    return httpx.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SECONDS, follow_redirects=True)


def fetch_trustpilot(domain: str) -> dict[str, Any] | None:
    """Fetch and parse the Trustpilot `aggregateRating` JSON-LD block for a domain.

    Returns `{"rating": float, "count": int, "fetched_at": iso str}` or `None`
    if blocked/not found — never scrapes the visible DOM, never hammers on
    failure (one retry via tenacity, then give up quietly).
    """
    if not domain:
        return None
    url = f"https://uk.trustpilot.com/review/{domain}"
    try:
        resp = _get_trustpilot_page(url)
    except Exception:
        return None

    if resp is None or resp.status_code != 200:
        return None

    parsed = _parse_trustpilot_html(resp.text)
    if not parsed:
        return None

    from datetime import datetime, timezone

    return {
        "rating": parsed["rating"],
        "count": parsed["count"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_google_reviews(place_query: str) -> dict[str, Any] | None:
    """Places API lookup if `GOOGLE_PLACES_API_KEY` is configured, else `None`.

    Never scrapes Google directly (spec 03 §3). Any API/network failure also
    degrades to `None` rather than raising.
    """
    if not settings.google_places_api_key or not place_query:
        return None
    try:
        find_resp = httpx.get(
            "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
            params={
                "input": place_query,
                "inputtype": "textquery",
                "fields": "place_id",
                "key": settings.google_places_api_key,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        find_resp.raise_for_status()
        candidates = find_resp.json().get("candidates") or []
        if not candidates:
            return None
        place_id = candidates[0].get("place_id")
        if not place_id:
            return None

        detail_resp = httpx.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={
                "place_id": place_id,
                "fields": "rating,user_ratings_total",
                "key": settings.google_places_api_key,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        detail_resp.raise_for_status()
        result = detail_resp.json().get("result") or {}
        rating = result.get("rating")
        count = result.get("user_ratings_total")
        if rating is None or count is None:
            return None

        from datetime import datetime, timezone

        return {
            "rating": float(rating),
            "count": int(count),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        return None


def review_strength(rating: float | None, count: int | None) -> float:
    """0-1 blend of log-scaled review volume x normalised rating (spec 03 §3).

    Never raises on missing/zero inputs: no rating or no reviews -> 0.0
    strength (absence of proof, not an error).
    """
    if not rating or not count or count <= 0:
        return 0.0
    # Normalise a 0-5 star rating to 0-1, floor negative ratings at 0.
    normalised_rating = max(0.0, min(1.0, rating / 5.0))
    # Log-scale volume: saturate around ~500 reviews (log10(500) ~= 2.7).
    volume_score = min(1.0, math.log10(count + 1) / math.log10(501))
    return max(0.0, min(1.0, normalised_rating * volume_score))


def review_trend(current: dict[str, Any] | None, previous: dict[str, Any] | None) -> str:
    """Compare current vs previous fetch -> `improving` / `flat` / `declining`.

    Feeds the `structural_decline` red flag (spec 04 §5) automatically. Missing
    data on either side degrades to `flat` (no evidence of movement) rather
    than raising or guessing a direction.
    """
    if not current or not previous:
        return "flat"

    cur_rating = current.get("rating")
    prev_rating = previous.get("rating")
    cur_count = current.get("count")
    prev_count = previous.get("count")

    if cur_rating is None or prev_rating is None or cur_count is None or prev_count is None:
        return "flat"

    rating_delta = cur_rating - prev_rating
    # Guard divide-by-zero when there were previously no reviews at all.
    count_growth = (cur_count - prev_count) / prev_count if prev_count > 0 else (1.0 if cur_count > 0 else 0.0)

    # Rating movement dominates (it's the harder signal to fake), volume growth
    # is a secondary confirmation/contradiction.
    if rating_delta <= -0.15 or (rating_delta < 0 and count_growth < 0):
        return "declining"
    if rating_delta >= 0.15 or (rating_delta >= 0 and count_growth > 0.1):
        return "improving"
    return "flat"
