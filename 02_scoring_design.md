# Common Partners — Scoring & Profiling Engine (design note)

*Draft for discussion — v0.1, 8 July 2026. Item 3: how we rank and profile the companies sourcing finds.*

## The core idea
Two layers, both deliberately explicit so the ranking is defensible and improves over time:
1. **Fit gate** — is this even in Common Partners' box? (pass / hold / fail)
2. **Attractiveness score** — for those that pass, how good is it and why? (0–100, weighted)

Plus **profiling**: each shortlisted company is tagged with the value-creation play(s) that fit — that's what turns a score into a plan. Nothing is a black box: every score carries its evidence and a one-line rationale, and the rubric re-tunes itself from the deals you actually pursue.

---

## 1. The company profile (captured on every target)
| Group | Fields |
|---|---|
| Identity | Legal + trading name(s), company number, incorporation date, website, region, SIC + our sector tag |
| Financial proxy | Filing category, latest balance-sheet figures, employee count, size band, 3rd-party revenue/EBITDA estimate, confidence flag |
| Ownership | Directors (age band, tenure), PSCs, ownership concentration, recent board/PSC events |
| Brand & demand | Review volume + rating across sources, social following/engagement, notable stockists, awards/press |
| Digital maturity | E-commerce? email capture? analytics/ad pixels? content cadence? → 1–5 read |
| Signals | Succession, latent-upside, consolidation scores (from sourcing note §3) + evidence |
| Scores & tags | Fit result, attractiveness score, value-creation angle(s), red flags, notes, pipeline stage |

## 2. The fit gate (pass / hold / fail)
A fundamental miss stops a company regardless of how attractive it looks — it's a gate, not a weighting.

| Test | Pass | Fail / hold |
|---|---|---|
| Sector | Consumer, ideally skincare/personal-care (launch sub-sector) or adjacent H/W/B | Software/non-consumer → fail |
| Product type | Physical product or service | Primarily a tech product → fail |
| Size | Within firepower (fit now ≤ ~£5m EV; stretch toward £1–10m EBITDA thesis) | Far too large → hold; too small to matter → fail |
| Foundations | Established, plausibly profitable, real trading history | Pre-revenue / structural loss / turnaround → fail |
| Situation | Evidence of or openness to succession / step-back, or approachable | Freshly-funded scaling founder, no transition → hold |
| Geography | UK | Outside footprint → hold |

## 3. The attractiveness score (0–100, weighted)
Each dimension scored 0–5 from defined evidence, then weighted. **Weights are a starting point — to be argued over with Ben, then tuned by the learning loop.**

| Dimension | Weight | A "5" looks like | Evidence |
|---|---|---|---|
| Brand & customer equity | **25%** | Visibly loved — high review volume + rating, repeat/recommend, real recognition | Reviews, social, press, awards |
| Latent digital / marketing upside | **20%** | Strong product, weak digital — a big, closable gap | Web-tech, social, e-comm maturity |
| Financial quality | **20%** | Healthy margins, steady/growing, clean balance sheet, no customer concentration | Accounts, estimates |
| Deal accessibility & seller readiness | **10%** | Clear succession window, owner likely willing, off-market, unadvised | Director age/tenure, PSC events |
| Team & continuity | **10%** | Capable team likely to stay; not wholly owner-dependent | Companies House, LinkedIn, site |
| Market & consolidation potential | **10%** | Fragmented category, roll-up / adjacency headroom | Sector map, universe density |
| Differentiation / durability | **5%** | Science-led, IP, or genuine positioning — not me-too | Website, product, press |

**Why this shape:** brand equity + the digital gap dominate because they're exactly what CP buys and what you and Ben add. Financial quality is a heavy floor. Accessibility and team matter but are secondary; differentiation is a tie-breaker that guards against undifferentiated wellness brands (which the market is already filtering out).

## 4. Red flags (auto de-prioritise / force manual call)
- **Tech-product dependency** — value hinges on software the team can't sustain
- **Structural decline** — falling reviews/demand, shrinking category
- **Customer / channel concentration** — one retailer or platform is most of the business
- **Regulatory exposure** — unresolved cosmetic/health-claim or compliance risk
- **Owner not actually willing** — no real transition despite surface signals
- **Total owner-dependency** — nothing survives the founder leaving

## 5. Value-creation angle (the profiling output)
Scoring says *how attractive*; profiling says *what we'd do with it*. Each shortlisted company gets one or two tags — shaping the value case (and, later, the outreach story).

| Angle | When it applies | The move |
|---|---|---|
| **Digitise** | Loved product, weak/absent e-commerce & digital ops | Modern storefront, data, automation, DTC — your build |
| **Performance-market** | Real demand, little/no paid acquisition or CRM | Ben's playbook: paid media, funnel, retention, brand |
| **Roll-up / buy-and-build** | Fragmented category, several similar small players | Acquire a platform, bolt on adjacents, centralise ops |
| **Succession / continuity** | Owner retiring, no successor, business sound | Step in as operating partner, preserve + scale |
| **Distribution expansion** | Great product, narrow reach | Marketplaces, national retail, wholesale, export |

## 6. How scoring runs (and gets smarter)
- **Two-part scoring.** Hard facts (size, ages, review counts) → deterministic **rules** (fast, cheap, auditable). Soft judgements (genuinely loved? how big the marketing gap? how differentiated?) → **LLM** reading the profile against a fixed prompt, returning score + one-line rationale + evidence.
- **Human-in-the-loop.** The system ranks; you and Ben decide. Every accept/reject/re-tag is captured.
- **Learning loop.** Those decisions re-tune weights and thresholds so the ranking converges on CP's actual taste — the compounding advantage.

---

## Open choice (need Ben's steer)
- **Confirm or adjust the §3 weights.** Ben will have strong priors on what makes a consumer brand worth operating — his judgement should set the starting weights before the loop takes over.
