-- Spec 01 §5: source_records — provenance for every fact in the system
create table source_records (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references companies (id) on delete cascade,
  source text not null check (source in (
    'companies_house_profile', 'companies_house_officers', 'companies_house_psc',
    'companies_house_filings', 'ixbrl_accounts', 'website_crawl', 'trustpilot',
    'google_reviews', 'social', 'stockist', 'trade_body', 'manual'
  )),
  source_url text,
  fetched_at timestamptz not null default now(),
  raw jsonb,
  content_hash text,
  created_at timestamptz not null default now()
);

create index idx_source_records_company_source_fetched
  on source_records (company_id, source, fetched_at desc);

-- Spec 01 §3: signals — one row per computed signal per company per run, append-only
create table signals (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies (id) on delete cascade,
  family text not null check (family in ('succession', 'latent_upside', 'consolidation')),
  name text not null,
  value numeric not null check (value between 0 and 1),
  evidence jsonb,
  rationale text,
  computed_at timestamptz not null default now(),
  signal_version text
);

create index idx_signals_company_name_computed
  on signals (company_id, name, computed_at desc);
create index idx_signals_family on signals (family);
