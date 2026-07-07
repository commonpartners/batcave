# Spec 01 — Data Model (Supabase Postgres)

Create as SQL migrations in `supabase/migrations/`. All tables get `id uuid primary key default gen_random_uuid()`, `created_at timestamptz default now()`, `updated_at timestamptz` (trigger-maintained) unless noted. Use `text` + CHECK constraints for enums (easier migrations than native enums). Enable RLS on all tables; single policy: authenticated users (Julia, Ben) get full read/write; service role bypasses.

## 1. `companies` — the central profile

| Column | Type | Notes |
|---|---|---|
| company_number | text UNIQUE NOT NULL | Companies House number; natural key for upserts |
| legal_name | text NOT NULL | |
| trading_names | text[] | |
| incorporation_date | date | |
| company_status | text | `active` / `dissolved` / `liquidation` / `strike-off` / ... (CH values verbatim) |
| registered_address | jsonb | CH payload |
| region | text | derived (e.g. postcode area → region lookup) |
| website | text | |
| sic_codes | text[] | |
| sector_tags | text[] | our taxonomy, e.g. `skincare`, `personal-care`, `supplements` (spec 02 §2) |
| sector_tag_source | text | `rules` / `llm` / `manual` |
| filing_category | text | `micro` / `small` / `medium` / `large` / `full` / `unknown` — from latest accounts type |
| latest_accounts_date | date | |
| balance_sheet | jsonb | parsed iXBRL figures: total_assets, net_assets, cash, creditors, shareholders_funds (pence) |
| employee_count | int | from filings where present |
| size_band | text | `too-small` / `fit-now` / `stretch` / `too-large` / `unknown` — computed (spec 04 §2) |
| revenue_estimate | jsonb | `{value_pence, source, method, confidence: high/med/low, as_of}` |
| ebitda_estimate | jsonb | same shape |
| digital_maturity | int CHECK 1..5 | from enrichment (spec 03 §4) |
| summary | text | one-line LLM summary |
| lifecycle | text NOT NULL default `discovered` | `discovered` / `enriched` / `scored` / `shortlisted` / `watchlist` / `rejected` / `archived` |

Indexes: `company_number`, `lifecycle`, GIN on `sector_tags`, `sic_codes`.

## 2. `people` + `company_people`

`people`: | ch_officer_id text UNIQUE | name text | birth_year int | birth_month int | (from CH officers API — month/year only; **never store full DOB even if obtainable**).

`company_people`: | company_id FK | person_id FK | role text (`director` / `psc` / `secretary`) | appointed_on date | resigned_on date | psc_kind text | ownership_pct_band text (CH PSC bands: `25-50`, `50-75`, `75-100`) | is_active bool generated (resigned_on IS NULL) |

Derived (computed by signals job, stored on `company_people`): `tenure_years numeric`, `other_active_directorships int`, `age_years int` (from birth month/year vs now).

## 3. `signals`

One row per computed signal per company per run — append-only, timestamped.

| Column | Type | Notes |
|---|---|---|
| company_id | FK | |
| family | text | `succession` / `latent_upside` / `consolidation` |
| name | text | e.g. `director_retirement_window`, `long_single_owner_tenure`, `psc_change_recent`, `reviews_strong_digital_weak`, `narrow_distribution`, `heritage_underexploited`, `fragmented_subcategory`, `adjacency` |
| value | numeric | 0–1 normalised strength |
| evidence | jsonb | facts + source_record ids used |
| rationale | text | one line |
| computed_at | timestamptz | |
| signal_version | text | code version of the signal definition |

Index: `(company_id, name, computed_at desc)`.

## 4. `rubric_versions` + `scores` + `score_dimensions`

`rubric_versions`: | version text UNIQUE (semver) | weights jsonb (dimension→weight, must sum to 100) | gate_config jsonb | prompt_hashes jsonb | active bool (exactly one) | notes text |

Seed v1.0.0 with weights from spec 04 §3.

`scores` (one row per scoring run per company):

| Column | Type |
|---|---|
| company_id | FK |
| rubric_version | text FK |
| gate_result | text `pass` / `hold` / `fail` |
| gate_detail | jsonb (per-test result + reason) |
| total_score | numeric 0–100, NULL if gate ≠ pass |
| red_flags | text[] (spec 04 §5 keys) |
| value_angles | text[] (spec 04 §6 keys, max 2) |
| profile_hash | text (hash of profile JSON scored — cache key, spec 04 §3) |
| data_completeness | numeric 0–1 (spec 04 §3) |
| scored_at | timestamptz |

Unique partial index on `(company_id, profile_hash, rubric_version)` to enforce the score cache.

`score_dimensions`: | score_id FK | dimension text | raw_score numeric 0–5 | weighted numeric | method text `rules`/`llm` | rationale text | evidence jsonb | prompt_hash text (if llm) |

## 5. `source_records` — provenance

| Column | Type | Notes |
|---|---|---|
| company_id | FK nullable | |
| source | text | `companies_house_profile` / `companies_house_officers` / `companies_house_psc` / `companies_house_filings` / `ixbrl_accounts` / `website_crawl` / `trustpilot` / `google_reviews` / `social` / `stockist` / `trade_body` / `manual` |
| source_url | text | |
| fetched_at | timestamptz | |
| raw | jsonb | full payload (or storage path for large HTML — use Supabase Storage bucket `raw-html`, store path here) |
| content_hash | text | skip re-processing unchanged content |

## 6. Pipeline & decisions

`pipeline_items`: | company_id FK UNIQUE | stage text (`inbox` / `review` / `shortlist` / `watchlist` / `pursue` / `passed`) | owner text | notes text | stage_changed_at timestamptz |

`decisions` (append-only; the learning-loop training data):

| Column | Type | Notes |
|---|---|---|
| company_id | FK | |
| score_id | FK | score visible when the decision was made |
| decision | text | `accept` / `reject` / `watchlist` / `retag` |
| reasons | text[] | structured reason codes (spec 05 §2) |
| free_text | text | |
| decided_by | text | `julia` / `ben` |
| decided_at | timestamptz | |

`watchlist_items`: | company_id FK UNIQUE | reason text | added_at | last_signal_check timestamptz | deprioritise_after timestamptz (added_at + patience config) | status text `watching`/`fired`/`expired` |

## 7. Operational tables

`jobs`: | job_name text | run_key text UNIQUE per (job_name, run_key) | status `running`/`succeeded`/`failed` | started_at | finished_at | stats jsonb | error text | — workers upsert here; cron re-runs with the same run_key no-op if already succeeded.

`app_config`: | key text UNIQUE | value jsonb | description text | — seed: `size_band_thresholds`, `watchlist_patience_months` (24), `scan_cadence`, `launch_sector_taxonomy`.

`taxonomy_rules`: | sector_tag text | sic_codes text[] | include_keywords text[] | exclude_keywords text[] | active bool | — drives sector classification (spec 02 §2).

## 8. Views (for the app)

- `v_shortlist`: companies with latest pass-gate score, joined to signals summary + pipeline stage, ordered by total_score desc.
- `v_company_detail`: everything the profile page needs in one round trip (company + people + latest score with dimensions + active signals + decisions history).
- `v_watchlist`: watchlist items + latest succession signals + days until deprioritise.

## 9. Migration order

1. extensions (`pgcrypto`), helper trigger fn for `updated_at`
2. companies, people, company_people
3. source_records, signals
4. rubric_versions, scores, score_dimensions
5. pipeline_items, decisions, watchlist_items
6. jobs, app_config, taxonomy_rules + seeds
7. views + RLS policies
