-- Spec 05 §1: "Notes: free-text per company, author + timestamp" — pipeline_items.notes
-- is a single mutable field, not a log; this gives the app a proper append-only thread.
create table notes (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies (id) on delete cascade,
  author text not null check (author in ('julia', 'ben')),
  body text not null,
  created_at timestamptz not null default now()
);

create index idx_notes_company_created on notes (company_id, created_at desc);

alter table notes enable row level security;
create policy "authenticated full access" on notes for all to authenticated using (true) with check (true);
