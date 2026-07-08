-- Spec 01 §4: rubric_versions + scores + score_dimensions
create table rubric_versions (
  id uuid primary key default gen_random_uuid(),
  version text unique not null,
  weights jsonb not null,
  gate_config jsonb not null,
  prompt_hashes jsonb not null default '{}'::jsonb,
  active boolean not null default false,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- exactly one active rubric version at a time
create unique index idx_rubric_versions_one_active
  on rubric_versions ((true)) where active;

create trigger trg_rubric_versions_updated_at
  before update on rubric_versions
  for each row execute function set_updated_at();

create table scores (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies (id) on delete cascade,
  rubric_version text not null references rubric_versions (version),
  gate_result text not null check (gate_result in ('pass', 'hold', 'fail')),
  gate_detail jsonb,
  total_score numeric check (total_score between 0 and 100),
  red_flags text[] not null default '{}',
  value_angles text[] not null default '{}',
  profile_hash text,
  data_completeness numeric check (data_completeness between 0 and 1),
  scored_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index idx_scores_company_scored_at on scores (company_id, scored_at desc);

-- score cache: reuse a prior run's score when profile + rubric are unchanged
create unique index idx_scores_cache_key
  on scores (company_id, profile_hash, rubric_version)
  where profile_hash is not null;

create table score_dimensions (
  id uuid primary key default gen_random_uuid(),
  score_id uuid not null references scores (id) on delete cascade,
  dimension text not null,
  raw_score numeric check (raw_score between 0 and 5),
  weighted numeric,
  method text check (method in ('rules', 'llm')),
  rationale text,
  evidence jsonb,
  prompt_hash text
);

create index idx_score_dimensions_score on score_dimensions (score_id);
