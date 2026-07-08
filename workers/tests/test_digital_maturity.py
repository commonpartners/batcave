"""Rubric boundary tests for compute_digital_maturity (spec 03 §4)."""
from __future__ import annotations

from cp_workers.enrichment.digital_maturity import compute_digital_maturity


def test_score_1_no_functioning_site():
    webtech = {"site_functional": False}
    assert compute_digital_maturity(webtech, has_ecommerce=False) == 1


def test_score_1_brochure_only_no_tech_detected():
    webtech = {
        "site_functional": True,
        "platform": None,
        "analytics": {},
        "ad_pixels": {},
        "email_capture": False,
        "structured_data": False,
    }
    assert compute_digital_maturity(webtech, has_ecommerce=False) == 1


def test_score_2_static_site_with_some_tech_but_no_ecommerce():
    webtech = {
        "site_functional": True,
        "analytics": {"ga4": True},
        "ad_pixels": {},
        "email_capture": False,
        "structured_data": False,
    }
    assert compute_digital_maturity(webtech, has_ecommerce=False) == 2


def test_score_3_ecommerce_with_at_most_one_of_the_signals():
    webtech = {
        "site_functional": True,
        "platform": "shopify",
        "analytics": {},
        "ad_pixels": {},
        "email_capture": True,
    }
    assert compute_digital_maturity(webtech, has_ecommerce=True) == 3


def test_score_3_ecommerce_with_zero_signals():
    webtech = {"site_functional": True, "platform": "shopify"}
    assert compute_digital_maturity(webtech, has_ecommerce=True) == 3


def test_score_4_ecommerce_email_capture_and_analytics():
    webtech = {
        "site_functional": True,
        "platform": "shopify",
        "analytics": {"ga4": True},
        "ad_pixels": {"meta": True},
        "email_capture": True,
        "active_content_cadence": False,
    }
    assert compute_digital_maturity(webtech, has_ecommerce=True) == 4


def test_score_5_full_stack():
    webtech = {
        "site_functional": True,
        "platform": "shopify",
        "analytics": {"ga4": True, "gtm": True},
        "ad_pixels": {"meta": True, "tiktok": True, "google_ads": True},
        "email_capture": True,
        "active_content_cadence": True,
        "structured_data": True,
    }
    assert compute_digital_maturity(webtech, has_ecommerce=True) == 5


def test_score_4_not_5_without_active_content_cadence():
    webtech = {
        "site_functional": True,
        "platform": "shopify",
        "analytics": {"ga4": True},
        "ad_pixels": {"meta": True, "tiktok": True},
        "email_capture": True,
        "active_content_cadence": False,
    }
    assert compute_digital_maturity(webtech, has_ecommerce=True) == 4


def test_missing_webtech_fields_degrade_gracefully_not_error():
    # An empty dict must never raise -- worst case treated as brochure-only.
    assert compute_digital_maturity({}, has_ecommerce=False) == 1
    assert compute_digital_maturity({}, has_ecommerce=True) == 3
