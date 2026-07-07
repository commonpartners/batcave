# Spec 05 — Review App & Learning Loop

Next.js (App Router, TS, Tailwind + shadcn/ui) on Vercel. Supabase auth (email magic link; only julia@ / ben@ allowlisted). Data via Supabase client against the views in spec 01 §8. Two users — optimise for speed of judgement, not admin features.

## 1. Pages

### `/` — Ranked shortlist
- Table over `v_shortlist`: rank, name, score, top-2 dimension chips, value-angle tags, red-flag badges, signals sparkline, stage.
- Filters: stage, sector tag, size band, red-flag presence, "new since last visit".
- Default sort: score desc; secondary sorts: newest, succession strength.
- Row click → company page. Keyboard: j/k navigate, enter open — reviews happen in bulk, make it fast.

### `/company/[number]` — Profile (the core screen)
Single `v_company_detail` fetch. Layout:
- **Header:** name, score (big), gate result, lifecycle, value angles, red flags (each flag click-through to its evidence).
- **Why this rank:** dimension bars (raw 0–5 × weight) each expandable to rationale + evidence quotes with source links. This screen must fully answer "why is this here?" — the explainability requirement is UI-level, not just DB-level.
- **Signals timeline:** succession/upside/consolidation events over time (a director termination shows as a dated event).
- **Facts panel:** financials (estimates badged with confidence + method — never presented as filed facts), people (ages banded, tenure), digital-maturity breakdown, reviews, stockists, links out (CH, website, Trustpilot).
- **Decision bar (sticky):** Accept → pursue · Reject · Watchlist · Retag — each opens the decision dialog (§4).
- **Notes:** free-text per company, author + timestamp.

### `/watchlist`
`v_watchlist`: reason parked, succession status, days to deprioritise, "fired" items pinned top with what fired. Actions: extend, promote to review, archive.

### `/held`
Gate-hold queue grouped by failing test (unknown size, needs-review sector, outside footprint...). Actions: override gate (recorded as manual decision), fix data (e.g. set website manually → triggers re-enrich), reject.

### `/admin`
- Rubric: view active weights/thresholds; propose new version (edits create a draft `rubric_versions` row; activating prompts optional `--rescore-all`). Show "provisional — pending Ben" banner until first manual confirmation (config flag).
- Config: size band, watchlist patience, cadence, LLM budget.
- Runs: `jobs` table view — last scan/enrich/score stats, failures, calibration-audit results.
- Intake: paste names/numbers box → intake code path (spec 02 §7).

## 2. Decision dialog (§the training data — get this right)

On Accept/Reject/Watchlist/Retag:
- Required: ≥ 1 **reason code** (multi-select) + optional free text.
- Reason codes (seed list, editable in admin): `brand_stronger_than_score` / `brand_weaker_than_score`, `too_small` / `too_big`, `digital_gap_smaller_than_it_looks`, `sector_wrong`, `owner_unlikely_to_sell`, `financials_concerning`, `love_the_heritage_angle`, `competition_for_deal`, `gut_feel` (allowed, but tracked).
- Writes `decisions` row referencing the exact `score_id` visible at decision time — the pairing of *what the system believed* and *what the human chose* is the training datum.

## 3. Learning loop (improvement — the design notes hand-wave "weights re-tune themselves")

Auto-retuning weights on a two-person firm's decision volume would overfit noise. Replace with a staged, honest design:

- **Stage 1 (launch → ~50 decisions): measure, don't move.** A `/admin/learning` panel shows, per dimension: mean dimension score among accepted vs rejected companies, and reason-code frequencies. This makes disagreement between rubric and taste *visible* without touching weights.
- **Stage 2 (≥ 50 decisions): assisted retune.** Quarterly job fits a simple logistic regression (accept/reject ~ dimension scores) and **proposes** a new weight vector as a draft rubric version, with a side-by-side "how would the current shortlist reorder?" diff. Julia/Ben approve or discard. Never auto-activate.
- **Stage 3 (later, optional):** per-dimension threshold tuning and prompt-anchor adjustments driven by reason codes (e.g. frequent `brand_weaker_than_score` → tighten brand-equity anchors).

All rubric changes are versioned; old scores are never rewritten — re-scoring under a new rubric creates new `scores` rows, and the company page can show score history across versions.

## 4. Non-functional

- Mobile-usable (Ben will review on a phone): shortlist + company page responsive; decision bar thumb-reachable.
- Empty/error states designed: no scores yet, enrichment partial (`scoring-incomplete` badge), estimate-only financials.
- No public access; Vercel deployment protected + Supabase RLS as backstop.
- Playwright smoke tests: login, shortlist renders with seeded fixture data, open company, record decision, decision appears in history.
