"""Digital maturity rubric (spec 03 §4) — deterministic, pure function.

    | Score | Criteria                                                              |
    |-------|------------------------------------------------------------------------|
    | 1     | No functioning site, or brochure page only                             |
    | 2     | Static site; no e-commerce, no email capture, no pixels                |
    | 3     | E-commerce present but <= 1 of {email capture, analytics, any pixel}   |
    | 4     | E-commerce + email capture + analytics; some paid/social activity      |
    | 5     | Full stack: modern platform, CRM/email flows, multiple pixels, active  |
    |       | content cadence                                                        |

This is the denominator of the latent-upside edge (spec 04 §3) — keep it
deterministic and auditable. No LLM calls, no network access: it only reads
the already-detected `webtech` dict (see `enrichment/webtech.py`).
"""
from __future__ import annotations

from typing import Any


def _has_any_ad_pixel(webtech: dict[str, Any]) -> bool:
    pixels = webtech.get("ad_pixels") or {}
    if isinstance(pixels, dict):
        return any(bool(v) for v in pixels.values())
    return bool(pixels)


def _bool(webtech: dict[str, Any], key: str) -> bool:
    """Truthiness of a webtech field, tolerant of the dict-of-bools shape used
    by `detect_webtech` for e.g. "analytics" (per-tool booleans rather than a
    single flag) as well as plain bool fields like "email_capture"."""
    value = webtech.get(key)
    if isinstance(value, dict):
        return any(bool(v) for v in value.values())
    return bool(value)


def compute_digital_maturity(webtech: dict[str, Any], has_ecommerce: bool) -> int:
    """Map detected web-tech signals to the 1-5 digital maturity rubric.

    `webtech` is the dict produced by `enrichment.webtech.detect_webtech`, expected
    (all optional, missing == falsy) to carry:
      - "site_functional": bool  (False/absent -> brochure-only or no site)
      - "platform": str | None   (a recognised modern platform, e.g. shopify/woo)
      - "analytics": dict[str, bool] | bool
      - "ad_pixels": dict[str, bool] | bool
      - "email_capture": bool
      - "live_chat": bool
      - "structured_data": bool
      - "active_content_cadence": bool  (recent blog/press/social activity)
    """
    site_functional = webtech.get("site_functional", True)
    has_analytics = _bool(webtech, "analytics")
    has_pixel = _has_any_ad_pixel(webtech)
    has_email_capture = _bool(webtech, "email_capture")
    has_structured_data = _bool(webtech, "structured_data")

    if not site_functional:
        return 1

    if not has_ecommerce:
        # No e-commerce: table caps these at 1-2. A pure brochure page with zero
        # detected tech of any kind is score 1 ("brochure page only"); a static
        # site that at least has *some* tech footprint (analytics tag, a pixel,
        # structured data) but still no e-commerce/capture is score 2.
        has_any_tech = any([has_analytics, has_pixel, has_email_capture, has_structured_data])
        return 2 if has_any_tech else 1

    # E-commerce present from here on -> score 3, 4, or 5.
    signals_present = sum([has_email_capture, has_analytics, has_pixel])
    modern_platform = bool(webtech.get("platform"))
    active_cadence = _bool(webtech, "active_content_cadence")
    multiple_pixels = isinstance(webtech.get("ad_pixels"), dict) and (
        sum(1 for v in webtech["ad_pixels"].values() if v) >= 2
    )

    if signals_present <= 1:
        return 3

    if has_email_capture and has_analytics and modern_platform and active_cadence and multiple_pixels:
        return 5

    if has_email_capture and has_analytics:
        return 4

    return 3
