# Spec 03 — Enrichment Pipeline

Turns a discovered company into a scoreable profile. Runs per company (`cli.py enrich --company <number>` / `--pending`). Each step writes `source_records` first, derived fields second. Steps are independent — one failing never blocks the others; profile carries per-field freshness.

## 1. Website resolution & crawl (`enrichment/website.py`)

- Resolve website: CH profile rarely has it — search by company/trading name (DuckDuckGo HTML endpoint or Brave Search API if key present), score candidates by name match + UK signals + footer company-number match (**best validator: UK companies must display registered number — regex `\b\d{8}\b` and match against CH number**). Below-threshold matches → `needs-review`, not guessed.
- Crawl politely (respect robots.txt, ≤ 15 pages: home, about, products, stockists, contact). Store HTML in Supabase Storage; text extraction via `trafilatura`.
- **JS-rendered fallback:** if extracted text < 500 chars on a 200 response (SPA/Shopify-heavy themes), re-fetch that page once with headless Playwright (installed in the worker image). Same politeness rules. Two-tier fetch keeps the common case fast and the hard case working.
- **Skip-unchanged:** hash fetched content; if unchanged vs last `source_records` hash, skip re-extraction (and any downstream LLM call). Weekly refreshes then cost almost nothing when nothing changed — this is what makes weekly cadence sustainable.
- **LLM extraction** (`prompts/website_extract.md`, one call per site over concatenated page text): founding story/heritage claims, product range summary, trading names, e-commerce present?, stockists mentioned, team size hints, contact/owner names. Output = strict JSON schema; validate with pydantic; retry once on invalid.

## 2. Web-tech detection (`enrichment/webtech.py`)

Deterministic — no LLM. From raw HTML + headers detect: platform (Shopify/Woo/Wix/Squarespace/custom via fingerprints), analytics (GA4/GTM), ad pixels (Meta/TikTok/Google Ads/Pinterest), email capture (Klaviyo/Mailchimp/newsletter forms), live chat, structured data. Store as `{feature: bool/name}` in a `source_records` row + summarised onto the profile.

## 3. Reviews (`enrichment/reviews.py`)

- **Trustpilot:** fetch `uk.trustpilot.com/review/{domain}` and parse the **JSON-LD `aggregateRating` block** (server-rendered, stable schema) rather than scraping the visible DOM — survives their frontend redesigns. Honest UA, per-request delay, one retry; if blocked, mark reviews `missing` and move on — never hammer.
- **Google reviews:** Places API (if key configured) else skip — do not scrape Google.
- Store per-source `{rating, count, fetched_at}`; compute `review_strength` 0–1 = weighted blend (volume log-scaled × rating normalised). **Improvement over design notes:** also compute a **trend** — compare count/rating vs previous fetch; declining trend feeds the `structural_decline` red flag (spec 04 §5) automatically rather than by manual judgement.

## 4. Digital maturity score (1–5, deterministic rubric)

| Score | Criteria |
|---|---|
| 1 | No functioning site, or brochure page only |
| 2 | Static site; no e-commerce, no email capture, no pixels |
| 3 | E-commerce present but ≤ 1 of {email capture, analytics, any ad pixel} |
| 4 | E-commerce + email capture + analytics; some paid/social activity |
| 5 | Full stack: modern platform, CRM/email flows, multiple pixels, active content cadence |

Computed in code from §1–2 outputs. This is the denominator of the latent-upside edge — keep it deterministic and auditable.

## 5. Social presence (`enrichment/social.py`)

Best-effort, brittle by nature — design for graceful degradation. From website footer links, capture Instagram/Facebook/TikTok handles; fetch public follower counts and last-post date where accessible without login. Store what's obtained; missing social data lowers confidence, never errors. Do not build login-based scraping.

## 6. Distribution footprint

From §1 LLM extraction (stockists mentioned) + reverse check against the retailer stockist scrapes (spec 02 §8): `notable_stockists text[]`, `marketplace_presence jsonb` (Amazon UK storefront search by brand name — presence + review count only), `distribution_breadth` 0–1.

## 7. Financial estimation (`enrichment/financials.py`)

Where filing category hides P&L (micro/small):
- Inputs: balance-sheet items, employee count, sector benchmark ratios (config table: revenue-per-employee and EBITDA-margin ranges for skincare/personal-care; seed with researched values, cite source).
- Output: `revenue_estimate` / `ebitda_estimate` with `method: benchmark` and `confidence: low/med` — **never present estimates as facts in the UI; always badge with confidence + method.**
- Medium/large filers: parse actual P&L from iXBRL, `confidence: high`.

## 8. Orchestration & freshness

`enrich --pending` = companies at lifecycle `discovered` or with dirty flags. Per-source refresh intervals in `app_config` (website 90d, reviews 30d, social 60d). After enrichment completes, lifecycle → `enriched`, and scoring is queued.

**Failure discipline (what makes weekly runs reliable):** every step wrapped with `tenacity` retries (3 attempts, exponential backoff); a step that still fails writes a row to `jobs.stats.failures` with company, step, error, and the company keeps its previous data (per-field freshness means stale ≠ absent). Companies failing the same step 3 consecutive runs surface in `/held` as `enrichment-blocked` for a human look. Nothing retries forever; nothing fails silently.

**LLM cost guardrail:** enrichment + scoring calls capped per run (config `llm_budget_per_run`, default 300 calls); over-budget companies wait for next run; jobs stats record spend.
