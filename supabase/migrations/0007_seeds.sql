-- Spec 01 §7 seeds + Spec 04 §3 rubric weights + Spec 02 §2 taxonomy
-- All values below are the documented defaults and are explicitly "provisional
-- pending Ben's input" per spec 00 §5 — surfaced as such in the /admin UI.

insert into rubric_versions (version, weights, gate_config, prompt_hashes, active, notes)
values (
  '1.0.0',
  '{
    "brand_customer_equity": 25,
    "latent_digital_upside": 20,
    "financial_quality": 20,
    "deal_accessibility": 10,
    "team_continuity": 10,
    "market_consolidation": 10,
    "differentiation": 5
  }'::jsonb,
  '{
    "min_company_age_years": 8,
    "shortlist_threshold": 60,
    "watchlist_auto_score_threshold": 70,
    "watchlist_succession_signal_floor": 0.5,
    "situation_succession_signal_floor": 0.3,
    "size_band_thresholds": {
      "fit_now_ev_max_gbp": 5000000,
      "stretch_ebitda_max_gbp": 10000000
    }
  }'::jsonb,
  '{}'::jsonb,
  true,
  'Seed v1.0.0 per spec 04 §3 — weights and gate thresholds provisional pending Ben. Changing weights requires a new rubric version; never edit this row in place.'
);

insert into taxonomy_rules (sector_tag, sic_codes, include_keywords, exclude_keywords, active)
values (
  'skincare-personal-care',
  array['20420', '46450', '47750', '20411', '20412', '96020', '86900', '47910', '47190', '47990'],
  array[
    'skincare', 'skin care', 'cosmetics', 'beauty', 'botanical', 'organic', 'natural',
    'serum', 'balm', 'soap', 'bath', 'body care', 'haircare', 'aromatherapy', 'spa'
  ],
  array[
    'software', 'app', 'platform', 'clinic', 'surgery', 'pharma', 'medical device', 'salon-only'
  ],
  true
);

insert into app_config (key, value, description) values
  (
    'size_band_thresholds',
    '{"fit_now_ev_max_gbp": 5000000, "stretch_ebitda_max_gbp": 10000000}'::jsonb,
    'Spec 00 §5.2 — default: fit-now <= £5m EV; stretch flag for £5m EV-£10m EBITDA-implied.'
  ),
  (
    'watchlist_patience_months',
    '24'::jsonb,
    'Spec 00 §5.3 / 02 §5 — months of monitoring before auto-deprioritise.'
  ),
  (
    'scan_cadence',
    '{
      "discover": "1st of month 03:00 UTC",
      "refresh": "Mon 06:00 UTC",
      "enrich": "Mon 09:00 UTC",
      "score": "Mon 12:00 UTC",
      "watchlist_check": "Mon 13:00 UTC",
      "digest": "Mon 14:00 UTC"
    }'::jsonb,
    'Spec 02 §6 — GitHub Actions cron schedule.'
  ),
  (
    'launch_sector_taxonomy',
    '["skincare-personal-care"]'::jsonb,
    'Spec 00 §1 — launch scope; supplements/nutrition is wave two.'
  ),
  (
    'min_company_age_years',
    '8'::jsonb,
    'Spec 02 §2 — universe filter: incorporation >= this many years ago.'
  ),
  (
    'llm_budget_per_run',
    '300'::jsonb,
    'Spec 03 §8 — LLM cost guardrail: max LLM calls per enrich/score run.'
  ),
  (
    'refresh_intervals_days',
    '{"website": 90, "reviews": 30, "social": 60}'::jsonb,
    'Spec 03 §8 — per-source freshness intervals used by enrich --pending.'
  ),
  (
    'decision_reason_codes',
    '[
      "brand_stronger_than_score", "brand_weaker_than_score", "too_small", "too_big",
      "digital_gap_smaller_than_it_looks", "sector_wrong", "owner_unlikely_to_sell",
      "financials_concerning", "love_the_heritage_angle", "competition_for_deal", "gut_feel"
    ]'::jsonb,
    'Spec 05 §2 — seed reason-code list for the decision dialog; editable in /admin.'
  ),
  (
    'rubric_provisional',
    'true'::jsonb,
    'Spec 05 §1 /admin — show "provisional - pending Ben" banner until first manual confirmation.'
  );
