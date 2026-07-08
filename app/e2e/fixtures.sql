-- Fixture data for Playwright smoke tests (app/e2e/*.spec.ts).
-- Run supabase/migrations/*.sql first (including 0007_seeds.sql, which
-- seeds rubric_versions '1.0.0' and app_config), then load this file into
-- the same (test) database before running `npm run e2e`.
--
-- Three companies covering the shortlist, a gate-hold, and a watchlist item:
--   1. Acme Skincare Ltd   (11111111) - gate pass, high score, on the shortlist
--   2. Bristol Botanicals Ltd (22222222) - gate pass, lower score, red flag, watchlisted
--   3. Old Mill Soap Co Ltd (33333333) - gate hold (fails the "size" test)

begin;

insert into companies (
  id, company_number, legal_name, trading_names, incorporation_date, company_status,
  region, website, sic_codes, sector_tags, sector_tag_source, filing_category,
  latest_accounts_date, employee_count, size_band, revenue_estimate, ebitda_estimate,
  digital_maturity, summary, lifecycle
) values
(
  '00000000-0000-0000-0000-000000000001', '11111111', 'Acme Skincare Ltd', array['Acme Skincare'],
  '2008-03-01', 'active', 'South West', 'https://acmeskincare.example', array['20420'],
  array['skincare-personal-care'], 'rules', 'small', '2025-12-31', 18, 'fit-now',
  '{"value_pence": 180000000, "source": "benchmark", "method": "benchmark", "confidence": "med", "as_of": "2026-01-01"}'::jsonb,
  '{"value_pence": 27000000, "source": "benchmark", "method": "benchmark", "confidence": "med", "as_of": "2026-01-01"}'::jsonb,
  2, 'Heritage botanical skincare brand, strong reviews, thin digital footprint.', 'scored'
),
(
  '00000000-0000-0000-0000-000000000002', '22222222', 'Bristol Botanicals Ltd', array['Bristol Botanicals'],
  '2010-06-15', 'active', 'South West', 'https://bristolbotanicals.example', array['20420'],
  array['skincare-personal-care'], 'rules', 'micro', '2025-09-30', 6, 'fit-now',
  '{"value_pence": 65000000, "source": "benchmark", "method": "benchmark", "confidence": "low", "as_of": "2026-01-01"}'::jsonb,
  '{"value_pence": 8000000, "source": "benchmark", "method": "benchmark", "confidence": "low", "as_of": "2026-01-01"}'::jsonb,
  3, 'Small-batch soapmaker, single founder, concentrated customer base.', 'scored'
),
(
  '00000000-0000-0000-0000-000000000003', '33333333', 'Old Mill Soap Co Ltd', array['Old Mill Soap'],
  '2005-01-20', 'active', 'Wales', 'https://oldmillsoap.example', array['20420'],
  array['skincare-personal-care'], 'rules', 'unknown', null, null, 'unknown',
  null, null, null, 'Unclear size - accounts not yet filed under new category.', 'scored'
)
on conflict (company_number) do nothing;

insert into rubric_versions (version, weights, gate_config, active)
values ('1.0.0', '{}'::jsonb, '{}'::jsonb, true)
on conflict (version) do nothing;

insert into scores (
  id, company_id, rubric_version, gate_result, gate_detail, total_score, red_flags, value_angles,
  profile_hash, data_completeness, scored_at
) values
(
  '00000000-0000-0000-0000-00000000a001', '00000000-0000-0000-0000-000000000001', '1.0.0', 'pass',
  '{"sector": {"result": "pass", "reason": "matches skincare taxonomy"}, "size": {"result": "pass", "reason": "fit-now band"}}'::jsonb,
  82, array[]::text[], array['reviews_strong_digital_weak', 'heritage_underexploited'],
  'fixture-hash-acme-1', 1.0, now() - interval '2 days'
),
(
  '00000000-0000-0000-0000-00000000a002', '00000000-0000-0000-0000-000000000002', '1.0.0', 'pass',
  '{"sector": {"result": "pass", "reason": "matches skincare taxonomy"}, "size": {"result": "pass", "reason": "fit-now band"}}'::jsonb,
  65, array['owner_concentration'], array['narrow_distribution'],
  'fixture-hash-bristol-1', 0.8, now() - interval '5 days'
),
(
  '00000000-0000-0000-0000-00000000a003', '00000000-0000-0000-0000-000000000003', '1.0.0', 'hold',
  '{"sector": {"result": "pass", "reason": "matches skincare taxonomy"}, "size": {"result": "hold", "reason": "employee_count and accounts both unknown"}}'::jsonb,
  null, array[]::text[], array[]::text[],
  'fixture-hash-oldmill-1', 0.4, now() - interval '1 day'
)
on conflict do nothing;

insert into score_dimensions (score_id, dimension, raw_score, weighted, method, rationale, evidence) values
('00000000-0000-0000-0000-00000000a001', 'brand_customer_equity', 4.2, 21.0, 'llm', 'Strong repeat-purchase language across reviews and heritage story.', '{"quotes": [{"text": "customers rave about the balm", "source_url": "https://acmeskincare.example/reviews"}]}'::jsonb),
('00000000-0000-0000-0000-00000000a001', 'latent_digital_upside', 4.5, 22.5, 'rules', 'High review strength, digital maturity only 2/5.', '{"review_strength": 0.82, "digital_maturity": 2}'::jsonb),
('00000000-0000-0000-0000-00000000a001', 'financial_quality', 3.5, 17.5, 'rules', 'Stable margins, benchmark-estimated EBITDA.', '{}'::jsonb),
('00000000-0000-0000-0000-00000000a002', 'brand_customer_equity', 2.8, 14.0, 'llm', 'Loyal but small customer base.', '{}'::jsonb),
('00000000-0000-0000-0000-00000000a002', 'deal_accessibility', 4.0, 4.0, 'rules', 'Single founder nearing retirement age, no other directorships.', '{}'::jsonb)
on conflict do nothing;

insert into signals (company_id, family, name, value, evidence, rationale, computed_at, signal_version) values
('00000000-0000-0000-0000-000000000001', 'latent_upside', 'reviews_strong_digital_weak', 0.82, '{"review_rating": 4.7, "review_count": 340}'::jsonb, 'Strong Trustpilot rating with a dated, low-conversion website.', now() - interval '2 days', 'v1'),
('00000000-0000-0000-0000-000000000001', 'succession', 'long_single_owner_tenure', 0.55, '{"tenure_years": 17}'::jsonb, 'Founder-director has held the company for 17 years.', now() - interval '2 days', 'v1'),
('00000000-0000-0000-0000-000000000002', 'succession', 'director_retirement_window', 0.7, '{"age_years": 64}'::jsonb, 'Sole director is within the typical retirement window.', now() - interval '5 days', 'v1'),
('00000000-0000-0000-0000-000000000002', 'latent_upside', 'narrow_distribution', 0.4, '{"stockists": 3}'::jsonb, 'Only sold through 3 independent stockists.', now() - interval '5 days', 'v1')
on conflict do nothing;

insert into pipeline_items (company_id, stage, owner, notes, stage_changed_at) values
('00000000-0000-0000-0000-000000000001', 'shortlist', 'julia', 'Looks promising, revisit after Q1 accounts.', now() - interval '2 days'),
('00000000-0000-0000-0000-000000000002', 'watchlist', 'ben', null, now() - interval '5 days'),
('00000000-0000-0000-0000-000000000003', 'review', null, null, now() - interval '1 day')
on conflict (company_id) do nothing;

insert into watchlist_items (company_id, reason, added_at, last_signal_check, deprioritise_after, status) values
('00000000-0000-0000-0000-000000000002', 'Founder near retirement but no succession event yet - monitoring.', now() - interval '5 days', now() - interval '1 day', now() + interval '60 days', 'watching')
on conflict (company_id) do nothing;

commit;
