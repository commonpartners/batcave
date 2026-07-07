# Common Partners — Platform Architecture & Build Plan (design note)

*Draft for discussion — v0.1, 8 July 2026. Item 4: how the platform is built, and in what order.*

## Design philosophy
A two-person team where Julia builds. So: standard, well-supported components; as much managed infrastructure as possible; LLMs used surgically on the judgement-heavy steps only. The goal is something you can stand up in weeks and extend — not a data-engineering project.

---

## 1. Components
| Layer | Responsibility | Suggested approach |
|---|---|---|
| **Ingestion / scanners** | Scheduled jobs that pull each source, detect new/changed companies, queue them | Scheduled workers (Python or TS); one connector module per source |
| **Enrichment** | Crawl sites, gather reviews/social/distribution, detect web-tech, normalise into the profile | Worker jobs + LLM extraction for messy pages |
| **Scoring** | Fit gate + rules + LLM qualitative scoring; write scores, tags, rationale | Rules engine + Claude with a versioned scoring prompt |
| **Data store** | Single source of truth: companies, people, signals, scores, stage, decisions | Postgres (Supabase) |
| **Application / review** | Where you + Ben read the ranked shortlist, open profiles, record decisions | Web app (Next.js on Vercel) over the DB |
| **Orchestration** | Scheduling, retries, monitoring of the scanning loop | Job scheduler/queue; idempotent, observable runs |
| **Outreach / CRM** | *(deferred)* stages, contact log, templated outreach | Add later once we choose to make contact |

**Data flow:** Scanners → raw candidates → Enrichment → full profile → Scoring (gate → rules → LLM) → Postgres → ranked shortlist in the app → human review → decisions feed the learning loop.

## 2. Core data model (entities)
- **Company** — the central profile record (scoring note §1)
- **Person** — directors/PSCs with age band, tenure, other directorships; linked to companies
- **Signal** — a computed, timestamped feature on a company (succession / upside / consolidation) + evidence
- **Score** — a versioned scoring run: fit result, dimension scores, total, rubric version
- **SourceRecord** — raw pulled data with provenance + fetch date, so every fact is traceable/refreshable
- **PipelineItem / Decision** — stage, owner, notes, and the accept/reject decisions that train the loop

## 3. Suggested stack
- **Database & auth:** Supabase (managed Postgres). Relational model fits the entities cleanly; row-level security if needed later.
- **Front end:** Next.js deployed on Vercel — fast to build a review UI over the DB.
- **Workers:** Python (great for scraping/parsing iXBRL) or TypeScript; run scheduled.
- **LLM:** Claude for extraction + qualitative scoring, called with a versioned prompt so scores are reproducible.
- **Scheduling:** cron-style scheduler for the weekly scanning loop.

*(Both Supabase and Vercel are available as connectors in this workspace, so the Phase-1 scaffold can be stood up directly from here when we're ready.)*

## 4. Where AI is used (and isn't)
- **Used:** sector classification beyond crude SIC codes; extracting structure from messy web pages; the qualitative scoring dimensions; drafting one-line company summaries.
- **Not used:** anything deterministic (size bands, ages, counts, gate logic) — rules are cheaper, faster, auditable. Keep the LLM on judgement, not arithmetic.

## 5. Build vs. buy (decided)
Buy the boring, build the edge. **Bootstrap on free Companies House + targeted scraping** for Phases 0–1; the director-age/succession signal (the real edge) is cheap to compute in-house. **Trial Beauhurst** only once the loop is proven and the data gap is clear. Build in-house the moat: signal computation, the CP rubric, the review workflow, the learning loop.

---

## 6. Phased build plan
| Phase | Goal | Scope | Outcome |
|---|---|---|---|
| **0 — Manual proof** (1–2 wks) | Validate the rubric on real companies before building | Skincare/personal-care sub-sector. Hand-pull ~30 companies (Companies House + web). Score in a spreadsheet using the rubric. Review with Ben. | Confidence the rubric ranks the way you'd want — or the data to fix it |
| **1 — Screening MVP** (3–5 wks) | Automate profiling + scoring for a supplied list | Supabase DB + enrichment + rules/LLM scoring + a simple ranked-list web app. Ingestion still semi-manual | Paste in companies, get ranked, explainable shortlists. Usable daily |
| **2 — Sourcing engine** (4–6 wks) | Automate discovery + the scanning loop | Scheduled scanners over the core sources; succession/upside/consolidation signals; watchlist; alerts on new qualifiers | Pipeline fills itself; a fresh ranked shortlist to review regularly |
| **3 — Scale & learn** (ongoing) | Broaden coverage, tune to your taste | More sources/sectors; the learning loop retuning weights from decisions; (outreach/CRM if/when wanted) | A compounding, proprietary origination platform |

**Why this order:** screening before sourcing looks backwards but isn't — the rubric is the risky, opinionated part and can be tested on hand-picked companies immediately. Once you trust the scoring, automating the funnel that feeds it is comparatively mechanical. Every phase produces something usable with Ben straight away.

## Next steps
1. Confirm the scoring weights with Ben.
2. Run **Phase 0** — hand-score ~30 real skincare/personal-care companies to pressure-test the rubric together.
3. Turn these notes into an engineering spec and begin the Phase 1 screening MVP (scaffold Supabase + Next.js).
