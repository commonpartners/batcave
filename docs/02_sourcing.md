# Spec 02 — Sourcing Engine (Phase 2 build; connectors reused in Phase 1)

Discovers candidate companies, keeps profiles fresh, computes signals, maintains the watchlist. All Python, in `workers/cp_workers/`.

## 1. Companies House client (`connectors/companies_house.py`)

- Base: `https://api.company-information.service.gov.uk`, HTTP Basic auth (API key as username, blank password).
- **Shared throttle:** 600 req / 5 min. Implement a token bucket; on 429, back off per `Retry-After`.
- Endpoints used: company profile `/company/{number}`; officers `/company/{number}/officers`; PSCs `/company/{number}/persons-with-significant-control`; filing history `/company/{number}/filing-history`; **advanced search** `/advanced-search/companies` (filter by `sic_codes`, `company_status=active`, incorporation date range); document API for accounts (fetch iXBRL where `links.document_metadata` present).
- Every response → `source_records` row before any parsing.
- iXBRL parsing: use `stream-read-xbrl` or fallback to the CH **accounts bulk data products** if per-company documents prove unreliable; extract balance-sheet facts listed in spec 01 §1 **plus average employee count — small companies must disclose it in the notes even when they withhold the P&L, making it the most reliable free size proxy for the dark end of the market.** Parsing failures are logged, never fatal.

## 2. Universe definition (`taxonomy_rules` seed)

Launch tag `skincare-personal-care`:

- **SIC seeds:** 20420 (manufacture of perfumes/toilet preparations), 46450 (wholesale perfume/cosmetics), 47750 (retail cosmetic/toilet articles), 20411/20412 (soap/detergents), 96020 (hairdressing/beauty — service arm, lower priority), 86900 (other human health, filtered hard by keywords).
- **Include keywords** (name + website): skincare, skin care, cosmetics, beauty, botanical, organic, natural, serum, balm, soap, bath, body care, haircare, aromatherapy, spa.
- **Exclude keywords:** software, app, platform, clinic, surgery, pharma, medical device, salon-only chains (unless product line evident).
- Classification: SIC match → candidate; keyword rules refine; ambiguous cases (SIC hit but weak keywords, or vice versa) → LLM classifier (`prompts/sector_classify.md`) returning tag + confidence; below 0.7 confidence → tag `needs-review`.

**Universe filters** (all applied at discovery): status active, no insolvency/strike-off flags in filing history, incorporation ≥ 8 years ago (config `min_company_age_years`), UK-registered.

## 3. Discovery & refresh (two mechanisms, both quota-safe and runnable today)

**Improvement over the design notes** (which assumed API pagination): discovery uses the free **CH bulk snapshot**; refresh uses targeted REST calls sized well inside the rate limit. No streaming infrastructure, no daemon — everything is a batch job that finishes.

### 3a. Monthly discovery (`cli.py discover`)

Download the monthly *Free Company Data Product* (`BasicCompanyDataAsOneFile` — one CSV of every live UK company: number, name, SICs, status, incorporation date, address; ~450MB zipped). Stream-parse locally; a company is a **candidate** if either:

1. any SIC code in the taxonomy seed list, **or**
2. company name matches include-keywords — this catches the many DTC consumer brands registered under generic codes the SIC seeds miss, especially **47910 (retail via mail order / internet)** and 47190/47990. Never ingest 47910 wholesale — keyword match on name is the filter that makes it usable.

Then apply universe filters (active, age ≥ min, exclude-keywords) locally — zero API quota. Surviving new candidates → `companies` (lifecycle `discovered`) → REST detail fetch (profile, officers, PSC, filing history) under the throttle. Expect the snapshot scan to run in well under an hour on a GitHub Actions runner.

### 3b. Weekly refresh (`cli.py refresh`)

For **universe companies only**: re-fetch profile + officers + PSC + filing-history; `content_hash` diff per endpoint; changed → mark dirty → signal recompute → re-score.

**Quota math (why this is safe):** ~2,000 universe companies × 4 endpoints = 8,000 calls ≈ 70 minutes at 600 req/5 min. Comfortably inside one Actions job (6h ceiling) up to a universe of ~10k. The throttled client makes breaching the limit impossible by construction; 429s back off per `Retry-After`.

Change events that must trigger immediate signal recompute: new accounts filed, director appointed/terminated, PSC change, status change.

*(CH Streaming API is a Phase 3 optimisation if the universe outgrows the weekly window — not needed for weekly cadence, don't build it now.)*

## 4. Signals (`signals/` — pure functions, exhaustively unit-tested)

Each returns `(value 0–1, evidence, rationale)`; job writes to `signals` table.

**Succession family:**
- `director_retirement_window`: controlling director (PSC ≥ 25% or sole/majority director) aged 65–75 → value scales 0 at 60 → 1.0 at 68–72 → taper to 0.6 at 78. Age from CH birth month/year.
- `long_single_owner_tenure`: same person director ≥ 12 yrs (0.5) → ≥ 20 yrs (1.0), AND ≤ 2 other active directorships.
- `board_psc_event_recent`: director termination / PSC change / family member off the board within 18 months → 1.0 decaying with age of event.

**Latent-upside family** (needs enrichment data, spec 03):
- `reviews_strong_digital_weak`: review score ≥ 4.3 with ≥ 100 reviews AND digital_maturity ≤ 2 → high. Formula: `review_strength × (1 − (digital_maturity−1)/4)`.
- `narrow_distribution`: strong reviews but ≤ 2 notable stockists and no marketplace presence.
- `heritage_underexploited`: company age ≥ 20 yrs + brand recognition evidence (press/awards) + digital_maturity ≤ 2.

**Consolidation family:**
- `fragmented_subcategory`: count of universe companies sharing the sector tag within size band; many small + no dominant player (no company > 10× median size) → high.
- `adjacency`: shares stockists/channels/suppliers with a company already tagged `pursue` or portfolio-flagged. (Stub returning 0 until portfolio exists — build the interface, not the logic.)

## 5. Watchlist (`cli.py watchlist-check`)

- Entry: manual (from app) or automatic — gate pass + total_score ≥ 70 (config) but no succession signal ≥ 0.5.
- Weekly check: recompute succession signals for watchlist companies; any signal crossing 0.5 → status `fired`, push company to pipeline `inbox`, flag "watchlist fired" in UI.
- `deprioritise_after` passed with no fire → status `expired`, lifecycle `archived` (reversible in UI).

## 6. Scheduling (GitHub Actions, `.github/workflows/`)

| Workflow | Cron | Command |
|---|---|---|
| discover.yml | 1st of month 03:00 UTC | `discover` (bulk snapshot scan) |
| refresh.yml | Mon 06:00 UTC | `refresh` then `compute-signals --changed-only` |
| enrich.yml | Mon 09:00 UTC | `enrich --pending` (spec 03) |
| score.yml | Mon 12:00 UTC | `score --pending` (spec 04) |
| watchlist.yml | Mon 13:00 UTC | `watchlist-check` |
| digest.yml | Mon 14:00 UTC | `digest` — email summary (below) |

Each job: acquire `jobs` row with run_key = ISO week (month for discover); skip if already succeeded; write stats (companies scanned/new/changed, API calls, failures). Failures of individual companies never abort the run — collect and report in stats. **Any job that fails outright sends an alert email — a silent dead pipeline is the biggest operational risk for a two-person system.**

**Weekly digest (`cli.py digest`, via Resend free tier or SMTP):** one email to Julia + Ben every Monday afternoon — new qualifiers (name, score, angle, link), watchlist fires, companies newly held, run health (counts + failures). This is the heartbeat that proves the loop ran and makes the system feel alive without anyone remembering to check the app.

## 7. Manual intake (Phase 1 path)

`cli.py intake --file companies.csv` (columns: company_number or name+website) and an app-side "Add companies" paste box hitting the same code path: resolve to company_number via CH search, create `companies` rows, mark lifecycle `discovered`. This is how Phase 1 runs before automated discovery exists.

## 8. Trade-body / stockist / awards sources

Phase 2.5 (after core loop works). One scraper module per source, each producing candidate names → CH resolution → intake path. Sources, in priority order: CTPA member directory, Independent Beauty Association, British Beauty Council, B Corp directory (UK beauty filter), CEW / Beauty Shortlist / Free From Skincare award lists, stockist pages of Space NK, Cult Beauty, John Lewis, Holland & Barrett. Membership/award/stockist presence is stored as `source_records` and used as evidence in scoring (brand equity) — being on these lists is a quality flag, and stockist count feeds distribution signals.
