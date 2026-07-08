-- 0011: Wide funnel & pre-gate (spec 09)
-- Free-data triage before paid enrichment: score lives on companies,
-- config drives weights/threshold/budget, taxonomy widens to all H/W/B.

alter table companies
  add column if not exists pregate_score numeric,
  add column if not exists pregate_detail jsonb;

create index if not exists idx_companies_pregate_score
  on companies (pregate_score desc nulls last);

insert into app_config (key, value, description) values
  (
    'pregate_weights',
    '{"succession": 0.40, "size_fit": 0.25, "sector_confidence": 0.20, "foundations": 0.15}'::jsonb,
    'Spec 09 §4 — pre-gate component weights (free data only). Must sum to 1.'
  ),
  (
    'pregate_threshold',
    '0.45'::jsonb,
    'Spec 09 §5 — minimum pregate_score to be eligible for enrichment.'
  ),
  (
    'enrichment_budget_per_week',
    '150'::jsonb,
    'Spec 09 §5 — max companies promoted to enrichment per weekly run.'
  ),
  (
    'pregate_hot_threshold',
    '0.60'::jsonb,
    'Spec 09 §3 — pregate_score at/above which a company gets weekly (hot) CH refresh.'
  ),
  (
    'calibration_benchmark_company_numbers',
    '[]'::jsonb,
    'Spec 04 §4 — fixed benchmark company numbers for the monthly calibration audit. Chosen in Phase 0.'
  )
on conflict (key) do nothing;

-- Widened H/W/B taxonomy (spec 09 §2). Same mechanism as launch row;
-- SIC seeds deliberately broad, keyword rules do the narrowing.
alter table taxonomy_rules
  add constraint taxonomy_rules_sector_tag_key unique (sector_tag);

insert into taxonomy_rules (sector_tag, sic_codes, include_keywords, exclude_keywords, active) values
  (
    'supplements-nutrition',
    array['10890','21100','21200','46460','47750','47910'],
    array['supplement','vitamin','nutrition','nutraceutical','protein','collagen','probiotic','herbal','botanical','superfood','wellness'],
    array['software','app','platform','clinic','pharmacy chain','medical device','veterinary'],
    true
  ),
  (
    'haircare-beauty',
    array['20420','46450','47750','47910','96020'],
    array['haircare','hair care','shampoo','salon products','cosmetic','beauty','makeup','make-up','nail','fragrance','perfume','grooming'],
    array['software','app','platform','salon franchise','recruitment','training academy'],
    true
  ),
  (
    'wellness-services',
    array['96040','93130','86900','96090'],
    array['spa','wellness','massage','yoga','pilates','retreat','therapy','holistic','wellbeing'],
    array['software','app','platform','gym chain','physiotherapy clinic','nhs'],
    true
  ),
  (
    'personal-care-manufacturing',
    array['20411','20412','20420','32990'],
    array['soap','bath','body care','skincare','candle','aromatherapy','essential oil','deodorant','oral care','toothpaste'],
    array['industrial','cleaning services','janitorial','detergent bulk'],
    true
  )
on conflict (sector_tag) do nothing;
