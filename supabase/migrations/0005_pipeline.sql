-- Spec 01 §6: pipeline & decisions
create table pipeline_items (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null unique references companies (id) on delete cascade,
  stage text not null default 'inbox'
    check (stage in ('inbox', 'review', 'shortlist', 'watchlist', 'pursue', 'passed')),
  owner text,
  notes text,
  stage_changed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger trg_pipeline_items_updated_at
  before update on pipeline_items
  for each row execute function set_updated_at();

-- append-only: the learning-loop training data (spec 05 §2-3)
create table decisions (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies (id) on delete cascade,
  score_id uuid references scores (id),
  decision text not null check (decision in ('accept', 'reject', 'watchlist', 'retag')),
  reasons text[] not null default '{}',
  free_text text,
  decided_by text not null check (decided_by in ('julia', 'ben')),
  decided_at timestamptz not null default now()
);

create index idx_decisions_company on decisions (company_id, decided_at desc);

create table watchlist_items (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null unique references companies (id) on delete cascade,
  reason text,
  added_at timestamptz not null default now(),
  last_signal_check timestamptz,
  deprioritise_after timestamptz,
  status text not null default 'watching' check (status in ('watching', 'fired', 'expired')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index idx_watchlist_items_status on watchlist_items (status);

create trigger trg_watchlist_items_updated_at
  before update on watchlist_items
  for each row execute function set_updated_at();
