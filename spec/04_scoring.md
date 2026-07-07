# Spec 04 — Scoring Engine

`cli.py score --pending` / `--company <number>` / `--rescore-all --rubric <version>`. Pipeline per company: **gate → deterministic dimensions → LLM dimensions → red flags → value angles → persist**. Every run stamped with `rubric_version` + prompt hashes so any historical score is reproducible.

## 1. Ordering principle (improvement over design notes)

The notes ran gate → rules → LLM. Keep that, and make it **cost-ordered**: gate and rules dimensions are free; LLM dimensions run only for gate-passers, and red-flag detection runs before LLM scoring so flagged companies can short-circuit to `hold` without spending LLM calls. At scale this cuts LLM spend ~60–80%.

## 2. Fit gate (pure rules, `scoring/gate.py`)

Each test returns `pass` / `hold` / `fail` + reason. Overall: any fail → fail; else any hold → hold; else pass. All thresholds from `rubric_versions.gate_config`.

| Test | Pass | Hold | Fail |
|---|---|---|---|
| Sector | sector_tag in launch/adjacent H/W/B set | tag `needs-review` | software / non-consumer |
| Product type | physical product or service (from enrichment) | ambiguous | primarily tech product |
| Size | size_band `fit-now` | `stretch` or `too-large` or `unknown` | `too-small` |
| Foundations | age ≥ min, active, net assets > 0 or plausibly profitable | thin data | pre-revenue / insolvency events / negative net assets + shrinking |
| Situation | succession signal ≥ 0.3, or approachable (no recent funding round) | freshly-funded scaling founder | — (situation never hard-fails; worst case hold) |
| Geography | UK | outside UK footprint | — |

`size_band` computation: prefer actual/estimated EBITDA vs thresholds; fall back to revenue estimate → EBITDA via sector margin; fall back to balance-sheet + employee heuristic; if all missing → `unknown` (hold, prompts manual look — **never silently drop for missing data**).

**Hold is a queue, not a verdict:** hold companies appear in the app under "Held — needs a human look" with the failing test named.

## 3. Attractiveness dimensions (0–5 each → weighted 0–100)

Weights = rubric v1.0.0 seed (Ben to confirm; changing weights = new rubric version, never edit in place):

| Dimension | Weight | Method |
|---|---|---|
| brand_customer_equity | 25 | LLM |
| latent_digital_upside | 20 | **Rules** (see below) |
| financial_quality | 20 | Rules |
| deal_accessibility | 10 | Rules |
| team_continuity | 10 | LLM |
| market_consolidation | 10 | Rules |
| differentiation | 5 | LLM |

**Improvement:** the design notes put "how big is the marketing gap" in the LLM bucket. It shouldn't be — we already compute `review_strength` and `digital_maturity` deterministically, so **latent_digital_upside = f(review_strength, digital_maturity, distribution_breadth)**, a tested formula: `5 × review_strength × (1 − (digital_maturity − 1)/4)`, +0.5 bonus if distribution_breadth < 0.3, capped at 5. Cheaper, consistent, and directly tunable. The LLM handles only what rules can't: is the brand *genuinely* loved (equity), team continuity, differentiation.

Rules dimensions:
- **financial_quality:** from balance sheet + estimates — net-asset trend, cash position, creditor ratio, estimate confidence discount (score capped at 3 when confidence low).
- **deal_accessibility:** direct mapping of succession-family signal values + unadvised proxy (no broker/advisor mention on site/filings).
- **market_consolidation:** from `fragmented_subcategory` + `adjacency` signals.

LLM dimensions (`prompts/score_qualitative.md`, one call per company covering all three):
- Input: the assembled profile (structured JSON + extracted website text + review summary).
- Output (strict JSON, pydantic-validated): per dimension `{score_0_to_5, rationale_one_line, evidence: [quotes/facts]}`.
- **Anchored rubric (improvement):** the prompt defines every integer score per dimension with concrete anchors (e.g. brand equity 5 = "≥ 4.5 stars across ≥ 500 reviews plus organic press/awards"; 2 = "decent product, no evidence anyone would miss it") and includes 3 worked few-shot examples. Unanchored 0–5 asks drift badly.
- Temperature 0. Retry once on schema failure; two failures → dimension `null`, company flagged `scoring-incomplete`, never fabricated.
- **Score cache (repeatability + cost):** before calling the LLM, compute `profile_hash` = hash of the exact profile JSON sent. If a `scores` row exists with the same `(profile_hash, prompt_hash, rubric_version)`, reuse it — no call. Weekly re-scores of unchanged companies are free and byte-identical; only genuinely changed profiles hit the API. This, plus §1 cost-ordering, is what makes the weekly loop cheap enough to run forever.
- **Data completeness:** every score stores `data_completeness` 0–1 (fraction of profile fields populated, weighted toward fields the rubric uses). The UI shows it next to the score; a 78 on thin data is not the same as a 78 on a full profile, and the shortlist can be sorted/filtered on it.

## 4. Calibration audit (new — not in design notes)

Monthly job `score --calibration-audit`: re-score a fixed benchmark set of 10 companies (chosen in Phase 0, never changed) with the active rubric. Alert if any LLM dimension moves > 1 point vs the stored baseline — catches prompt/model drift before it silently reorders the pipeline. Store results in `jobs.stats`.

## 5. Red flags (rules where possible, LLM assist where not)

| Flag | Detection |
|---|---|
| tech_product_dependency | LLM extraction: core value is software |
| structural_decline | Rules: review trend negative AND (net assets shrinking OR employee count falling) |
| customer_channel_concentration | Rules-assisted: single stockist/marketplace dominates distribution evidence; else LLM from website text |
| regulatory_exposure | LLM: unresolved health/cosmetic claims (keyword pre-filter: "clinically proven", "cures", medical claims) |
| owner_not_willing | Manual only — set from the app, never inferred |
| total_owner_dependency | LLM: founder-is-the-brand with no team evidence |

Effect: any red flag caps pipeline placement (cannot enter `shortlist` without a human explicitly acknowledging the flag) — flags **don't** alter the numeric score, so the score stays comparable and the flag stays visible.

## 6. Value-creation angles (max 2 per company)

Assigned by rules from signals/dimensions, LLM tie-breaks when > 2 qualify:

| Angle | Trigger |
|---|---|
| digitise | latent_digital_upside ≥ 4 and digital_maturity ≤ 2 |
| performance_market | review_strength high, no ad pixels, e-commerce exists |
| rollup_buy_and_build | fragmented_subcategory ≥ 0.6 |
| succession_continuity | succession signals ≥ 0.5 and team evidence present |
| distribution_expansion | narrow_distribution ≥ 0.6 |

## 7. Outputs

Persist `scores` + `score_dimensions` rows; update company lifecycle → `scored`; gate-passers with score ≥ shortlist threshold (config, default 60) create/refresh `pipeline_items` at `inbox`.
