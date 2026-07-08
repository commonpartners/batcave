"""Website resolution & crawl (spec 03 §1).

Three responsibilities, each independently testable:
  - `resolve_website`: find the company's real website and validate it against
    the Companies House registered number printed in the footer — the best
    available validator, since every UK company must display its registered
    number somewhere on its site. Below-threshold matches are never guessed;
    they come back as `(None, confidence)` for the caller to mark
    `needs-review`.
  - `crawl_website`: polite crawl (robots.txt respected, <= 15 pages), text
    extraction via `trafilatura`, with a headless-Playwright fallback only
    when the extracted text is suspiciously short on a 200 response.
  - `extract_profile`: one LLM call over the concatenated crawl text
    (`prompts/website_extract.md`), strict JSON schema, pydantic-validated,
    retried once on schema failure.

Network access is isolated behind small module-level functions (`_http_get`,
`_search_web`, `_render_with_playwright`, `_call_llm`) so tests can monkeypatch
them instead of hitting the network.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from pydantic import BaseModel, Field, ValidationError

from cp_workers.config import settings

_USER_AGENT = "CommonPartnersBot/0.1 (+https://thebothy.club; deal-research enrichment; contact julia@thebothy.club)"
_TIMEOUT_SECONDS = 12.0
_MAX_PAGES = 15
_MIN_EXTRACTED_CHARS = 500
_CH_NUMBER_PATTERN = re.compile(r"\b(\d{8})\b")

# Below this combined confidence, a candidate is never treated as "the"
# website — the caller marks it `needs-review` instead of guessing. Only a
# confirmed footer company-number match can push a candidate above this bar;
# name/UK-signal match alone tops out below it by construction (see
# `_score_candidate`).
MATCH_THRESHOLD = 0.6

# Paths preferentially crawled after the homepage (spec 03 §1: "home, about,
# products, stockists, contact").
_PRIORITY_PATH_KEYWORDS = ("about", "product", "stockist", "contact", "our-story", "shop")


# --------------------------------------------------------------------------
# Network primitives — isolated so tests can monkeypatch without hitting HTTP.
# --------------------------------------------------------------------------

def _http_get(url: str) -> httpx.Response | None:
    try:
        return httpx.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
    except Exception:
        return None


def _search_web(query: str) -> list[str]:
    """Return candidate URLs for a search query.

    Uses Brave Search API if a key is configured, else the DuckDuckGo HTML
    endpoint (no key required, no JS). Never raises: a failed search degrades
    to an empty candidate list rather than blocking enrichment.
    """
    try:
        if settings.brave_search_api_key:
            resp = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": 10},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": settings.brave_search_api_key,
                },
                timeout=_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            results = resp.json().get("web", {}).get("results", [])
            return [r["url"] for r in results if r.get("url")]

        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return re.findall(r'class="result__a"[^>]+href="([^"]+)"', resp.text)
    except Exception:
        return []


def _render_with_playwright(url: str) -> str:
    """Headless-browser fallback text extraction. Imported lazily — Playwright
    is heavy and only needed for the SPA/Shopify-heavy-theme edge case."""
    from playwright.sync_api import sync_playwright  # local import, spec 03 §1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=_USER_AGENT)
            page.goto(url, timeout=int(_TIMEOUT_SECONDS * 1000), wait_until="networkidle")
            html = page.content()
        finally:
            browser.close()
    extracted = trafilatura.extract(html) or ""
    return extracted


# --------------------------------------------------------------------------
# resolve_website
# --------------------------------------------------------------------------

def _name_match_score(url: str, company_name: str, trading_names: list[str] | None) -> float:
    import difflib

    domain = urlparse(url).netloc.lower().removeprefix("www.")
    domain_slug = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])
    candidates = [company_name] + list(trading_names or [])
    best = 0.0
    for name in candidates:
        if not name:
            continue
        slug = re.sub(r"[^a-z0-9]", "", name.lower())
        if not slug:
            continue
        ratio = difflib.SequenceMatcher(None, domain_slug, slug).ratio()
        best = max(best, ratio)
    return best


def _uk_signal_score(url: str, page_text: str) -> float:
    domain = urlparse(url).netloc.lower()
    score = 0.0
    if domain.endswith(".co.uk") or domain.endswith(".uk"):
        score += 0.6
    if re.search(r"\bunited kingdom\b", page_text, re.IGNORECASE):
        score += 0.2
    if re.search(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", page_text):  # UK postcode shape
        score += 0.2
    return min(1.0, score)


def _footer_matches_company_number(page_text: str, company_number: str | None) -> bool:
    if not company_number:
        return False
    normalised_number = company_number.strip().upper().zfill(8)
    found = _CH_NUMBER_PATTERN.findall(page_text or "")
    return any(candidate.zfill(8) == normalised_number for candidate in found)


def _score_candidate(
    url: str,
    company_name: str,
    trading_names: list[str] | None,
    company_number: str | None,
) -> tuple[float, dict[str, Any]]:
    resp = _http_get(url)
    page_text = ""
    if resp is not None and resp.status_code == 200:
        page_text = trafilatura.extract(resp.text) or resp.text or ""

    name_score = _name_match_score(url, company_name, trading_names)
    uk_score = _uk_signal_score(url, page_text)
    footer_match = _footer_matches_company_number(page_text, company_number)

    if footer_match:
        # Confirmed by the strongest available validator — allowed to cross
        # MATCH_THRESHOLD on its own.
        confidence = min(1.0, 0.9 + 0.1 * name_score)
    else:
        # Name/UK signal alone is never enough to declare a confident match —
        # capped below MATCH_THRESHOLD by construction ("never guess").
        confidence = min(MATCH_THRESHOLD - 0.01, 0.3 * name_score + 0.2 * uk_score)

    evidence = {
        "name_match": round(name_score, 3),
        "uk_signal": round(uk_score, 3),
        "footer_company_number_match": footer_match,
        "fetched": resp is not None and resp.status_code == 200,
    }
    return confidence, evidence


def resolve_website(
    company_name: str,
    trading_names: list[str] | None = None,
    *,
    company_number: str | None = None,
) -> tuple[str | None, float]:
    """Resolve a company's real website, validated via footer registered-number match.

    Returns `(url, match_confidence)`. Below `MATCH_THRESHOLD`, `url` is always
    `None` — the caller should mark the company `needs-review` rather than
    guessing (spec 03 §1). `company_number` is keyword-only and optional so
    the positional signature stays exactly `(company_name, trading_names)` per
    CONTRACT.md; without it, footer validation can't run and candidates can
    never cross the threshold (there is no other validator strong enough to
    stand alone).
    """
    query = f"{company_name} official website UK"
    candidate_urls = _search_web(query)

    best_url: str | None = None
    best_confidence = 0.0
    for url in candidate_urls[:10]:
        try:
            confidence, _evidence = _score_candidate(url, company_name, trading_names, company_number)
        except Exception:
            continue
        if confidence > best_confidence:
            best_confidence = confidence
            best_url = url

    if best_confidence < MATCH_THRESHOLD:
        return None, best_confidence

    return best_url, best_confidence


# --------------------------------------------------------------------------
# crawl_website
# --------------------------------------------------------------------------

def _robots_allows(base_url: str, path_url: str) -> bool:
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = robotparser.RobotFileParser()
    resp = _http_get(robots_url)
    if resp is not None and resp.status_code == 200:
        parser.parse(resp.text.splitlines())
    else:
        # No reachable robots.txt -> permissive default (nothing to disallow).
        parser.parse([])
    try:
        return parser.can_fetch(_USER_AGENT, path_url)
    except Exception:
        return True


def _extract_links(base_url: str, html: str) -> list[str]:
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html or "")
    domain = urlparse(base_url).netloc
    links: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc != domain:
            continue
        clean = absolute.split("#")[0]
        if clean in seen:
            continue
        seen.add(clean)
        links.append(clean)
    return links


def _prioritise(links: list[str]) -> list[str]:
    def priority(link: str) -> tuple[int, str]:
        path = urlparse(link).path.lower()
        for rank, keyword in enumerate(_PRIORITY_PATH_KEYWORDS):
            if keyword in path:
                return (rank, link)
        return (len(_PRIORITY_PATH_KEYWORDS), link)

    return sorted(links, key=priority)


def crawl_website(url: str) -> dict[str, Any]:
    """Politely crawl up to `_MAX_PAGES` pages of a site and extract text.

    Respects robots.txt, extracts text via `trafilatura`, and falls back to a
    single headless-Playwright render only when the extracted text is < 500
    chars on an otherwise-200 response (spec 03 §1 "JS-rendered fallback").
    Returns `{"pages": {url: {"text": str, "html": str, "headers": dict,
    "status": int, "fetched_via": str}}, "homepage": url}`. The raw
    homepage HTML/headers are kept (not just extracted text) so
    `enrichment.webtech.detect_webtech` has something to fingerprint. Never
    raises: unreachable pages are simply omitted from the result.
    """
    pages: dict[str, dict[str, Any]] = {}
    if not url:
        return {"pages": pages, "homepage": url}

    to_visit = [url]
    visited: set[str] = set()

    while to_visit and len(pages) < _MAX_PAGES:
        current = to_visit.pop(0)
        if current in visited:
            continue
        visited.add(current)

        if not _robots_allows(url, current):
            continue

        resp = _http_get(current)
        if resp is None:
            continue

        status = resp.status_code
        html = resp.text if status == 200 else ""
        text = trafilatura.extract(html) or "" if html else ""
        fetched_via = "http"

        if status == 200 and len(text) < _MIN_EXTRACTED_CHARS:
            try:
                rendered_text = _render_with_playwright(current)
            except Exception:
                rendered_text = ""
            if len(rendered_text) > len(text):
                text = rendered_text
                fetched_via = "playwright"

        pages[current] = {
            "text": text,
            "html": html,
            "headers": dict(resp.headers) if resp is not None else {},
            "status": status,
            "fetched_via": fetched_via,
        }

        if status == 200 and html and len(visited) == 1:
            # Only expand link discovery from the homepage — keeps the crawl
            # small and predictable rather than following every in-page link.
            links = _prioritise(_extract_links(url, html))
            for link in links:
                if link not in visited and link not in to_visit:
                    to_visit.append(link)

    return {"pages": pages, "homepage": url}


_SOCIAL_LINK_PATTERNS: dict[str, re.Pattern[str]] = {
    "instagram": re.compile(r"instagram\.com/([A-Za-z0-9_.]+)", re.IGNORECASE),
    "facebook": re.compile(r"facebook\.com/([A-Za-z0-9_.]+)", re.IGNORECASE),
    "tiktok": re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)", re.IGNORECASE),
}
_SOCIAL_IGNORED_HANDLES = {"sharer", "share", "share.php", "login", "home"}


def extract_social_handles(homepage_html: str) -> dict[str, str]:
    """Pull Instagram/Facebook/TikTok handles from footer/nav links (spec 03 §5).

    Deliberately simple regex extraction (not LLM) over raw homepage HTML;
    never raises, returns `{}` for a page with no recognisable social links.
    """
    handles: dict[str, str] = {}
    html = homepage_html or ""
    for platform, pattern in _SOCIAL_LINK_PATTERNS.items():
        match = pattern.search(html)
        if not match:
            continue
        handle = match.group(1).strip("/")
        if handle and handle.lower() not in _SOCIAL_IGNORED_HANDLES:
            handles[platform] = handle
    return handles


# --------------------------------------------------------------------------
# extract_profile (LLM)
# --------------------------------------------------------------------------

class WebsiteProfile(BaseModel):
    """Strict schema for `prompts/website_extract.md` output (spec 03 §1)."""

    heritage_summary: str | None = Field(default=None, description="Founding story / heritage claims, if any.")
    founding_year: int | None = Field(default=None)
    product_range_summary: str | None = Field(default=None)
    trading_names: list[str] = Field(default_factory=list)
    has_ecommerce: bool = False
    stockists_mentioned: list[str] = Field(default_factory=list)
    team_size_hint: str | None = Field(default=None)
    contact_names: list[str] = Field(default_factory=list)


def _call_llm(prompt: str) -> str:
    """Single Anthropic call, isolated for testability. Raises on failure —
    callers (here, `extract_profile`) are responsible for retry/degrade."""
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")


def _load_prompt_template() -> str:
    from pathlib import Path

    prompt_path = Path(__file__).resolve().parents[2] / "prompts" / "website_extract.md"
    return prompt_path.read_text(encoding="utf-8")


def _extract_json_block(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    # Strip a ```json ... ``` fence if the model wrapped its output in one.
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fence_match:
        raw = fence_match.group(1).strip()
    return json.loads(raw)


def extract_profile(page_texts: dict[str, str]) -> dict[str, Any]:
    """LLM extraction over concatenated crawl text (spec 03 §1).

    `page_texts` maps url -> extracted text (the `"text"` values of
    `crawl_website(url)["pages"]`, typically). Validates the model's JSON
    output against `WebsiteProfile`; retries once on invalid JSON/schema
    failure. Returns `{}` (never raises) if both attempts fail, so a bad LLM
    response degrades the profile rather than blocking the rest of
    enrichment.
    """
    concatenated = "\n\n".join(text for text in page_texts.values() if text).strip()
    if not concatenated:
        return {}

    template = _load_prompt_template()
    prompt = template.replace("{{PAGE_TEXT}}", concatenated[:20000])

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            raw = _call_llm(prompt)
            data = _extract_json_block(raw)
            profile = WebsiteProfile.model_validate(data)
            return profile.model_dump()
        except (json.JSONDecodeError, ValidationError, Exception) as exc:  # noqa: BLE001
            last_error = exc
            continue

    return {}
