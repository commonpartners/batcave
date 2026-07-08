"""Tests for enrichment/website.py. All network access (_http_get, _search_web,
_render_with_playwright, _call_llm) is monkeypatched -- no live HTTP calls."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from cp_workers.enrichment import website


def _fake_resp(status_code: int, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, text=text, headers={})


FOOTER_WITH_MATCHING_NUMBER = "<html><body><footer>Acme Botanicals Ltd, registered in England, company no. 01234567</footer></body></html>"
FOOTER_WITH_OTHER_NUMBER = "<html><body><footer>Some Co Ltd, company number 09999999</footer></body></html>"
FOOTER_NO_NUMBER = "<html><body><footer>Acme Botanicals Ltd</footer></body></html>"


class TestResolveWebsite:
    def test_footer_company_number_match_crosses_threshold(self, monkeypatch):
        monkeypatch.setattr(website, "_search_web", lambda query: ["https://acmebotanicals.co.uk"])
        monkeypatch.setattr(website, "_http_get", lambda url: _fake_resp(200, FOOTER_WITH_MATCHING_NUMBER))

        url, confidence = website.resolve_website(
            "Acme Botanicals Ltd", ["Acme"], company_number="01234567"
        )
        assert url == "https://acmebotanicals.co.uk"
        assert confidence >= website.MATCH_THRESHOLD

    def test_footer_number_mismatch_never_guessed(self, monkeypatch):
        monkeypatch.setattr(website, "_search_web", lambda query: ["https://acmebotanicals.co.uk"])
        monkeypatch.setattr(website, "_http_get", lambda url: _fake_resp(200, FOOTER_WITH_OTHER_NUMBER))

        url, confidence = website.resolve_website(
            "Acme Botanicals Ltd", ["Acme"], company_number="01234567"
        )
        assert url is None
        assert confidence < website.MATCH_THRESHOLD

    def test_no_footer_number_at_all_never_guessed_even_with_perfect_name_match(self, monkeypatch):
        # Even a domain that matches the company name exactly must not cross
        # the threshold on name-match alone -- footer confirmation is
        # required (spec 03 §1 "never guess").
        monkeypatch.setattr(website, "_search_web", lambda query: ["https://acmebotanicals.co.uk"])
        monkeypatch.setattr(website, "_http_get", lambda url: _fake_resp(200, FOOTER_NO_NUMBER))

        url, confidence = website.resolve_website("Acme Botanicals Ltd", [], company_number="01234567")
        assert url is None
        assert confidence < website.MATCH_THRESHOLD

    def test_no_candidates_found_degrades_gracefully(self, monkeypatch):
        monkeypatch.setattr(website, "_search_web", lambda query: [])
        url, confidence = website.resolve_website("Nonexistent Brand Ltd", [], company_number="01234567")
        assert url is None
        assert confidence == 0.0

    def test_missing_company_number_never_crosses_threshold(self, monkeypatch):
        # Without a CH number to validate against, footer matching can't run,
        # so nothing should ever be treated as confirmed.
        monkeypatch.setattr(website, "_search_web", lambda query: ["https://acmebotanicals.co.uk"])
        monkeypatch.setattr(website, "_http_get", lambda url: _fake_resp(200, FOOTER_WITH_MATCHING_NUMBER))

        url, confidence = website.resolve_website("Acme Botanicals Ltd", ["Acme"])
        assert url is None
        assert confidence < website.MATCH_THRESHOLD

    def test_candidate_fetch_failure_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(website, "_search_web", lambda query: ["https://down-site.example"])
        monkeypatch.setattr(website, "_http_get", lambda url: None)
        url, confidence = website.resolve_website("Acme Botanicals Ltd", [], company_number="01234567")
        assert url is None


class TestCrawlWebsite:
    def test_crawls_homepage_and_respects_max_pages(self, monkeypatch):
        home_html = (
            '<html><body>'
            '<a href="/about">About</a><a href="/products">Products</a>'
            '<a href="/contact">Contact</a>'
            + "some body text " * 100
            + "</body></html>"
        )

        def fake_http_get(url):
            if url == "https://brand.co.uk/robots.txt":
                return _fake_resp(200, "User-agent: *\nDisallow:\n")
            if url == "https://brand.co.uk":
                return _fake_resp(200, home_html)
            return _fake_resp(200, "<html><body>" + "sub page text " * 100 + "</body></html>")

        monkeypatch.setattr(website, "_http_get", fake_http_get)
        # Safety net so this test never touches a real headless browser even
        # if trafilatura's extraction of the fixture HTML comes back short.
        monkeypatch.setattr(website, "_render_with_playwright", lambda url: "x" * 600)
        result = website.crawl_website("https://brand.co.uk")

        assert "https://brand.co.uk" in result["pages"]
        assert len(result["pages"]) <= website._MAX_PAGES
        assert result["pages"]["https://brand.co.uk"]["status"] == 200
        assert result["pages"]["https://brand.co.uk"]["text"]

    def test_robots_disallow_skips_page(self, monkeypatch):
        def fake_http_get(url):
            if url.endswith("robots.txt"):
                return _fake_resp(200, "User-agent: *\nDisallow: /\n")
            return _fake_resp(200, "<html><body>hello</body></html>")

        monkeypatch.setattr(website, "_http_get", fake_http_get)
        result = website.crawl_website("https://blocked.co.uk")
        assert result["pages"] == {}

    def test_missing_url_returns_empty_never_raises(self):
        result = website.crawl_website("")
        assert result["pages"] == {}

    def test_unreachable_site_returns_empty_never_raises(self, monkeypatch):
        monkeypatch.setattr(website, "_http_get", lambda url: None)
        result = website.crawl_website("https://unreachable.example")
        assert result["pages"] == {}

    def test_short_text_triggers_playwright_fallback(self, monkeypatch):
        short_html = "<html><body>Hi</body></html>"  # < 500 chars extracted

        def fake_http_get(url):
            if url.endswith("robots.txt"):
                return _fake_resp(200, "User-agent: *\nDisallow:\n")
            return _fake_resp(200, short_html)

        monkeypatch.setattr(website, "_http_get", fake_http_get)
        monkeypatch.setattr(website, "_render_with_playwright", lambda url: "rendered text " * 60)

        result = website.crawl_website("https://spa-site.co.uk")
        page = result["pages"]["https://spa-site.co.uk"]
        assert page["fetched_via"] == "playwright"
        assert len(page["text"]) >= 500


class TestExtractSocialHandles:
    def test_extracts_known_platforms(self):
        html = (
            '<footer><a href="https://instagram.com/thebrand">IG</a>'
            '<a href="https://www.tiktok.com/@thebrand">TikTok</a></footer>'
        )
        handles = website.extract_social_handles(html)
        assert handles["instagram"] == "thebrand"
        assert handles["tiktok"] == "thebrand"

    def test_empty_html_returns_empty_dict(self):
        assert website.extract_social_handles("") == {}
        assert website.extract_social_handles(None) == {}  # type: ignore[arg-type]


VALID_PROFILE_JSON = json.dumps(
    {
        "heritage_summary": "Founded in 2001 by a herbalist in Bath.",
        "founding_year": 2001,
        "product_range_summary": "Organic skincare balms and oils.",
        "trading_names": ["Bath Botanicals"],
        "has_ecommerce": True,
        "stockists_mentioned": ["John Lewis"],
        "team_size_hint": "our small team of 6",
        "contact_names": ["Jane Smith"],
    }
)


class TestExtractProfile:
    def test_valid_json_validates_and_returns_dict(self, monkeypatch):
        monkeypatch.setattr(website, "_call_llm", lambda prompt: VALID_PROFILE_JSON)
        result = website.extract_profile({"https://brand.co.uk": "some page text about the brand"})
        assert result["has_ecommerce"] is True
        assert result["trading_names"] == ["Bath Botanicals"]

    def test_retries_once_on_invalid_json_then_succeeds(self, monkeypatch):
        calls = {"n": 0}

        def fake_call(prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                return "not valid json at all"
            return VALID_PROFILE_JSON

        monkeypatch.setattr(website, "_call_llm", fake_call)
        result = website.extract_profile({"https://brand.co.uk": "text"})
        assert calls["n"] == 2
        assert result["has_ecommerce"] is True

    def test_two_failures_degrade_to_empty_dict_never_raises(self, monkeypatch):
        monkeypatch.setattr(website, "_call_llm", lambda prompt: "still not json")
        result = website.extract_profile({"https://brand.co.uk": "text"})
        assert result == {}

    def test_empty_page_texts_returns_empty_without_calling_llm(self, monkeypatch):
        called = {"n": 0}

        def fake_call(prompt):
            called["n"] += 1
            return VALID_PROFILE_JSON

        monkeypatch.setattr(website, "_call_llm", fake_call)
        result = website.extract_profile({})
        assert result == {}
        assert called["n"] == 0

    def test_json_wrapped_in_markdown_fence_is_parsed(self, monkeypatch):
        fenced = f"```json\n{VALID_PROFILE_JSON}\n```"
        monkeypatch.setattr(website, "_call_llm", lambda prompt: fenced)
        result = website.extract_profile({"https://brand.co.uk": "text"})
        assert result["has_ecommerce"] is True
