# Common Partners — Sourcing Engine (design note)

*Draft for discussion — v0.1, 8 July 2026. Item 2 of the platform: how we find candidate companies.*

## The core idea
Sourcing is not a list you buy once. It's a **standing scanner** over a basket of sources you choose, tuned to fire on specific signals, with a **watchlist** so timing works in your favour. Two firms using the same raw data would still get different shortlists from this — the signal logic and timing are the edge.

---

## 1. Define the box first
Everything downstream inherits an explicit, adjustable definition:

- **Sector:** start with health / wellness / beauty consumer brands + services (skincare, cosmetics, supplements/nutrition, personal care, wellness services, specialist retail). Encode as SIC codes **plus** keyword rules — SIC alone is too blunt for consumer brands.
- **Geography:** UK (Ireland later).
- **Size proxy:** most UK SMEs file abbreviated/micro accounts with **no P&L** — revenue/EBITDA often not disclosed. Screen on balance-sheet strength, employee counts, filing category, third-party estimates. Confirm real numbers in conversation.
- **Status:** active, established (company age = "real foundations" proxy), not insolvent / striking off.

### 1a. What you can (and can't) see in the accounts
Under the rules for financial years starting on/after 6 April 2025:

| Category | Qualifies if it meets 2 of 3 | Public at Companies House |
|---|---|---|
| **Micro** | turnover ≤ £1m · BS ≤ £500k · ≤10 staff | Stripped-back balance sheet only — **no P&L, no turnover** |
| **Small** | turnover ≤ £15m · BS ≤ £7.5m · ≤50 staff | "Filleted" — balance sheet + limited notes — **no P&L, no turnover** |
| **Medium** | turnover ≤ £54m · BS ≤ £27m · ≤250 staff | Full accounts **including P&L** (turnover, profit public) |
| **Large** | above medium | Full accounts, fully public |

**The line is the top of "small": once turnover is above ~£15m (2 of 3), a company files a full P&L and revenue/profit are readable off the filing.** Below that it can withhold both.

Implication for our pipeline: a business at **£1–10m EBITDA usually has turnover well above £15m** (unless very high-margin), so **many targets will be "medium" and publish their numbers.** The dark ones are the smaller / high-margin end. When P&L isn't visible, triangulate via balance sheet + employee count + sector-margin benchmarks + third-party estimates, and confirm actuals with the owner under NDA. (Watch: ECCTA will require small/micro to file a P&L from **April 2028**, delayed from 2027 — but they can keep it off the *public* register, so don't rely on it becoming visible.)

## 2. Sources — two tiers

**Core (registry / financial):**
- **Companies House** — free API, near-complete UK coverage. Holds director/PSC records, **director ages**, and event filings (appointments, terminations, PSC changes). The backbone.
- Accounts filings (iXBRL) — balance-sheet figures where filed in full.
- **Paid aggregator** (Beauhurst = UK-focused; Grata / SourceScrub = private-company discovery) — cleaner profiles, better tagging, pre-built filters. Trial first; not essential day one.

**Signal / intent (the edge):**
- Company websites + **web-tech detection** — modern shop? email capture? analytics/ad pixels? → digital-maturity read.
- Reviews (Trustpilot, Google, Amazon, sector sites) — evidence of "products people love."
- Stockists & marketplaces — distribution footprint / headroom.
- Social presence — following, cadence, engagement, paid activity.
- Trade bodies, awards, directories, trade press — credible players, quality flags, transition events. **Weighted for launch sub-sector:** CTPA and Independent Beauty Association member directories; British Beauty Council; B Corp directory (quality filter); awards (CEW Beauty Awards, Beauty Shortlist, Free From Skincare Awards); retailer stockist lists (Space NK, Cult Beauty, John Lewis, Holland & Barrett) as distribution reads.
- Broker/intermediary feeds — lower edge (already advised) but useful coverage + benchmark.
- LinkedIn + personal network — keep it, but **capture into the system**, not inboxes.

## 3. Signals we compute (the proprietary edge)

**Succession / seller-readiness** *(sharpest edge, cheap to build):*
- Controlling director ~65–75 (Companies House has birth month/year).
- 12–20+ yr single-owner tenure, few other directorships (quiet lifestyle business).
- Recent PSC / board changes signalling a transition beginning.
- Structural tailwind: large cohort of owner-managers reaching retirement with no successor.

**Latent-upside gap** *(what you + Ben add):*
- Strong reviews + weak digital (dated site, thin social, no paid marketing, no e-comm). Bigger gap = higher rank.
- Narrow distribution despite a loved product.
- Under-exploited brand / heritage.

**Consolidation:**
- Fragmented sub-category, no dominant consolidator → roll-up candidate.
- Adjacency to something already owned (shared customers/channels/suppliers).

## 4. Continuous loop + watchlist
Runs on a cadence (weekly-ish):
1. Re-scan universe; detect new companies + **changed** filings since last run.
2. Recompute signals (a new director termination can move a company up overnight).
3. Enrich new candidates automatically.
4. Re-score, re-rank, surface new qualifiers for review.
5. **Watchlist:** great-fit-but-not-yet-in-transition businesses are parked and monitored → you're first in line when a succession signal fires.

---

## Decisions (locked 8 Jul 2026)
1. **Launch narrow.** First sub-sector: **independent UK skincare & natural/personal-care brands** — fragmented (roll-up + volume), review-heavy (measurable "loved"), wide digital-maturity spread (the digitise/perf-marketing gap), succession-rich, heritage angle. Supplements/nutrition = second wave.
2. **Bootstrap on data first.** Build Phases 0–1 on free Companies House (director ages/succession = the key signal) + targeted scraping. Take a paid **trial of Beauhurst** only once the loop is proven and the specific data gap is clear. Indicative costs: Grata ~$15k/yr, SourceScrub ~$20–60k/yr, Beauhurst quote-only (four-to-low-five-figure £). Don't subscribe day one.
3. **Trusted sources chosen** — see the trade-bodies line in §2 (CTPA, IBA, British Beauty Council, B Corp, awards, retailer stockist lists).
4. **Outreach: deferred.** Not building outreach for now, so GDPR/PECR isn't a live constraint yet. Revisit before any owner contact.
