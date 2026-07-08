"""Calibration audit — spec 04 §4.

Monthly job: re-score a fixed benchmark set (chosen once in Phase 0, never
changed) with the active rubric and alert if any LLM dimension moved more
than 1 point vs the stored baseline — this catches prompt/model drift before
it silently reorders the pipeline.

Baseline storage: spec 04 §4 says "store results in jobs.stats" without
pinning what "the stored baseline" is compared against on the very first
run, or whether it's a fixed Phase-0 anchor or a rolling "vs last audit"
comparison. This implementation uses a dedicated ``jobs`` row
(job_name=``score_calibration_baseline``, run_key=``baseline``, a single
row we read then overwrite) as a *rolling* baseline: each run compares
against the previous run's stored scores and then becomes the new baseline.
That's the interpretation that actually catches drift between consecutive
audits (a fixed Phase-0 anchor would eventually just measure "how much has
changed since launch", not "did something change since last month"). The
first-ever run has nothing to compare against, so it stores a baseline and
reports no drift.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cp_workers import db
from cp_workers.scoring import llm_dimensions, pipeline

# Deliberately calls llm_dimensions directly on a freshly-assembled profile
# rather than going through pipeline.score_company. score_company's
# profile_hash cache (spec 04 §3) is designed to make a *company's* unchanged
# profile skip the LLM call — exactly the opposite of what a drift audit
# needs. The benchmark set is chosen so its member companies' profiles are
# essentially static, which means routing this through the cache would very
# often just replay last month's cached LLM dimensions and never notice a
# prompt/model change at all. Bypassing the cache here is what makes this
# audit actually able to catch drift (spec 04 §4).
CALIBRATION_JOB_NAME = "score_calibration_baseline"
CALIBRATION_RUN_KEY = "baseline"
DRIFT_ALERT_THRESHOLD = 1.0


def _load_baseline(client) -> dict | None:
    resp = (
        client.table("jobs")
        .select("*")
        .eq("job_name", CALIBRATION_JOB_NAME)
        .eq("run_key", CALIBRATION_RUN_KEY)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    return (resp.data[0].get("stats") or {}).get("scores")


def _store_baseline(client, scores: dict) -> None:
    now = datetime.now(timezone.utc).isoformat()
    existing = (
        client.table("jobs")
        .select("*")
        .eq("job_name", CALIBRATION_JOB_NAME)
        .eq("run_key", CALIBRATION_RUN_KEY)
        .limit(1)
        .execute()
    )
    stats_payload = {"scores": scores, "updated_at": now}
    if existing.data:
        client.table("jobs").update(
            {"status": "succeeded", "finished_at": now, "stats": stats_payload}
        ).eq("id", existing.data[0]["id"]).execute()
    else:
        client.table("jobs").insert(
            {
                "job_name": CALIBRATION_JOB_NAME,
                "run_key": CALIBRATION_RUN_KEY,
                "status": "succeeded",
                "started_at": now,
                "finished_at": now,
                "stats": stats_payload,
            }
        ).execute()


def run_calibration_audit(benchmark_company_numbers: list[str], *, llm_client: Any = None) -> dict:
    """Re-score the benchmark set, diff LLM dimensions vs the stored
    baseline, and roll the baseline forward. Never raises for a single
    company's scoring failure — it's collected in ``errors`` instead.
    """
    client = db.get_client()
    baseline = _load_baseline(client) or {}

    current_scores: dict[str, dict[str, float | None]] = {}
    errors: list[dict] = []

    for company_number in benchmark_company_numbers:
        try:
            company = db.get_company_by_number(company_number)
            if company is None:
                raise ValueError(f"unknown company_number={company_number!r}")
            profile = pipeline._assemble_profile(client, company)
            llm_result = llm_dimensions.score_qualitative_dimensions(profile, client=llm_client)
            current_scores[company_number] = {
                name: (llm_result["dimensions"].get(name) or {}).get("raw_score")
                for name in llm_dimensions.LLM_DIMENSION_NAMES
            }
        except Exception as exc:  # noqa: BLE001 - one company's failure must not abort the audit
            errors.append({"company_number": company_number, "error": str(exc)})

    drifted: list[dict] = []
    for company_number, dims in current_scores.items():
        baseline_dims = baseline.get(company_number) or {}
        for dim_name, current_value in dims.items():
            baseline_value = baseline_dims.get(dim_name)
            if current_value is None or baseline_value is None:
                continue
            delta = abs(current_value - baseline_value)
            if delta > DRIFT_ALERT_THRESHOLD:
                drifted.append(
                    {
                        "company_number": company_number,
                        "dimension": dim_name,
                        "baseline": baseline_value,
                        "current": current_value,
                        "delta": round(delta, 2),
                    }
                )

    _store_baseline(client, current_scores)

    return {
        "benchmark_size": len(benchmark_company_numbers),
        "scored": len(current_scores),
        "errors": errors,
        "drifted": drifted,
        "alert": bool(drifted),
        "scores": current_scores,
        "had_prior_baseline": bool(baseline),
    }
