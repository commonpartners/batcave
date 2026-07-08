-- Spec 01 §8: views for the app. security_invoker so RLS on the underlying
-- tables applies to the querying user, not the view owner.

create or replace view v_shortlist
with (security_invoker = true) as
select
  c.id as company_id,
  c.company_number,
  c.legal_name,
  c.sector_tags,
  c.size_band,
  c.lifecycle,
  c.summary,
  latest.score_id,
  latest.total_score,
  latest.gate_result,
  latest.red_flags,
  latest.value_angles,
  latest.data_completeness,
  latest.rubric_version,
  latest.scored_at,
  coalesce(sig.signals, '[]'::jsonb) as signals,
  pi.stage as pipeline_stage,
  pi.stage_changed_at
from companies c
join lateral (
  select s.id as score_id, s.total_score, s.gate_result, s.red_flags,
         s.value_angles, s.data_completeness, s.rubric_version, s.scored_at
  from scores s
  where s.company_id = c.id
  order by s.scored_at desc
  limit 1
) latest on true
left join lateral (
  select jsonb_agg(jsonb_build_object(
    'name', s2.name, 'family', s2.family, 'value', s2.value, 'computed_at', s2.computed_at
  ) order by s2.computed_at desc) as signals
  from (
    select distinct on (name) name, family, value, computed_at
    from signals
    where company_id = c.id
    order by name, computed_at desc
  ) s2
) sig on true
left join pipeline_items pi on pi.company_id = c.id
where latest.gate_result = 'pass'
order by latest.total_score desc nulls last;

create or replace view v_company_detail
with (security_invoker = true) as
select
  c.*,
  latest.score_id,
  latest.total_score,
  latest.gate_result,
  latest.gate_detail,
  latest.red_flags,
  latest.value_angles,
  latest.data_completeness,
  latest.rubric_version,
  latest.scored_at,
  coalesce(dims.dimensions, '[]'::jsonb) as dimensions,
  coalesce(ppl.people, '[]'::jsonb) as people,
  coalesce(sig.signals, '[]'::jsonb) as signals,
  coalesce(dec.decisions, '[]'::jsonb) as decisions,
  pi.stage as pipeline_stage,
  pi.owner as pipeline_owner,
  pi.notes as pipeline_notes,
  pi.stage_changed_at as pipeline_stage_changed_at
from companies c
left join lateral (
  select s.id as score_id, s.total_score, s.gate_result, s.gate_detail, s.red_flags,
         s.value_angles, s.data_completeness, s.rubric_version, s.scored_at
  from scores s
  where s.company_id = c.id
  order by s.scored_at desc
  limit 1
) latest on true
left join lateral (
  select jsonb_agg(to_jsonb(sd) order by sd.dimension) as dimensions
  from score_dimensions sd
  where sd.score_id = latest.score_id
) dims on true
left join lateral (
  select jsonb_agg(jsonb_build_object(
    'person_id', pe.id, 'name', pe.name, 'birth_year', pe.birth_year, 'birth_month', pe.birth_month,
    'role', cp.role, 'appointed_on', cp.appointed_on, 'resigned_on', cp.resigned_on,
    'is_active', cp.is_active, 'tenure_years', cp.tenure_years,
    'other_active_directorships', cp.other_active_directorships, 'age_years', cp.age_years,
    'ownership_pct_band', cp.ownership_pct_band, 'psc_kind', cp.psc_kind
  ) order by cp.is_active desc, cp.appointed_on asc nulls last) as people
  from company_people cp
  join people pe on pe.id = cp.person_id
  where cp.company_id = c.id
) ppl on true
left join lateral (
  select jsonb_agg(to_jsonb(s2) order by s2.computed_at desc) as signals
  from (
    select distinct on (name) *
    from signals
    where company_id = c.id
    order by name, computed_at desc
  ) s2
) sig on true
left join lateral (
  select jsonb_agg(to_jsonb(d) order by d.decided_at desc) as decisions
  from decisions d
  where d.company_id = c.id
) dec on true
left join pipeline_items pi on pi.company_id = c.id;

create or replace view v_watchlist
with (security_invoker = true) as
select
  w.id as watchlist_item_id,
  w.company_id,
  c.company_number,
  c.legal_name,
  c.sector_tags,
  w.reason,
  w.added_at,
  w.last_signal_check,
  w.deprioritise_after,
  w.status,
  succession.name as succession_signal_name,
  succession.value as succession_signal_value,
  succession.rationale as succession_signal_rationale,
  case
    when w.deprioritise_after is null then null
    else ceil(extract(epoch from (w.deprioritise_after - now())) / 86400.0)
  end as days_to_deprioritise
from watchlist_items w
join companies c on c.id = w.company_id
left join lateral (
  select name, value, rationale
  from signals
  where company_id = w.company_id and family = 'succession'
  order by computed_at desc
  limit 1
) succession on true
order by (w.status = 'fired') desc, w.deprioritise_after asc nulls last;
