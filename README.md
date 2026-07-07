# Common Partners Platform

Deal-origination platform for Common Partners: a sourcing engine (Companies House +
signal sources) and a screening engine (enrichment, scoring, review app) over one
Supabase Postgres database.

Full spec: [`docs/00_overview.md`](docs/00_overview.md) (read 00 → 08 in order).
Day-one setup: [`docs/08_day_one_runbook.md`](docs/08_day_one_runbook.md).

## Layout

```
app/                 Next.js (App Router, TS) review app — deploy to Vercel
workers/             Python 3.12 package (cp_workers) — sourcing, enrichment, scoring
  cp_workers/
    connectors/      Companies House, web, reviews, social
    enrichment/      website, webtech, reviews, social, distribution, financials
    signals/         succession, latent-upside, consolidation (pure functions)
    scoring/         gate, rules dimensions, LLM dimensions, red flags, value angles
    cli.py           single entry point: python -m cp_workers.cli <command>
  prompts/           versioned LLM prompts (markdown, front-matter with version)
  tests/             pytest
supabase/migrations/ SQL migrations (schema + seeds + views + RLS)
.github/workflows/   cron workflows (discover/refresh/enrich/score/watchlist/digest)
docs/                copy of the engineering specs
```

## Quickstart (workers)

```bash
cd workers
python -m venv .venv && .venv/Scripts/activate  # or source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env   # fill in keys
pytest
python -m cp_workers.cli --help
```

## Quickstart (app)

```bash
cd app
npm install
npm run dev
```

## Quickstart (database)

```bash
supabase db push   # applies supabase/migrations/ to your project
```

See [`docs/08_day_one_runbook.md`](docs/08_day_one_runbook.md) for the full account
setup + first-run sequence.
