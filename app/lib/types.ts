/**
 * Hand-written types mirroring supabase/migrations/*.sql. There is no live
 * project to run `supabase gen types` against yet; once one exists this file
 * should be replaced by the generated Database type (same shape is
 * preserved so call sites don't need to change).
 *
 * These are declared as `type` (not `interface`) throughout: an `interface`
 * has no implicit index signature, so it fails the `extends Record<string,
 * unknown>` structural check that @supabase/postgrest-js's GenericTable /
 * GenericView constraints run on Row - which silently collapses the whole
 * Database generic to `never` and breaks every `.from(...)` call's typing.
 */

export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[];

export type GateResult = "pass" | "hold" | "fail";
export type Lifecycle =
  | "discovered"
  | "enriched"
  | "scored"
  | "shortlisted"
  | "watchlist"
  | "rejected"
  | "archived";
export type SizeBand = "too-small" | "fit-now" | "stretch" | "too-large" | "unknown";
export type PipelineStage = "inbox" | "review" | "shortlist" | "watchlist" | "pursue" | "passed";
export type DecisionType = "accept" | "reject" | "watchlist" | "retag";
export type DecidedBy = "julia" | "ben";
export type WatchlistStatus = "watching" | "fired" | "expired";
export type JobStatus = "running" | "succeeded" | "failed";

export type MoneyEstimate = {
  value_pence: number;
  source: string;
  method: "benchmark" | "filed";
  confidence: "high" | "med" | "low";
  as_of: string;
};

export type SignalSummary = {
  name: string;
  family: "succession" | "latent_upside" | "consolidation";
  value: number;
  computed_at: string;
};

export type SignalRow = SignalSummary & {
  id: string;
  company_id: string;
  evidence: Json;
  rationale: string | null;
  signal_version: string | null;
};

export type ScoreDimensionRow = {
  id: string;
  score_id: string;
  dimension: string;
  raw_score: number | null;
  weighted: number | null;
  method: "rules" | "llm" | null;
  rationale: string | null;
  evidence: Json;
  prompt_hash: string | null;
};

export type PersonSummary = {
  person_id: string;
  name: string | null;
  birth_year: number | null;
  birth_month: number | null;
  role: "director" | "psc" | "secretary";
  appointed_on: string | null;
  resigned_on: string | null;
  is_active: boolean;
  tenure_years: number | null;
  other_active_directorships: number | null;
  age_years: number | null;
  ownership_pct_band: string | null;
  psc_kind: string | null;
};

export type DecisionRow = {
  id: string;
  company_id: string;
  score_id: string | null;
  decision: DecisionType;
  reasons: string[];
  free_text: string | null;
  decided_by: DecidedBy;
  decided_at: string;
};

/** `notes` — spec 05 §1 free-text per company, author + timestamp (0011_notes.sql) */
export type NoteRow = {
  id: string;
  company_id: string;
  author: DecidedBy;
  body: string;
  created_at: string;
};

export type TopDimension = {
  dimension: string;
  raw_score: number | null;
  weighted: number | null;
};

/** `v_shortlist` — spec 01 §8 / 0008_views.sql */
export type ShortlistRow = {
  company_id: string;
  company_number: string;
  legal_name: string;
  sector_tags: string[] | null;
  size_band: SizeBand;
  lifecycle: Lifecycle;
  summary: string | null;
  score_id: string;
  total_score: number | null;
  gate_result: GateResult;
  red_flags: string[];
  value_angles: string[];
  data_completeness: number | null;
  rubric_version: string;
  scored_at: string;
  signals: SignalSummary[];
  pipeline_stage: PipelineStage | null;
  stage_changed_at: string | null;
  top_dimensions: TopDimension[];
};

/** `v_company_detail` — spec 01 §8 / 0008_views.sql */
export type CompanyDetailRow = {
  id: string;
  company_number: string;
  legal_name: string;
  trading_names: string[] | null;
  incorporation_date: string | null;
  company_status: string | null;
  registered_address: Json;
  region: string | null;
  website: string | null;
  sic_codes: string[] | null;
  sector_tags: string[] | null;
  sector_tag_source: "rules" | "llm" | "manual" | null;
  filing_category: string | null;
  latest_accounts_date: string | null;
  balance_sheet: Json;
  employee_count: number | null;
  size_band: SizeBand;
  revenue_estimate: MoneyEstimate | null;
  ebitda_estimate: MoneyEstimate | null;
  digital_maturity: number | null;
  summary: string | null;
  lifecycle: Lifecycle;
  created_at: string;
  updated_at: string;
  score_id: string | null;
  total_score: number | null;
  gate_result: GateResult | null;
  gate_detail: Record<string, { result: string; reason: string }> | null;
  red_flags: string[] | null;
  value_angles: string[] | null;
  data_completeness: number | null;
  rubric_version: string | null;
  scored_at: string | null;
  dimensions: ScoreDimensionRow[];
  people: PersonSummary[];
  signals: SignalRow[];
  decisions: DecisionRow[];
  pipeline_stage: PipelineStage | null;
  pipeline_owner: string | null;
  pipeline_notes: string | null;
  pipeline_stage_changed_at: string | null;
  notes: NoteRow[];
};

/** `v_watchlist` — spec 01 §8 / 0008_views.sql */
export type WatchlistRow = {
  watchlist_item_id: string;
  company_id: string;
  company_number: string;
  legal_name: string;
  sector_tags: string[] | null;
  reason: string | null;
  added_at: string;
  last_signal_check: string | null;
  deprioritise_after: string | null;
  status: WatchlistStatus;
  succession_signal_name: string | null;
  succession_signal_value: number | null;
  succession_signal_rationale: string | null;
  days_to_deprioritise: number | null;
};

export type ScoreRow = {
  id: string;
  company_id: string;
  rubric_version: string;
  gate_result: GateResult;
  gate_detail: Record<string, { result: string; reason: string }> | null;
  total_score: number | null;
  red_flags: string[];
  value_angles: string[];
  profile_hash: string | null;
  data_completeness: number | null;
  scored_at: string;
  created_at: string;
};

export type RubricVersionRow = {
  id: string;
  version: string;
  weights: Record<string, number>;
  gate_config: Record<string, unknown>;
  prompt_hashes: Record<string, unknown>;
  active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type AppConfigRow = {
  id: string;
  key: string;
  value: Json;
  description: string | null;
  created_at: string;
  updated_at: string;
};

export type JobRow = {
  id: string;
  job_name: string;
  run_key: string;
  status: JobStatus;
  started_at: string | null;
  finished_at: string | null;
  stats: Json;
  error: string | null;
  created_at: string;
};

export type CompanyRow = {
  id: string;
  company_number: string;
  legal_name: string;
  trading_names: string[] | null;
  incorporation_date: string | null;
  company_status: string | null;
  registered_address: Json;
  region: string | null;
  website: string | null;
  sic_codes: string[] | null;
  sector_tags: string[] | null;
  sector_tag_source: string | null;
  filing_category: string | null;
  latest_accounts_date: string | null;
  balance_sheet: Json;
  employee_count: number | null;
  size_band: SizeBand;
  revenue_estimate: MoneyEstimate | null;
  ebitda_estimate: MoneyEstimate | null;
  digital_maturity: number | null;
  summary: string | null;
  lifecycle: Lifecycle;
  created_at: string;
  updated_at: string;
};

export type TaxonomyRuleRow = {
  id: string;
  sector_tag: string;
  sic_codes: string[];
  include_keywords: string[];
  exclude_keywords: string[];
  active: boolean;
  created_at: string;
  updated_at: string;
};

/**
 * Minimal Database shape for the @supabase/ssr generics. Only the
 * tables/views this app touches are declared; Row/Insert/Update collapse to
 * the same shape since we only need typed `.select()` results here.
 */
export type Database = {
  public: {
    Tables: {
      companies: {
        Row: CompanyRow;
        Insert: Record<string, unknown>;
        Update: Record<string, unknown>;
        Relationships: [];
      };
      pipeline_items: {
        Row: Record<string, unknown>;
        Insert: Record<string, unknown>;
        Update: Record<string, unknown>;
        Relationships: [];
      };
      decisions: {
        Row: DecisionRow;
        Insert: Partial<DecisionRow>;
        Update: Partial<DecisionRow>;
        Relationships: [];
      };
      notes: {
        Row: NoteRow;
        Insert: Partial<NoteRow>;
        Update: Partial<NoteRow>;
        Relationships: [];
      };
      watchlist_items: {
        Row: Record<string, unknown>;
        Insert: Record<string, unknown>;
        Update: Record<string, unknown>;
        Relationships: [];
      };
      scores: {
        Row: ScoreRow;
        Insert: Partial<ScoreRow>;
        Update: Partial<ScoreRow>;
        Relationships: [
          {
            foreignKeyName: "scores_company_id_fkey";
            columns: ["company_id"];
            isOneToOne: false;
            referencedRelation: "companies";
            referencedColumns: ["id"];
          },
        ];
      };
      score_dimensions: {
        Row: ScoreDimensionRow;
        Insert: Record<string, unknown>;
        Update: Record<string, unknown>;
        Relationships: [];
      };
      rubric_versions: {
        Row: RubricVersionRow;
        Insert: Record<string, unknown>;
        Update: Record<string, unknown>;
        Relationships: [];
      };
      app_config: {
        Row: AppConfigRow;
        Insert: Record<string, unknown>;
        Update: Record<string, unknown>;
        Relationships: [];
      };
      jobs: {
        Row: JobRow;
        Insert: Record<string, unknown>;
        Update: Record<string, unknown>;
        Relationships: [];
      };
      taxonomy_rules: {
        Row: TaxonomyRuleRow;
        Insert: Record<string, unknown>;
        Update: Record<string, unknown>;
        Relationships: [];
      };
    };
    Views: {
      v_shortlist: { Row: ShortlistRow; Relationships: [] };
      v_company_detail: { Row: CompanyDetailRow; Relationships: [] };
      v_watchlist: { Row: WatchlistRow; Relationships: [] };
    };
    Functions: Record<string, never>;
    Enums: Record<string, never>;
    CompositeTypes: Record<string, never>;
  };
};
