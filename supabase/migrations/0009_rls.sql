-- Spec 00 §2 / 01 preamble: RLS on from day one. Two users (Julia, Ben), simple
-- policy: any authenticated user gets full read/write; service role bypasses
-- RLS automatically (Supabase service_role uses a role with bypassrls).

do $$
declare
  t text;
begin
  for t in select unnest(array[
    'companies', 'people', 'company_people', 'source_records', 'signals',
    'rubric_versions', 'scores', 'score_dimensions', 'pipeline_items',
    'decisions', 'watchlist_items', 'jobs', 'app_config', 'taxonomy_rules'
  ])
  loop
    execute format('alter table %I enable row level security;', t);
    execute format(
      'create policy "authenticated full access" on %I for all to authenticated using (true) with check (true);',
      t
    );
  end loop;
end $$;
