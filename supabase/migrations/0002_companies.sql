-- Spec 01 §1: companies — the central profile
create table companies (
  id uuid primary key default gen_random_uuid(),
  company_number text unique not null,
  legal_name text not null,
  trading_names text[],
  incorporation_date date,
  company_status text,
  registered_address jsonb,
  region text,
  website text,
  sic_codes text[],
  sector_tags text[],
  sector_tag_source text check (sector_tag_source in ('rules', 'llm', 'manual')),
  filing_category text check (filing_category in ('micro', 'small', 'medium', 'large', 'full', 'unknown')) default 'unknown',
  latest_accounts_date date,
  balance_sheet jsonb,
  employee_count int,
  size_band text check (size_band in ('too-small', 'fit-now', 'stretch', 'too-large', 'unknown')) default 'unknown',
  revenue_estimate jsonb,
  ebitda_estimate jsonb,
  digital_maturity int check (digital_maturity between 1 and 5),
  summary text,
  lifecycle text not null default 'discovered'
    check (lifecycle in ('discovered', 'enriched', 'scored', 'shortlisted', 'watchlist', 'rejected', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index idx_companies_lifecycle on companies (lifecycle);
create index idx_companies_sector_tags on companies using gin (sector_tags);
create index idx_companies_sic_codes on companies using gin (sic_codes);

create trigger trg_companies_updated_at
  before update on companies
  for each row execute function set_updated_at();

-- Spec 01 §2: people + company_people
create table people (
  id uuid primary key default gen_random_uuid(),
  ch_officer_id text unique,
  name text,
  birth_year int,
  birth_month int,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger trg_people_updated_at
  before update on people
  for each row execute function set_updated_at();

create table company_people (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies (id) on delete cascade,
  person_id uuid not null references people (id) on delete cascade,
  role text not null check (role in ('director', 'psc', 'secretary')),
  appointed_on date,
  resigned_on date,
  psc_kind text,
  ownership_pct_band text check (ownership_pct_band in ('25-50', '50-75', '75-100')),
  is_active boolean generated always as (resigned_on is null) stored,
  -- derived by the signals job (spec 01 §2):
  tenure_years numeric,
  other_active_directorships int,
  age_years int,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (company_id, person_id, role, appointed_on)
);

create index idx_company_people_company on company_people (company_id);
create index idx_company_people_person on company_people (person_id);
create index idx_company_people_active on company_people (company_id) where is_active;

create trigger trg_company_people_updated_at
  before update on company_people
  for each row execute function set_updated_at();
