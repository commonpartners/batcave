# Worker package interface contract

Four agents are building `cp_workers` in parallel and cannot see each other's code.
This pins the module boundaries, function signatures, and CLI ownership so the
pieces fit together without cross-agent coordination. **Nobody except the
integration pass touches `cp_workers/cli.py`** — every agent exposes plain
importable functions; the CLI wiring happens after all four land.

Already built (shared infra, read but do not modify unless fixing a bug):
- `cp_workers/config.py` — `settings` (env-driven: `companies_house_api_key`,
  `supabase_url`, `supabase_service_role_key`, `anthropic_api_key`,
  `anthropic_model`, `resend_api_key`, `digest_recipients`, etc).
- `cp_workers/db.py` — `get_client()` (Supabase client), `content_hash(payload)`,
  `record_source(company_id, source, source_url, raw)` (writes `source_records`,
  always call before parsing per spec 00 §4), `last_source_hash(company_id, source)`
  (skip-unchanged), `upsert_company(company_number, fields)`,
  `get_company_by_number(company_number)`, `get_config(key, default)`.
- `cp_workers/jobs.py` — `start_job(job_name, run_key) -> dict | None` (None means
  already succeeded — no-op),`finish_job(job, status, stats=None, error=None)`.
- SQL schema: `supabase/migrations/*.sql` — this is the source of truth for every
  table/column name. Read it, don't guess column names from the spec prose.

Signal functions return a plain tuple `(value: float, evidence: dict, rationale: str)`
per spec 02 §4 — no shared dataclass, keeps signal modules import-free of each other.

---

## Agent A — sourcing & CH client + succession/consolidation signals

Files you own: `connectors/companies_house.py`, `connectors/__init__.py` additions,
`signals/succession.py`, `signals/consolidation.py`, plus business-logic functions
(no CLI decorators) that the integration pass will wire into `cli.py`:

- `connectors/companies_house.py`:
  - `class CompaniesHouseClient` — token-bucket throttle (600 req / 5 min), methods
    `get_profile(number)`, `get_officers(number)`, `get_psc(number)`,
    `get_filing_history(number)`, `advanced_search(sic_codes, status, incorp_from, incorp_to)`,
    `get_document(metadata_url)`. Every call must go through `db.record_source(...)`
    before returning parsed data. 429 → back off per `Retry-After` header.
  - `parse_ixbrl(document_bytes) -> dict` — balance sheet facts + average employee
    count (spec 02 §1); never raise on malformed input, log and return `{}`.
- Bulk discovery: `discover_universe(snapshot_path: str) -> DiscoverStats` — stream-parse
  the Free Company Data Product CSV, apply taxonomy + universe filters (age >= config
  `min_company_age_years`, active, no insolvency), upsert survivors as `companies`
  (`lifecycle='discovered'`).
- `classify_sector(name: str, website_text: str | None, sic_codes: list[str]) -> tuple[str, float, str]`
  → `(sector_tag, confidence, source)` where `source` is `"rules"` or `"llm"`
  (`prompts/sector_classify.md`, confidence < 0.7 → tag `needs-review`).
- `refresh_universe_company(company_number: str) -> bool` — re-fetch profile/officers/
  PSC/filing-history, content-hash diff, return whether anything changed (dirty flag).
- `intake_from_csv(path: str) -> IntakeReport` — resolve name/number rows to
  `company_number` via CH search, upsert `companies`, report unresolved rows.
- `export_phase0(company_numbers: list[str], out_path: str) -> None` — pull CH data,
  compute succession signals, write one xlsx row per company with empty rubric
  dimension columns (spec 06 Phase 0).
- `signals/succession.py`: `director_retirement_window(people, now)`,
  `long_single_owner_tenure(people)`, `board_psc_event_recent(events, now)` — exact
  formulas in spec 02 §4. Exhaustive pytest fixtures: missing DOB, dissolved company,
  no officers.
- `signals/consolidation.py`: `fragmented_subcategory(universe_companies, target)`,
  `adjacency(company, portfolio_companies)` (stub, always returns
  `(0.0, {}, "no portfolio yet")` until a portfolio exists — build the interface only).

## Agent B — enrichment pipeline

Files you own: `enrichment/website.py`, `enrichment/webtech.py`, `enrichment/reviews.py`,
`enrichment/social.py`, `enrichment/distribution.py`, `enrichment/financials.py`,
`enrichment/digital_maturity.py`, `signals/latent_upside.py`, `enrichment/orchestrate.py`.

- `enrichment/website.py`: `resolve_website(company_name, trading_names) -> tuple[str | None, float]`
  (url, match_confidence — validate via registered-number regex `\b\d{8}\b` in footer
  vs CH number per spec 03 §1; below-threshold → `None`, mark `needs-review`, never guess).
  `crawl_website(url) -> dict` (page texts, ≤15 pages, robots.txt respected, Playwright
  fallback if extracted text < 500 chars). `extract_profile(page_texts) -> dict`
  (`prompts/website_extract.md`, pydantic-validated, retry once on schema failure).
- `enrichment/webtech.py`: `detect_webtech(html, headers) -> dict` — deterministic,
  no LLM (platform, analytics, ad pixels, email capture, live chat, structured data).
- `enrichment/reviews.py`: `fetch_trustpilot(domain) -> dict | None` (parse JSON-LD
  `aggregateRating`, never scrape DOM), `fetch_google_reviews(place_query) -> dict | None`
  (Places API if key present, else `None` — never scrape Google).
  `review_strength(rating, count) -> float` (0-1, log-scaled volume × normalised rating).
  `review_trend(current, previous) -> str` (`improving`/`flat`/`declining` — feeds
  `structural_decline` red flag, spec 03 §3).
- `enrichment/social.py`: `fetch_social(handles: dict) -> dict` — best-effort, never
  raises, missing data lowers confidence not correctness.
- `enrichment/distribution.py`: `distribution_breadth(notable_stockists, marketplace_presence) -> float`.
- `enrichment/financials.py`: `estimate_financials(balance_sheet, employee_count, sector_tag) -> tuple[dict, dict]`
  → `(revenue_estimate, ebitda_estimate)` each shaped
  `{"value_pence": int, "source": str, "method": "benchmark"|"filed", "confidence": "high"|"med"|"low", "as_of": str}`.
  Include a small benchmark-ratio config table (revenue-per-employee, EBITDA-margin
  ranges for skincare/personal-care) with a cited source in a code comment.
- `enrichment/digital_maturity.py`: `compute_digital_maturity(webtech: dict, has_ecommerce: bool) -> int`
  (1-5, exact rubric in spec 03 §4 — pure function, exhaustively tested).
- `signals/latent_upside.py`:
  - `reviews_strong_digital_weak(review_strength, digital_maturity) -> tuple[float, dict, str]`
  - `narrow_distribution(review_strength, notable_stockists_count, marketplace_presence) -> tuple[float, dict, str]`
  - `heritage_underexploited(company_age_years, brand_recognition_evidence, digital_maturity) -> tuple[float, dict, str]`
  - `latent_digital_upside_dimension(review_strength, digital_maturity, distribution_breadth) -> float`
    (0-5, formula: `5 * review_strength * (1 - (digital_maturity - 1) / 4)`, +0.5 if
    `distribution_breadth < 0.3`, capped at 5 — spec 04 §3. This is the ONLY place
    this formula is implemented; Agent C's rules dimension calls this function.)
- `enrichment/orchestrate.py`: `enrich_company(company_number: str) -> EnrichReport` —
  runs all steps independently (one failing never blocks others), `tenacity` retries
  (3 attempts) per step, writes freshness per field, sets `lifecycle='enriched'` on
  success, records `jobs.stats.failures` entries on repeated failure.

## Agent C — scoring engine & ops

Files you own: `scoring/gate.py`, `scoring/dimensions.py`, `scoring/llm_dimensions.py`,
`scoring/red_flags.py`, `scoring/value_angles.py`, `scoring/pipeline.py`,
`scoring/watchlist.py`, `scoring/digest.py`, `scoring/calibration.py`,
`prompts/score_qualitative.md`.

Imports `latent_digital_upside_dimension` from `cp_workers.signals.latent_upside`
(Agent B) for the one rules dimension that needs it — everything else in this
package is self-contained.

- `scoring/gate.py`: `run_gate(profile: dict, gate_config: dict) -> GateResult`
  (`GateResult = {"result": "pass"|"hold"|"fail", "detail": {test_name: {"result":..., "reason":...}}}`)
  implementing the six tests in spec 04 §2 exactly (sector, product type, size,
  foundations, situation, geography — situation never hard-fails).
  `compute_size_band(ebitda_estimate, revenue_estimate, balance_sheet, employee_count, thresholds) -> str`.
- `scoring/dimensions.py`: rules dimensions — `financial_quality(...)`,
  `deal_accessibility(succession_signals, unadvised: bool)`, `market_consolidation(fragmented_subcategory_value, adjacency_value)`,
  and `latent_digital_upside(...)` (thin wrapper calling Agent B's function). Each
  returns `(raw_score_0_to_5: float, evidence: dict, rationale: str)`.
- `scoring/llm_dimensions.py`: one Anthropic call per company covering
  `brand_customer_equity`, `team_continuity`, `differentiation` — anchored rubric +
  3 few-shot examples in the prompt file, temperature 0, pydantic-validated strict
  JSON, retry once on schema failure, two failures → dimension `None` +
  company flagged `scoring-incomplete` (never fabricate). Prompt hash stored.
- `scoring/red_flags.py`: the six flags in spec 04 §5, rules where possible / LLM
  assist where not.
- `scoring/value_angles.py`: the five angles in spec 04 §6, rules first, LLM
  tie-break when > 2 qualify, max 2 returned.
- `scoring/pipeline.py`: `score_company(company_number: str, rubric_version: str | None = None) -> ScoreResult`
  — cost-ordered per spec 04 §1 (gate + rules free; red flags before LLM; LLM only
  for gate-passers), `profile_hash` cache check before any LLM call, persists
  `scores` + `score_dimensions`, updates `companies.lifecycle`, creates/refreshes
  `pipeline_items` at `inbox` for gate-passers >= shortlist threshold.
- `scoring/watchlist.py`: `watchlist_check() -> WatchlistStats` (spec 02 §5 — entry/fire/
  expire logic; auto-entry: pass + score >= config threshold but no succession
  signal >= 0.5).
- `scoring/digest.py`: `build_digest() -> dict` + `send_digest(content: dict) -> None`
  (Resend, spec 02 §6 — new qualifiers, watchlist fires, held companies, run health).
- `scoring/calibration.py`: `run_calibration_audit(benchmark_company_numbers: list[str]) -> CalibrationReport`
  (spec 04 §4 — alert if any LLM dimension moves > 1 point vs stored baseline).

## Agent D — Next.js review app

Directory: `app/`. Next.js 14+ App Router, TypeScript, Tailwind, shadcn/ui, Supabase
JS client (magic-link auth, allowlist `julia@thebothy.club` + one Ben address read
from an env var `NEXT_PUBLIC_ALLOWLISTED_EMAILS`, comma-separated).

Query the views/tables directly by the exact names in `supabase/migrations/0008_views.sql`
and `0002-0007*.sql`: `v_shortlist`, `v_company_detail`, `v_watchlist`, plus
`pipeline_items`, `decisions`, `app_config`, `jobs`, `rubric_versions`, `taxonomy_rules`
for `/held` and `/admin`. Pages, decision dialog, and non-functional requirements are
exactly as specified in `docs/05_app_and_learning.md` — read it in full before
starting. Do not invent new table/column names; if something the spec implies isn't
in the schema, note it in your final report rather than guessing a migration change.
Playwright smoke tests per spec 05 §4 (login, shortlist renders against seeded
fixture data, open company, record decision, decision appears in history) — seed
fixture data with a small SQL script under `app/e2e/fixtures.sql` the tests can load.
