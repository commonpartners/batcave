"""Social presence — best-effort, brittle by nature (spec 03 §5).

From website footer links (see `enrichment.website.extract_profile`), capture
Instagram/Facebook/TikTok handles and fetch public follower counts / last-post
date where accessible without login. This module never raises: missing or
unreachable social data lowers confidence, never correctness, and we do not
build login-based scraping.
"""
from __future__ import annotations

from typing import Any

import httpx

# Deliberately tiny per-platform timeout: social lookups are best-effort and
# must never become the slow/blocking step of an enrichment run.
_TIMEOUT_SECONDS = 8.0
_USER_AGENT = "CommonPartnersBot/0.1 (+https://thebothy.club; enrichment research)"

SUPPORTED_PLATFORMS = ("instagram", "facebook", "tiktok")


def _fetch_platform(platform: str, handle: str) -> dict[str, Any]:
    """Best-effort single-platform lookup. Isolated so a single platform's
    failure (blocked, rate-limited, login-walled) can't affect the others."""
    result: dict[str, Any] = {"handle": handle, "found": False, "confidence": "low"}
    try:
        # Public profile pages only; no authenticated/login-based access.
        url = {
            "instagram": f"https://www.instagram.com/{handle}/",
            "facebook": f"https://www.facebook.com/{handle}/",
            "tiktok": f"https://www.tiktok.com/@{handle}",
        }.get(platform)
        if not url:
            return result
        resp = httpx.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return result
        result["found"] = True
        result["confidence"] = "med"
        # Follower counts / last-post date require parsing platform-specific
        # embedded JSON that changes frequently and is often login-gated; we
        # deliberately don't attempt that scrape here (spec 03 §5 "do not
        # build login-based scraping"). Presence-only is still useful signal.
    except Exception as exc:  # noqa: BLE001 - best-effort, must never raise
        result["error"] = str(exc)
    return result


def fetch_social(handles: dict[str, str]) -> dict[str, Any]:
    """Best-effort social presence lookup. Never raises.

    `handles` maps platform name -> handle/username (e.g.
    `{"instagram": "thebrand", "tiktok": "thebrand"}`), typically sourced from
    website footer links. Unknown platforms are ignored; per-platform failures
    are captured in that platform's result rather than propagated.
    """
    out: dict[str, Any] = {}
    if not handles:
        return out
    for platform, handle in handles.items():
        if platform not in SUPPORTED_PLATFORMS or not handle:
            continue
        try:
            out[platform] = _fetch_platform(platform, handle)
        except Exception as exc:  # noqa: BLE001 - absolute last-resort guard
            out[platform] = {"handle": handle, "found": False, "confidence": "low", "error": str(exc)}
    return out
