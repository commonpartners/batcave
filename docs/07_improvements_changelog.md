# Spec 07 — Improvements Over the v0.1 Design Notes

Deviations from the Opus 4.8 blueprint, so nothing changes silently. Each is my recommendation; all are reversible.

## Substantive design changes

1. **Bulk data + streaming instead of API pagination** (spec 02 §3). The notes assumed scanning via the CH REST API. That API is rate-limited to 600 req/5 min — a universe crawl would take days and burn quota needed for enrichment. The free monthly bulk snapshot builds the universe locally in an hour; the CH Streaming API gives event-driven change detection instead of weekly full re-fetch diffs. REST is kept for per-company detail only. Fallback to the original approach is specified if streaming is unreliable.

2. **Latent-digital-upside moved from LLM to a deterministic formula** (spec 04 §3). The notes classed "how big is the marketing gap" as an LLM judgement, but its inputs (review strength, digital maturity, distribution breadth) are already computed deterministically. A formula is consistent, free, unit-testable, and directly tunable by Ben. The LLM keeps only what rules truly can't do: brand equity, team continuity, differentiation.

3. **Honest learning loop** (spec 05 §3). "Decisions re-tune weights and thresholds" would overfit badly at two-people decision volume. Replaced with: measure-only panel (< 50 decisions) → assisted retune that *proposes* a versioned weight change with a shortlist-reorder diff (≥ 50 decisions) → human approval always. Never auto-activate.

4. **Anchored LLM scoring + calibration audit** (spec 04 §3–4). Unanchored 0–5 LLM scores drift across prompts/model versions. Added concrete per-integer anchors, few-shot examples, temperature 0, strict schemas — plus a monthly re-score of a fixed 10-company benchmark set that alerts on > 1-point drift. Without this, a model update could silently reorder the whole pipeline.

5. **Red flags cap pipeline stage, not score** (spec 04 §5). The notes said flags "auto de-prioritise". Mixing flags into the number hides them and breaks score comparability. Instead the score stays clean and a flag blocks shortlist entry until a human acknowledges it — the flag stays visible forever.

6. **Cost-ordered scoring + LLM budget caps** (spec 04 §1, 03 §8). Free checks run first; LLM only for gate-passers; per-run call budget. Matters once the sourcing engine scales the universe to thousands.

7. **Phase 0 gets tooling** (spec 06). "Hand-pull 30 companies into a spreadsheet" is hours of drudgery that also tests nothing. A thin CLI slice (CH connectors + succession signals + Excel export) makes Phase 0 faster *and* validates the riskiest data plumbing before Phase 1 commits to it.

8. **Review trend as an automatic decline detector** (spec 03 §3). Storing review count/rating over successive fetches turns the `structural_decline` red flag from a manual judgement into a computed one.

9. **"Hold" is a worked queue** (spec 04 §2, 05 §1). The notes defined hold but no workflow. Added `/held` grouped by failing test, with fix-data and override actions — otherwise holds become a silent graveyard, and unknown-size companies (the small/micro filers hiding their P&L, i.e. much of the dark end of the market) would never resurface.

10. **Website resolution validated by registered-number match** (spec 03 §1). Matching a company to the right website is the most error-prone enrichment step. UK companies must display their registered number; footer regex match against CH gives near-certain validation, with `needs-review` rather than guessing below threshold.

## Smaller notes

- Decision reason codes (spec 05 §2) so learning-loop data is structured, not just accept/reject bits; `gut_feel` allowed but tracked.
- Estimates always badged with method + confidence in the UI; never rendered as filed facts.
- Rubric changes are immutable versions; historical scores never rewritten.
- Store director birth month/year only — deliberate data minimisation ahead of any future GDPR posture.
- GitHub Actions cron + Postgres `jobs` table instead of a queue/scheduler service — right-sized for a two-person team; swap later if runs outgrow it.

## Round 2 (v1.1) — reliability & run-it-today hardening

11. **Streaming API dropped from the critical path** (spec 02 §3). Quota math shows a ~2,000-company universe refreshes via plain REST in ~70 minutes weekly — no streaming consumer, no daemon, nothing to babysit. Deferred to Phase 3 if the universe grows ~5×.

12. **Name-keyword scan of the full bulk snapshot** (spec 02 §3a). Many DTC skincare brands register under generic retail SICs (esp. 47910 online retail) and would be invisible to SIC-seeded discovery. Scanning all ~5m company names locally is free and closes the biggest coverage hole in the original design.

13. **Employee counts from small-company accounts** (spec 02 §1). Average headcount must be disclosed even in filleted accounts — the best free size proxy for exactly the companies that hide their P&L.

14. **Scraping made survivable:** Trustpilot via server-rendered JSON-LD not DOM scraping; Playwright fallback only when static fetch returns a JS shell; content-hash skip-unchanged; tenacity retries; 3-strikes → human queue (specs 03 §1, §3, §8). Weekly refresh cost approaches zero when nothing changed.

15. **LLM score cache** keyed (profile_hash, prompt_hash, rubric_version) (spec 04 §3, 01 §4) — re-scores are free and byte-identical unless the profile actually changed.

16. **`data_completeness` on every score** (spec 04 §3) — a 78 on thin data is visibly not a 78 on a full profile.

17. **Weekly digest email + failure alerts** (spec 02 §6) — the heartbeat. For a two-person team, a silently dead pipeline is the failure mode that kills the whole idea; email is the channel they already check.

18. **Day-one runbook** (spec 08) — accounts, keys, exact command sequence from zero to scored shortlist in one day, weekly-loop enablement, and "how you know it's working".

## Unchanged on purpose

Launch sub-sector, the two-engine structure, the fit-gate tests, the seven dimensions and their weights, value-creation angles, screening-before-sourcing build order, bootstrap-before-Beauhurst, outreach deferred — the blueprint's core judgements are sound and are carried through as-is.
