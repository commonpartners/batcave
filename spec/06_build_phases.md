# Spec 06 — Build Phases & Acceptance Criteria

Build order preserves the design notes' logic: **screening before sourcing** (the rubric is the risky part; test it on hand-picked companies first). Every phase ends with something Julia and Ben use that week.

## Phase 0 — Manual proof (1–2 weeks) — *tooling support, not just a spreadsheet*

**Improvement over design notes** (which said "score in a spreadsheet"): hand-pulling CH data for 30 companies is hours of drudgery the connectors can already do. Build the thin slice first and let Phase 0 exercise it:

Scope: repo scaffold, Supabase project + migrations (spec 01), CH client (spec 02 §1), intake CLI (spec 02 §7), and `cli.py export-phase0 --file out.xlsx` — for an intake list of ~30 skincare/personal-care companies, pull CH profile/officers/PSC/accounts, compute the succession signals, and export one row per company with all rubric dimensions as empty columns for Julia + Ben to hand-score.

**Acceptance:** given a CSV of 30 company names/numbers, one command produces a spreadsheet with CH facts + computed director ages/tenures + succession signal values; data spot-checked correct against the CH website for 5 companies; Julia and Ben have scored it and the rubric ranking argument has happened (weights confirmed or adjusted → seed rubric v1.0.0 accordingly).

## Phase 1 — Screening MVP (3–5 weeks)

Scope: enrichment pipeline (spec 03), scoring engine (spec 04), review app pages `/`, `/company/[number]`, `/held`, decision dialog (spec 05 §1–2), manual intake in-app. Ingestion still manual (paste/CSV). GitHub Actions: enrich + score weekly over whatever is in the DB.

**Acceptance:**
- Paste 20 company numbers → within one enrich+score run, ranked, explainable shortlist in the app.
- Every score drills down to rationale + evidence with working source links.
- Gate holds appear in `/held` with the failing test named; estimates always badged.
- Decisions persist with reason codes, referencing the visible score_id.
- Unit tests green: gate logic, size-band computation, digital-maturity rubric, succession signals, latent-upside formula (each with edge-case fixtures: missing DOB, no website, micro accounts, dissolved company).
- Playwright smoke suite green. LLM scoring is schema-valid on 20 real companies with zero fabricated dimensions.

## Phase 2 — Sourcing engine (4–6 weeks)

Scope: bulk-data universe build + taxonomy classification (spec 02 §2–3), streaming/dirty-flag change detection, full signal computation on the universe, watchlist (spec 02 §5 + `/watchlist` page), scheduled loop end-to-end, `/admin` runs view.

**Acceptance:**
- Universe built from bulk snapshot: count of active UK skincare/personal-care candidates known and plausible (sanity: hundreds–low thousands, not 10 or 100k — investigate if outside).
- Weekly loop runs unattended: scan → signals → enrich (budget-capped) → score → watchlist check, with `jobs` stats visible in admin; an individual company failure never kills a run.
- A simulated director-termination event on a watchlist company fires it into `inbox` within one cycle.
- New qualifiers appear in the app flagged "new since last visit". CH rate limits never breached (client-enforced).

## Phase 2.5 — Signal-source scrapers (rolling)

One module per trade-body/awards/stockist source (spec 02 §8), added incrementally. Acceptance per source: names resolved to company numbers ≥ 80% precision on a sample of 20; membership/stockist evidence visible on company pages.

## Phase 3 — Scale & learn (ongoing)

Scope: learning-loop Stage 1 panel then Stage 2 assisted retune (spec 05 §3), calibration audit (spec 04 §4), second sub-sector (supplements/nutrition: new taxonomy rules + benchmark ratios — architecture must require **no code changes**, only config/seed rows), Beauhurst trial integration as a new connector *only when* a specific data gap is documented.

**Acceptance:** adding a sub-sector = migration seed only; learning panel shows accepted-vs-rejected dimension deltas; first assisted-retune proposal generated after 50 decisions with reorder diff.

## Deferred (do not build)

Outreach/CRM, contact scraping, email sequences — revisit before any owner contact (GDPR/PECR review first). Ireland. Any auto-activation of rubric changes.

## Suggested Claude Code session breakdown

1. Scaffold: repo, Supabase migrations, CI, fixtures.
2. CH client + intake + Phase 0 export (ship Phase 0).
3. Enrichment: website + webtech + reviews (+ tests).
4. Scoring: gate + rules dimensions (+ exhaustive tests).
5. LLM scoring + prompts + calibration baseline.
6. App: shortlist + company page + decisions.
7. App: held/watchlist/admin + Playwright.
8. Sourcing: bulk universe + taxonomy + scheduling.
9. Signals at scale + watchlist loop.
10. Learning panel + polish.

Keep sessions ≤ half a day of scope; land tests with the code they cover; every session ends with migrations applied and CI green.
