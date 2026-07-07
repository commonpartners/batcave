# Spec 08 — Day-One Runbook

Everything needed to go from zero to a scored shortlist today, and to a self-refreshing weekly loop this week. All accounts below have free tiers adequate for launch.

## 1. Accounts & keys (≈ 30 minutes, all self-serve)

| What | Where | Notes |
|---|---|---|
| Companies House API key | developer.company-information.service.gov.uk | Free, instant. Create a "live" REST key. |
| Supabase project | supabase.com | Free tier fine. Note URL + service-role key. |
| Anthropic API key | console.anthropic.com | Budget guardrail is in config; expect single-digit £/week at launch volume. |
| GitHub repo | github.com | Private repo; Actions included free tier is ample. |
| Vercel | vercel.com | Import the repo; set env vars. |
| Resend (digest email) | resend.com | Free tier; or any SMTP. Optional day one. |
| Google Places API | console.cloud.google.com | Optional — Google reviews. Skip day one. |

Env vars everywhere (Actions secrets, Vercel, local `.env`): `COMPANIES_HOUSE_API_KEY`, `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `RESEND_API_KEY` (optional).

## 2. Day-one sequence

1. **Scaffold + migrate:** apply `supabase/migrations/` (Supabase MCP or `supabase db push`). Seeds create rubric v1.0.0, taxonomy rules, config defaults.
2. **Seed intake:** build `seed.csv` — start with the Phase 0 list of ~30 skincare/personal-care companies (names or company numbers). `python -m cp_workers.cli intake --file seed.csv`. Unresolved names are reported, not guessed.
3. **First pull:** `cli.py refresh` (CH detail for the 30) → `cli.py compute-signals`.
4. **Enrich + score:** `cli.py enrich --pending` then `cli.py score --pending`. Expect a handful of `needs-review` website matches and `held` companies — that's the system being honest, not broken.
5. **Open the app:** deploy `app/` to Vercel (or `npm run dev` locally), log in, review the ranked list, record first decisions.
6. **Turn on the loop:** enable the six Actions workflows (spec 02 §6). Confirm next Monday's digest email arrives.

## 3. First-week milestones

- Day 1: 30 companies scored, first decisions recorded.
- Day 2–3: run `cli.py discover` once manually — the bulk snapshot builds the full universe (expect hundreds–low thousands of candidates; investigate if wildly off).
- Day 4–5: enrich/score the top of the universe within the LLM budget; pick the 10-company calibration benchmark set (spec 04 §4).
- Monday: first unattended weekly cycle + digest.

## 4. How you know it's working (and when it isn't)

- **Heartbeat:** Monday digest email = loop ran. No email = check `/admin` runs view.
- **Job failures alert by email** (spec 02 §6). Individual company failures accumulate in run stats and `enrichment-blocked` surfaces in `/held` after 3 strikes.
- **Honesty over coverage:** missing reviews/social/website are marked missing and lower `data_completeness` — they never block scoring or get invented.
- **Rate limits cannot be breached** — the throttled CH client enforces 600/5min by construction; scraping is per-domain throttled and robots-respecting.

## 5. Weekly rhythm (steady state)

Mon: automated cycle + digest → Julia/Ben review new qualifiers + watchlist fires in the app (15–30 min each) → decisions accumulate → quarterly: look at `/admin/learning`, consider an assisted retune (after ≥ 50 decisions).
