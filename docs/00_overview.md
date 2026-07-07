# Common Partners Platform — Engineering Spec (v1.0)

**For:** Claude Code (Sonnet 5). Read this file first, then specs 01–06 in order. Together they fully specify the build.

**Sources of truth:** These specs derive from `01_sourcing_design.md`, `02_scoring_design.md`, `03_architecture_and_build_plan.md`, and `Common_Partners_Platform_Blueprint.docx` (all v0.1, 8 Jul 2026) in the repo root's parent folder. Where a spec conflicts with those notes, the spec wins — it is the later, more precise document.

---

## 1. What this is

A deal-origination platform for Common Partners (Julia — tech/product; Ben — brand/marketing/growth), a two-person firm buying established, profitable UK consumer businesses (£1–10m EBITDA thesis; practical firepower today ≈ £5m EV) where the owner is stepping back and there is latent digital/marketing upside.

Two connected engines over one Postgres database:

1. **Sourcing engine** — scheduled scanners over Companies House + signal sources that discover candidate companies, compute succession / latent-upside / consolidation signals, and keep a watchlist.
2. **Screening engine** — enriches each candidate into a structured profile, runs a fit gate (pass/hold/fail), scores 0–100 against a weighted rubric (deterministic rules + LLM for judgement calls), tags value-creation angles, and surfaces a ranked shortlist in a web app where Julia and Ben record decisions. Decisions feed a learning loop that re-tunes the rubric.

**Launch scope:** independent UK skincare & natural/personal-care brands. Supplements/nutrition is wave two. UK only (Ireland later). Outreach/CRM is explicitly **out of scope** (deferred; GDPR/PECR not a live constraint until owner contact).

## 2. Stack (decided — do not substitute)

| Layer | Choice | Notes |
|---|---|---|
| Database + auth | Supabase (managed Postgres) | Single source of truth. RLS on from day one (two users, simple policy). |
| Web app | Next.js (App Router, TypeScript) on Vercel | Review UI over the DB via Supabase JS client. |
| Workers | Python 3.12 (`workers/` package) | Scraping, iXBRL parsing, Companies House connectors, enrichment, scoring runs. |
| Job scheduling | GitHub Actions cron workflows invoking worker CLI commands | No queue infra. Postgres `jobs` table provides idempotency + run logs. |
| LLM | Claude via Anthropic API (`claude-sonnet-4-5` or newer) | Versioned prompts in `workers/prompts/`; prompt hash stored on every score. |
| Secrets | GitHub Actions secrets + Vercel env vars + `.env` locally | `COMPANIES_HOUSE_API_KEY`, `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`. |

## 3. Repo layout (monorepo)

```
common-partners-platform/
├── app/                    # Next.js app (spec 05)
├── workers/                # Python package (specs 02–04)
│   ├── cp_workers/
│   │   ├── connectors/     # companies_house.py, web.py, reviews.py, ...
│   │   ├── enrichment/
│   │   ├── signals/
│   │   ├── scoring/
│   │   └── cli.py          # single entry point: python -m cp_workers.cli <command>
│   ├── prompts/            # versioned LLM prompts (markdown, front-matter with version)
│   └── tests/
├── supabase/
│   └── migrations/         # SQL migrations (spec 01)
├── .github/workflows/      # cron workflows (spec 02 §6)
└── docs/                   # these specs, copied in
```

## 4. Cross-cutting conventions

- **Provenance everywhere.** Every fact written to the DB traces to a `source_records` row (source, URL/endpoint, fetched_at, raw payload). No orphan facts.
- **Idempotent jobs.** Every worker command can be re-run safely; upsert by natural key (company number, etc.); record runs in `jobs`.
- **Deterministic vs LLM.** Anything computable from structured data (ages, tenures, size bands, counts, gate logic) is rules code with unit tests. LLM is used only for: sector classification beyond SIC, extraction from messy pages, the four qualitative scoring dimensions, one-line company summaries. Never let the LLM do arithmetic or gate logic.
- **Explainability.** Every signal, gate result, and dimension score stores its evidence (JSON) and a one-line rationale. The UI must be able to answer "why is this ranked here?" for every company.
- **Config, not constants.** Rubric weights, size-band thresholds, watchlist patience, scan cadence live in DB config (`rubric_versions`, `app_config`) — all flagged as tunable pending Ben's input.
- **Rate limits.** Companies House: 600 requests / 5 minutes — build a shared throttled client. Polite scraping: respect robots.txt, identify with a UA string, per-domain delay ≥ 2s, never bypass blocks.
- **Money/size figures** stored in GBP integer pence where exact, or as banded enums where estimated; every estimate carries a `confidence` field.
- **Testing.** pytest for workers (signals and gate logic must have exhaustive unit tests — they are the edge); Playwright smoke tests for the app's critical paths (list renders, decision saves).

## 5. Open business decisions (build must not block on these)

Encode as config with these defaults; surface prominently in the UI as "provisional":

1. **Rubric weights** (spec 04 §3) — defaults as specified; Ben to confirm.
2. **Size band** — default: fit-now ≤ £5m EV; stretch flag for £5m EV–£10m EBITDA-implied. Both thresholds in `app_config`.
3. **Watchlist patience** — default 24 months of monitoring before auto-deprioritise; in `app_config`.

## 6. Read order for the remaining specs

01 data model → 02 sourcing → 03 enrichment → 04 scoring → 05 app & learning loop → 06 build phases (the order to actually build in — **Phase 1 screening MVP first, sourcing second**) → 07 changelog of deliberate improvements over the v0.1 design notes (read before assuming the notes and specs agree) → 08 day-one runbook (accounts, keys, first-run sequence, weekly-loop enablement).
