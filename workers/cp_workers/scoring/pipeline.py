"""Scoring orchestration — spec 04 §1, §7. ``score_company`` ties gate,
rules dimensions, red flags, LLM dimensions, and value angles together in
cost order and persists the result.

--------------------------------------------------------------------------
PROFILE SCHEMA (the ``profile: dict`` passed to gate.py / dimensions.py /
red_flags.py / value_angles.py)
--------------------------------------------------------------------------
Assembled by ``_assemble_profile`` below from data that already exists in
the schema today. Several fields spec 04 implies (product type, ad-pixel
presence, e-commerce flag, dominant channel share, "recently funded",
"unadvised") have **no dedicated column or guaranteed evidence shape yet** —
Agent A/B's connectors, enrichment extraction, and signal evidence payloads
are being built in parallel and their exact JSON shapes aren't pinned by
CONTRACT.md beyond function signatures. Where this module can't be sure a
field exists, it degrades to `None`/`False` (documented per-field below)
rather than guessing — consistent with "never silently drop for missing
data". This is flagged explicitly in the build report for the integration
pass to reconcile once Agent B's actual evidence/extraction shapes land.

Field -> source:
  sector_tags, sector_tag_source, company_status, region, balance_sheet,
  employee_count, revenue_estimate, ebitda_estimate, digital_maturity,
  website, summary, company_age_years   <- `companies` row (direct columns)
  succession_signals, succession_signal_max,
  fragmented_subcategory, adjacency      <- latest `signals` rows (value)
  review_strength, review_trend          <- evidence of `reviews_strong_digital_weak`
  narrow_distribution, notable_stockists_count,
  marketplace_presence, distribution_breadth <- `narrow_distribution` signal + evidence
  brand_recognition_evidence             <- evidence of `heritage_underexploited`
  website_text                           <- latest `source_records` (source=website_crawl), best-effort flatten
  review_summary                         <- latest `source_records` (source=trustpilot/google_reviews)
  team_evidence_present                  <- heuristic over `company_people` (>=2 distinct active people)
  unadvised                              <- heuristic keyword check over website_text (documented, no dedicated field)
  product_type                           <- heuristic (tech keyword scan + sector tag presence); no dedicated column
  insolvency_events, pre_revenue, shrinking, plausibly_profitable,
  recently_funded, net_assets_shrinking, employee_count_falling,
  ad_pixels_present, has_ecommerce, dominant_channel_share,
  owner_not_willing_manual               <- NO current source; default None/False (documented gap)
  country                                <- "UK" (universe is UK-registered by construction, spec 02 §2)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from cp_workers import db
from cp_workers.scoring import dimensions, gate, llm_dimensions, red_flags, value_angles

RULES_DIMENSION_NAMES = (
    "financial_quality",
    "deal_accessibility",
    "market_consolidation",
    "latent_digital_upside",
)

ADVISOR_KEYWORDS = (
    "corporate finance adviser",
    "corporate finance advisor",
    "m&a adviser",
    "m&a advisor",
    "business broker",
    "advised by",
    "sale process managed by",
)

TECH_PRODUCT_KEYWORDS = (
    "saas",
    "software platform",
    "mobile app",
    "web app",
    "api platform",
    "subscription software",
)

_COMPLETENESS_FIELDS = {
    "balance_sheet": 2,
    "employee_count": 1,
    "revenue_estimate": 1,
    "ebitda_estimate": 1,
    "digital_maturity": 2,
    "review_strength": 2,
    "narrow_distribution": 1,
    "fragmented_subcategory": 1,
    "succession_signal_max": 2,
    "website_text": 2,
    "sector_tags": 1,
    "company_age_years": 1,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_years(incorporation_date: Any) -> float | None:
    if not incorporation_date:
        return None
    if isinstance(incorporation_date, str):
        try:
            incorporation_date = date.fromisoformat(incorporation_date[:10])
        except ValueError:
            return None
    if isinstance(incorporation_date, datetime):
        incorporation_date = incorporation_date.date()
    if not isinstance(incorporation_date, date):
        return None
    now = datetime.now(timezone.utc).date()
    return round((now - incorporation_date).days / 365.25, 2)


def _latest_signals(client, company_id: str) -> dict[str, dict]:
    resp = (
        client.table("signals")
        .select("*")
        .eq("company_id", company_id)
        .order("computed_at", desc=True)
        .execute()
    )
    latest: dict[str, dict] = {}
    for row in resp.data or []:
        name = row.get("name")
        if name and name not in latest:
            latest[name] = row
    return latest


def _company_people(client, company_id: str) -> list[dict]:
    resp = client.table("company_people").select("*").eq("company_id", company_id).execute()
    return resp.data or []


def _infer_team_evidence(people: list[dict]) -> bool:
    active_person_ids = {p["person_id"] for p in people if p.get("is_active")}
    return len(active_person_ids) >= 2


def _flatten_website_raw(raw: Any) -> str | None:
    if isinstance(raw, str):
        return raw or None
    if isinstance(raw, dict):
        if isinstance(raw.get("text"), str):
            return raw["text"]
        texts = [v for v in raw.values() if isinstance(v, str) and v.strip()]
        if texts:
            return "\n\n".join(texts)
    return None


def _latest_enrichment_text(client, company_id: str) -> tuple[str | None, str | None]:
    website_text = None
    resp = (
        client.table("source_records")
        .select("*")
        .eq("company_id", company_id)
        .eq("source", "website_crawl")
        .order("fetched_at", desc=True)
        .limit(1)
        .execute()
    )
    if resp.data:
        website_text = _flatten_website_raw(resp.data[0].get("raw"))

    review_bits: list[str] = []
    for source in ("trustpilot", "google_reviews"):
        resp = (
            client.table("source_records")
            .select("*")
            .eq("company_id", company_id)
            .eq("source", source)
            .order("fetched_at", desc=True)
            .limit(1)
            .execute()
        )
        if resp.data:
            raw = resp.data[0].get("raw") or {}
            rating = raw.get("rating") if isinstance(raw, dict) else None
            count = raw.get("count") or raw.get("review_count") if isinstance(raw, dict) else None
            if rating is not None or count is not None:
                review_bits.append(f"{source}: rating={rating}, count={count}")
    review_summary = "; ".join(review_bits) if review_bits else None
    return website_text, review_summary


def _infer_unadvised(website_text: str | None) -> bool:
    if not website_text:
        return True
    lowered = website_text.lower()
    return not any(kw in lowered for kw in ADVISOR_KEYWORDS)


def _infer_product_type(sector_tags: list[str], website_text: str | None) -> str:
    lowered = (website_text or "").lower()
    if any(kw in lowered for kw in TECH_PRODUCT_KEYWORDS):
        return "tech_product"
    if sector_tags:
        return "physical_product"
    return "ambiguous"


def _assemble_profile(client, company: dict) -> dict:
    company_id = company["id"]
    sector_tags = company.get("sector_tags") or []

    signals_by_name = _latest_signals(client, company_id)
    succession_signals = {
        name: row["value"] for name, row in signals_by_name.items() if row.get("family") == "succession"
    }

    fragmented_row = signals_by_name.get("fragmented_subcategory")
    adjacency_row = signals_by_name.get("adjacency")
    reviews_row = signals_by_name.get("reviews_strong_digital_weak")
    narrow_dist_row = signals_by_name.get("narrow_distribution")
    heritage_row = signals_by_name.get("heritage_underexploited")

    review_evidence = (reviews_row or {}).get("evidence") or {}
    dist_evidence = (narrow_dist_row or {}).get("evidence") or {}
    heritage_evidence = (heritage_row or {}).get("evidence") or {}

    website_text, review_summary = _latest_enrichment_text(client, company_id)
    people = _company_people(client, company_id)

    profile: dict[str, Any] = {
        "sector_tags": sector_tags,
        "sector_tag_source": company.get("sector_tag_source"),
        "company_status": company.get("company_status"),
        "region": company.get("region"),
        "country": "UK",
        "balance_sheet": company.get("balance_sheet"),
        "employee_count": company.get("employee_count"),
        "revenue_estimate": company.get("revenue_estimate"),
        "ebitda_estimate": company.get("ebitda_estimate"),
        "digital_maturity": company.get("digital_maturity"),
        "website": company.get("website"),
        "summary": company.get("summary"),
        "company_age_years": _age_years(company.get("incorporation_date")),
        "succession_signals": succession_signals,
        "succession_signal_max": max(succession_signals.values(), default=None)
        if succession_signals
        else None,
        "fragmented_subcategory": fragmented_row["value"] if fragmented_row else None,
        "adjacency": adjacency_row["value"] if adjacency_row else None,
        "review_strength": review_evidence.get("review_strength"),
        "review_trend": review_evidence.get("review_trend"),
        "narrow_distribution": narrow_dist_row["value"] if narrow_dist_row else None,
        "notable_stockists_count": dist_evidence.get("notable_stockists_count"),
        "marketplace_presence": dist_evidence.get("marketplace_presence"),
        "distribution_breadth": dist_evidence.get("distribution_breadth")
        or review_evidence.get("distribution_breadth"),
        "brand_recognition_evidence": heritage_evidence.get("brand_recognition_evidence"),
        "website_text": website_text,
        "review_summary": review_summary,
        "team_evidence_present": _infer_team_evidence(people),
        # documented gaps — no dedicated source yet, default to conservative "no evidence":
        "insolvency_events": False,
        "pre_revenue": False,
        "shrinking": False,
        "plausibly_profitable": None,
        "recently_funded": False,
        "net_assets_shrinking": False,
        "employee_count_falling": False,
        "ad_pixels_present": None,
        "has_ecommerce": None,
        "dominant_channel_share": None,
        "owner_not_willing_manual": False,
    }
    profile["unadvised"] = _infer_unadvised(website_text)
    profile["product_type"] = _infer_product_type(sector_tags, website_text)
    profile["latent_digital_upside_raw"] = None  # filled in after dimensions.latent_digital_upside runs
    profile["structured"] = {
        k: v for k, v in profile.items() if k not in ("website_text", "review_summary", "structured")
    }
    return profile


def _get_rubric(client, rubric_version: str | None) -> dict:
    query = client.table("rubric_versions").select("*")
    if rubric_version:
        query = query.eq("version", rubric_version)
    else:
        query = query.eq("active", True)
    resp = query.limit(1).execute()
    if not resp.data:
        raise ValueError(f"no rubric_versions row found (version={rubric_version!r})")
    return resp.data[0]


def _find_cached_score(client, company_id: str, profile_hash: str, rubric_version: str) -> dict | None:
    resp = (
        client.table("scores")
        .select("*")
        .eq("company_id", company_id)
        .eq("profile_hash", profile_hash)
        .eq("rubric_version", rubric_version)
        .order("scored_at", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def _load_score_dimensions(client, score_id: str) -> list[dict]:
    resp = client.table("score_dimensions").select("*").eq("score_id", score_id).execute()
    return resp.data or []


def _compute_data_completeness(profile: dict) -> float:
    total_weight = sum(_COMPLETENESS_FIELDS.values())
    if not total_weight:
        return 0.0
    filled = 0
    for field, weight in _COMPLETENESS_FIELDS.items():
        value = profile.get(field)
        if value not in (None, [], {}, ""):
            filled += weight
    return round(filled / total_weight, 2)


def _compute_total_score(dim_raw_scores: dict[str, float | None], weights: dict[str, float]) -> float | None:
    """Weighted sum over dimensions with a raw score, renormalised over the
    weight actually covered — so a company with an incomplete LLM call still
    gets a comparable 0-100 score rather than an artificially low one, while
    ``data_completeness`` on the score row makes the gap visible in the UI.
    """
    total_weight = 0.0
    weighted_sum = 0.0
    for dim, weight in weights.items():
        raw = dim_raw_scores.get(dim)
        if raw is None:
            continue
        total_weight += weight
        weighted_sum += weight * (raw / 5.0)
    if total_weight == 0:
        return None
    return round((weighted_sum / total_weight) * 100, 2)


def _upsert_pipeline_item(client, company_id: str) -> None:
    existing = client.table("pipeline_items").select("*").eq("company_id", company_id).limit(1).execute()
    if not existing.data:
        client.table("pipeline_items").insert({"company_id": company_id, "stage": "inbox"}).execute()
        return
    row = existing.data[0]
    if row.get("stage") == "inbox":
        client.table("pipeline_items").update({"stage_changed_at": _now_iso()}).eq(
            "company_id", company_id
        ).execute()
    # else: company already progressed beyond inbox (review/shortlist/watchlist/
    # pursue/passed) via a human decision — never regress it back to inbox.


def _reconstruct_result(company: dict, score_row: dict, dimension_rows: list[dict]) -> dict:
    dims = {
        row["dimension"]: {
            "raw_score": row["raw_score"],
            "evidence": row["evidence"],
            "rationale": row["rationale"],
            "method": row["method"],
        }
        for row in dimension_rows
    }
    return {
        "company_id": company["id"],
        "company_number": company["company_number"],
        "rubric_version": score_row["rubric_version"],
        "gate_result": score_row["gate_result"],
        "gate_detail": score_row["gate_detail"],
        "total_score": score_row["total_score"],
        "red_flags": score_row["red_flags"],
        "value_angles": score_row["value_angles"],
        "data_completeness": score_row["data_completeness"],
        "dimensions": dims,
        "profile_hash": score_row["profile_hash"],
        "used_cache": True,
        "score_id": score_row["id"],
    }


def score_company(company_number: str, rubric_version: str | None = None, *, llm_client: Any = None) -> dict:
    """Score one company end to end (spec 04 §1, §7).

    Cost order: gate + rules dimensions first (free) -> rules-based red flags
    (before any LLM call, so a held/failed company never triggers one) ->
    LLM dimensions only for gate-passers, with a profile_hash cache check
    first -> value angles -> persist.

    ``llm_client`` lets callers/tests inject a mock Anthropic-shaped client;
    passed straight through to ``llm_dimensions`` and the value-angle
    tie-break call.
    """
    client = db.get_client()
    company = db.get_company_by_number(company_number)
    if company is None:
        raise ValueError(f"unknown company_number={company_number!r}")

    rubric = _get_rubric(client, rubric_version)
    weights: dict[str, float] = rubric["weights"]
    gate_config: dict = rubric["gate_config"]

    profile = _assemble_profile(client, company)

    size_band = gate.compute_size_band(
        profile.get("ebitda_estimate"),
        profile.get("revenue_estimate"),
        profile.get("balance_sheet"),
        profile.get("employee_count"),
        gate_config.get("size_band_thresholds", {}),
    )
    profile["size_band"] = size_band

    gate_result = gate.run_gate(profile, gate_config)

    # --- rules dimensions: free, always computed regardless of gate result ---
    fq_raw, fq_evidence, fq_rationale = dimensions.financial_quality(
        profile.get("balance_sheet"),
        profile.get("revenue_estimate"),
        profile.get("ebitda_estimate"),
        profile.get("employee_count"),
    )
    da_raw, da_evidence, da_rationale = dimensions.deal_accessibility(
        profile.get("succession_signals", {}), profile.get("unadvised", False)
    )
    mc_raw, mc_evidence, mc_rationale = dimensions.market_consolidation(
        profile.get("fragmented_subcategory"), profile.get("adjacency")
    )
    ldu_raw, ldu_evidence, ldu_rationale = dimensions.latent_digital_upside(
        profile.get("review_strength"), profile.get("digital_maturity"), profile.get("distribution_breadth")
    )
    profile["latent_digital_upside_raw"] = ldu_raw

    rules_dims = {
        "financial_quality": (fq_raw, fq_evidence, fq_rationale, "rules"),
        "deal_accessibility": (da_raw, da_evidence, da_rationale, "rules"),
        "market_consolidation": (mc_raw, mc_evidence, mc_rationale, "rules"),
        "latent_digital_upside": (ldu_raw, ldu_evidence, ldu_rationale, "rules"),
    }

    # --- red flags: rules pass runs before any LLM call (spec 04 §1) ---
    rules_flags, _flags_evidence = red_flags.detect_rules_red_flags(profile)

    profile_hash = db.content_hash(profile)
    data_completeness = _compute_data_completeness(profile)

    cached_row = None
    if gate_result["result"] == "pass":
        cached_row = _find_cached_score(client, company["id"], profile_hash, rubric["version"])

    if cached_row:
        dimension_rows = _load_score_dimensions(client, cached_row["id"])
        result = _reconstruct_result(company, cached_row, dimension_rows)
    else:
        llm_dims: dict[str, tuple | None] = {name: None for name in llm_dimensions.LLM_DIMENSION_NAMES}
        llm_call_flags: dict = {}
        prompt_hash = None
        scoring_incomplete = False

        if gate_result["result"] == "pass":
            llm_result = llm_dimensions.score_qualitative_dimensions(profile, client=llm_client)
            prompt_hash = llm_result["prompt_hash"]
            scoring_incomplete = llm_result["scoring_incomplete"]
            for name in llm_dimensions.LLM_DIMENSION_NAMES:
                dim = llm_result["dimensions"].get(name)
                if dim:
                    llm_dims[name] = (
                        dim["raw_score"],
                        {"evidence": dim["evidence"]},
                        dim["rationale"],
                        "llm",
                    )
            llm_call_flags = llm_result.get("flags", {})

        final_flags = red_flags.merge_llm_red_flags(rules_flags, llm_call_flags)
        if scoring_incomplete and "scoring-incomplete" not in final_flags:
            final_flags = final_flags + ["scoring-incomplete"]

        all_dims = dict(rules_dims)
        for name, val in llm_dims.items():
            if val is not None:
                all_dims[name] = val

        dim_raw_scores = {name: vals[0] for name, vals in all_dims.items()}

        total_score = None
        value_angles_selected: list[str] = []
        if gate_result["result"] == "pass":
            total_score = _compute_total_score(dim_raw_scores, weights)
            qualifying = value_angles.qualifying_value_angles(profile)
            tie_break = lambda q, p: value_angles.llm_tie_break_value_angles(q, p, client=llm_client)  # noqa: E731
            value_angles_selected = value_angles.select_value_angles(qualifying, profile, llm_tie_break=tie_break)

        score_row = {
            "company_id": company["id"],
            "rubric_version": rubric["version"],
            "gate_result": gate_result["result"],
            "gate_detail": gate_result["detail"],
            "total_score": total_score,
            "red_flags": final_flags,
            "value_angles": value_angles_selected,
            "profile_hash": profile_hash,
            "data_completeness": data_completeness,
        }
        inserted = client.table("scores").insert(score_row).execute().data[0]

        dimension_rows = []
        for name, (raw_score, evidence, rationale, method) in all_dims.items():
            weighted = None
            if raw_score is not None:
                weighted = round((raw_score / 5.0) * weights.get(name, 0), 2)
            dimension_rows.append(
                {
                    "score_id": inserted["id"],
                    "dimension": name,
                    "raw_score": raw_score,
                    "weighted": weighted,
                    "method": method,
                    "rationale": rationale,
                    "evidence": evidence,
                    "prompt_hash": prompt_hash if method == "llm" else None,
                }
            )
        if dimension_rows:
            client.table("score_dimensions").insert(dimension_rows).execute()

        result = _reconstruct_result(company, {**score_row, "id": inserted["id"]}, dimension_rows)
        result["used_cache"] = False

    client.table("companies").update({"lifecycle": "scored", "size_band": size_band}).eq(
        "id", company["id"]
    ).execute()

    shortlist_threshold = gate_config.get("shortlist_threshold", 60)
    if (
        gate_result["result"] == "pass"
        and result["total_score"] is not None
        and result["total_score"] >= shortlist_threshold
    ):
        _upsert_pipeline_item(client, company["id"])

    return result
