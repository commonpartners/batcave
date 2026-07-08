# Spec 09 — Wide Funnel & Pre-Gate (v1.0)

**Why this exists (decision, 8 Jul 2026):** the universe is widening from ~2,000 launch-sub-sector companies to **tens of thousands across health, wellness and beauty**. Enrichment (crawling, reviews, LLM extraction/scoring) costs compute, time and money per company — it must never run over the whole universe. Everything before enrichment must use **free data only** (CH bulk snapshot + CH REST, both £0), and a **pre-gate** decides which companies earn enrichment. The DB holds everyone; money is spent on a ranked few.

## 1. The funnel (cost-tiered)

| Tier | Data | Cost | Volume |
|---|---|---|---|
| T0 Discover | Bulk snapshot fields (name, SICs, status, age, accounts category) | £0, no API quota | tens of thousands |
| T1 Detail | CH REST: officers, PSC, filing history, iXBRL accounts | £0, rate-limited | thousands/week (throttled backfill) |
| T2 Pre-gate | Signals computed from T1 — **no scraping, no LLM** | £0 | all with T1 data |
| T3 Enrich + score | Web, reviews, social, LLM | ££ | **top-K per week by pre-gate score** (config) |

Lifecycle unchanged; the pre-gate is a score on `companies` (`pregate_score`, `pregate_detail`), not a new stage — nothing is thrown away, everything can be re-ranked as config changes.

## 2. Widened discovery (T0)

Taxonomy grows from `skincare-personal-care` to all H/W/B: add `supplements-nutrition`, `haircare-beauty`, `wellness-services`, `personal-care-manufacturing` rows in `taxonomy_rules` (SIC seeds + keywords per row, same mechanism). Name-keyword scan of the full snapshot stays (catches generic-SIC DTC brands). Expected result: 20k–60k `discovered` companies. That's fine — rows are cheap.

## 3. Detail backfill (T1) — the rate-limit budget is the constraint

~4 REST calls/company; 600/5min ⇒ ~7,200 calls/hour ⇒ ~1,800 companies per 6h Actions job. So:

- `refresh --new --max-companies N` (default 1,800): fetch detail for discovered companies with no officer data yet, **ordered by T0 priority** — sector-keyword match strength, then company age. Runs nightly until backlog clears (a 40k backlog clears in ~3 weeks).
- `refresh --hot`: weekly, companies with `pregate_score ≥ hot threshold` OR on watchlist/pipeline — the ones where a new filing changes decisions.
- `refresh --shard <0-3>`: monthly cold-tail refresh, universe sharded 4 ways by company-number hash, one shard per week.

## 4. The pre-gate score (T2) — free data only, deliberately proprietary

`pregate_score` ∈ 0–1 = weighted blend (weights in `app_config.pregate_weights`, tunable without code):

| Component | Weight | From (all free) |
|---|---|---|
| Succession readiness | **0.40** | max of the three succession signals (director age curve, tenure, board/PSC events) |
| Size fit | 0.25 | `size_band` from iXBRL balance sheet + employee count: fit-now 1.0 · stretch 0.6 · unknown 0.5 · too-small/too-large 0.0 |
| Sector confidence | 0.20 | taxonomy/classifier confidence (rules 1.0 · llm ≥0.7 · needs-review 0.4) |
| Foundations | 0.15 | age ≥ min, active, net assets > 0, no insolvency events |

Succession dominates on purpose: **ranking the enrichment queue by seller-readiness computed from free director data is the proprietary move** — anyone can filter by SIC and size; almost nobody spends their enrichment budget in succession order. `pregate_detail` stores per-component values + evidence so the `/held`-style admin view can answer "why wasn't this enriched yet?".

## 5. Budgeted promotion (T3)

`enrich --pending` no longer means "everything discovered". Selection each run:

1. Companies with `pregate_score ≥ pregate_threshold` (config, default 0.45), not yet enriched or past freshness windows,
2. ordered by `pregate_score` desc,
3. capped at `enrichment_budget_per_week` (config, default 150) and the existing `llm_budget_per_run`.

Below-threshold companies stay in the DB, get refreshed on the cold cadence, and are promoted the week a succession event moves their score — the watchlist principle applied to the whole universe.

## 6. Implementation map

- Migration `0011_pregate.sql`: `companies.pregate_score numeric`, `companies.pregate_detail jsonb`, index on score desc; `app_config` seeds `pregate_weights`, `pregate_threshold`, `enrichment_budget_per_week`, `calibration_benchmark` (list, empty until Phase 0 picks it); new H/W/B `taxonomy_rules` rows.
- `cp_workers/scoring/pregate.py`: pure `compute_pregate(company, succession_values) -> (score, detail)` + `run_pregate()` persistence.
- `cp_workers/signals/compute.py`: persists succession + consolidation signals from DB people/event rows (this was the missing integration piece).
- `cli.py`: `pregate` command; `refresh` tiering flags; `enrich --pending` budget selection.
- Workflows: nightly `backfill.yml` (`refresh --new`); `refresh.yml` gains `pregate` step.

Weekly cost at steady state: enrichment for ≤ 150 companies + LLM scoring for gate-passers only — bounded regardless of universe size.
