"""Deterministic web-tech detection (spec 03 §2). No LLM calls.

Given raw HTML + response headers for a page (typically the homepage from
`enrichment.website.crawl_website`), fingerprint platform, analytics, ad
pixels, email capture, live chat, and structured data. Output shape matches
spec 03 §2: `{feature: bool/name}`, summarised onto the company profile and
also stored verbatim in a `source_records` row by the caller.
"""
from __future__ import annotations

import re
from typing import Any

# (platform_name, [fingerprint substrings to look for in html/headers])
_PLATFORM_FINGERPRINTS: list[tuple[str, list[str]]] = [
    ("shopify", ["cdn.shopify.com", "shopify.com/s/files", "Shopify.theme"]),
    ("woocommerce", ["woocommerce", "wp-content/plugins/woocommerce"]),
    ("wix", ["static.wixstatic.com", "wix.com"]),
    ("squarespace", ["static1.squarespace.com", "squarespace.com"]),
    ("bigcommerce", ["cdn11.bigcommerce.com", "bigcommerce.com"]),
    ("wordpress", ["wp-content", "wp-includes"]),
]

_ANALYTICS_FINGERPRINTS: dict[str, list[str]] = {
    "ga4": ["gtag('config'", "googletagmanager.com/gtag/js", "G-", "www.google-analytics.com/g/collect"],
    "gtm": ["googletagmanager.com/gtm.js", "GTM-"],
    "universal_analytics": ["www.google-analytics.com/analytics.js", "UA-"],
}

_AD_PIXEL_FINGERPRINTS: dict[str, list[str]] = {
    "meta": ["connect.facebook.net", "fbq(", "facebook pixel"],
    "tiktok": ["analytics.tiktok.com", "ttq.load"],
    "google_ads": ["googleadservices.com", "AW-"],
    "pinterest": ["s.pinimg.com/ct/core.js", "pintrk("],
}

_EMAIL_CAPTURE_FINGERPRINTS: dict[str, list[str]] = {
    "klaviyo": ["klaviyo.com", "_learnq", "klaviyo-form"],
    "mailchimp": ["list-manage.com", "mc-embedded-subscribe"],
    "newsletter_form": ["newsletter", "subscribe", 'type="email"'],
}

_LIVE_CHAT_FINGERPRINTS: list[str] = [
    "widget.intercom.io",
    "static.zdassets.com",  # Zendesk chat
    "embed.tawk.to",
    "widget.freshworks.com",
    "gorgias.chat",
]

_STRUCTURED_DATA_PATTERN = re.compile(r'<script[^>]+type=["\']application/ld\+json["\']', re.IGNORECASE)


def _any_present(haystack: str, needles: list[str]) -> bool:
    lowered = haystack.lower()
    return any(needle.lower() in lowered for needle in needles)


def detect_webtech(html: str | None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Fingerprint web-tech from raw HTML + response headers. Deterministic, no LLM.

    Never raises: missing/empty html degrades to an all-false/None result
    (e.g. a site that failed to crawl) rather than an error, so callers in
    `enrichment.orchestrate` can always trust the return shape.
    """
    html = html or ""
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    server_header = headers.get("server", "") + " " + headers.get("x-powered-by", "")
    combined = html + " " + server_header

    platform = None
    for name, fingerprints in _PLATFORM_FINGERPRINTS:
        if _any_present(combined, fingerprints):
            platform = name
            break

    analytics = {name: _any_present(html, fps) for name, fps in _ANALYTICS_FINGERPRINTS.items()}
    ad_pixels = {name: _any_present(html, fps) for name, fps in _AD_PIXEL_FINGERPRINTS.items()}
    email_capture_detail = {name: _any_present(html, fps) for name, fps in _EMAIL_CAPTURE_FINGERPRINTS.items()}

    return {
        "site_functional": bool(html.strip()),
        "platform": platform,
        "analytics": analytics,
        "ad_pixels": ad_pixels,
        "email_capture": any(email_capture_detail.values()),
        "email_capture_detail": email_capture_detail,
        "live_chat": _any_present(html, _LIVE_CHAT_FINGERPRINTS),
        "structured_data": bool(_STRUCTURED_DATA_PATTERN.search(html)),
    }
