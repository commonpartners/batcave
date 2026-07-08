"""Tests for enrichment/webtech.py -- deterministic, no network, no LLM."""
from __future__ import annotations

from cp_workers.enrichment.webtech import detect_webtech


def test_detects_shopify_platform():
    html = '<html><head><link href="https://cdn.shopify.com/s/files/theme.css"></head></html>'
    result = detect_webtech(html, headers={})
    assert result["platform"] == "shopify"


def test_detects_woocommerce_platform():
    html = '<html><body class="woocommerce"><script src="/wp-content/plugins/woocommerce/x.js"></script></body></html>'
    result = detect_webtech(html, headers={})
    assert result["platform"] == "woocommerce"


def test_detects_ga4_and_gtm_analytics():
    html = '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-ABC123"></script>'
    result = detect_webtech(html, headers={})
    assert result["analytics"]["gtm"] is True


def test_detects_meta_pixel():
    html = '<script src="https://connect.facebook.net/en_US/fbevents.js"></script><script>fbq("init");</script>'
    result = detect_webtech(html, headers={})
    assert result["ad_pixels"]["meta"] is True


def test_detects_klaviyo_email_capture():
    html = '<script src="https://static.klaviyo.com/onsite/js/klaviyo.js"></script>'
    result = detect_webtech(html, headers={})
    assert result["email_capture"] is True
    assert result["email_capture_detail"]["klaviyo"] is True


def test_detects_live_chat_widget():
    html = '<script src="https://widget.intercom.io/widget/abc123"></script>'
    result = detect_webtech(html, headers={})
    assert result["live_chat"] is True


def test_detects_structured_data():
    html = '<script type="application/ld+json">{"@type": "Organization"}</script>'
    result = detect_webtech(html, headers={})
    assert result["structured_data"] is True


def test_no_signals_all_false():
    result = detect_webtech("<html><body>Just a plain page.</body></html>", headers={})
    assert result["platform"] is None
    assert result["email_capture"] is False
    assert result["live_chat"] is False
    assert result["structured_data"] is False
    assert not any(result["analytics"].values())
    assert not any(result["ad_pixels"].values())


def test_empty_html_degrades_gracefully_never_errors():
    result = detect_webtech(None, None)
    assert result["site_functional"] is False
    assert result["platform"] is None

    result2 = detect_webtech("", {})
    assert result2["site_functional"] is False
