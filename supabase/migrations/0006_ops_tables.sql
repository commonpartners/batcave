-- Spec 01 §7: operational tables
create table jobs (
  id uuid primary key default gen_random_uuid(),
  job_name text not null,
  run_key text not null,
  status text not null check (status in ('running', 'succeeded', 'failed')),
  started_at timestamptz,
  finished_at timestamptz,
  stats jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now(),
  unique (job_name, run_key)
);

create index idx_jobs_name_started on jobs (job_name, started_at desc);

create table app_config (
  id uuid primary key default gen_random_uuid(),
  key text unique not null,
  value jsonb not null,
  description text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger trg_app_config_updated_at
  before update on app_config
  for each row execute function set_updated_at();

create table taxonomy_rules (
  id uuid primary key default gen_random_uuid(),
  sector_tag text not null,
  sic_codes text[] not null default '{}',
  include_keywords text[] not null default '{}',
  exclude_keywords text[] not null default '{}',
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index idx_taxonomy_rules_active on taxonomy_rules (active);

create trigger trg_taxonomy_rules_updated_at
  before update on taxonomy_rules
  for each row execute function set_updated_at();
