"""Pre-gate (spec 09) — free-data triage that decides who earns enrichment.

The universe is tens of thousands of H/W/B companies; enrichment costs compute
and LLM spend per company. This scorer uses ONLY data already in the DB from
Companies House (£0): succession signals, iXBRL-derived size band, taxonomy
confidence, and foundations. `run_pregate()` persists the score + component
detail on `companies`; `enrichment_candidates()` is the budgeted promotion
query used by `cli.py enrich --pending`.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from cp_workers import db

DEFAULT_WEIGHTS = {"succession": 0.40, "size_fit": 0.25, "sector_confidence": 0.20, "foundations": 0.15}

_SIZE_FIT = {"fit-now": 1.0, "stretch": 0.6, "unknown": 0.5, "too-small": 0.0, "too-large": 0.0}
_SECTOR_CONF = {"rules": 1.0, "manual": 1.0, "llm": 0.7}
_SUCCESSION_SIGNALS = ("director_retirement_window", "long_single_owner_tenure", "board_psc_event_recent")


def _company_age_years(incorporation_date, now: date) -> float | None:
    if incorporation_date is None:
        return None
    if isinstance(incorporation_date, str):
        try:
            incorporation_date = date.fromisoformat(incorporation_date[:10])
        except ValueError:
            return None
    if isinstance(incorporation_date, datetime):
        incorporation_date = incorporation_date.date()
    return round((now - incorporation_date).days / 365.25, 2)


def compute_pregate(
    company: dict,
    succession_values: dict[str, float],
    *,
    weights: dict | None = None,
    min_age_years: float = 8.0,
    now: date | None = None,
) -> tuple[float, dict]:
    """Pure scorer: (pregate_score 0-1, per-component detail). No I/O."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    now = now or datetime.now(timezone.utc).date()

    # Succession readiness — the proprietary ordering (spec 09 §4).
    succession = max((succession_values.get(name, 0.0) or 0.0 for name in _SUCCESSION_SIGNALS), default=0.0)

    size_fit = _SIZE_FIT.get(company.get("size_band") or "unknown", 0.5)

    if "needs-review" in (company.get("sector_tags") or []):
        sector_confidence = 0.4
    else:
        sector_confidence = _SECTOR_CONF.get(company.get("sector_tag_source") or "", 0.7)

    # Foundations: established + active + solvent-looking, from free filings.
    age = _company_age_years(company.get("incorporation_date"), now)
    parts = []
    parts.append(1.0 if (age is not None and age >= min_age_years) else 0.0)
    parts.append(1.0 if company.get("company_status") == "active" else 0.0)
    net_assets = (company.get("balance_sheet") or {}).get("net_assets")
    parts.append(0.5 if net_assets is None else (1.0 if net_assets > 0 else 0.0))
    foundations = round(sum(parts) / len(parts), 4)

    components = {
        "succession": round(succession, 4),
        "size_fit": size_fit,
        "sector_confidence": sector_confidence,
        "foundations": foundations,
    }
    score = round(sum(components[k] * w[k] for k in components), 4)
    detail = {
        "components": components,
        "weights": w,
        "inputs": {
            "succession_values": {k: succession_values.get(k) for k in _SUCCESSION_SIGNALS},
            "size_band": company.get("size_band"),
            "sector_tag_source": company.get("sector_tag_source"),
            "company_age_years": age,
            "net_assets": net_assets,
        },
    }
    return score, detail


def _latest_succession_values(client, company_id: str) -> dict[str, float]:
    resp = (
        client.table("signals")
        .select("name,value,computed_at")
        .eq("company_id", company_id)
        .eq("family", "succession")
        .order("computed_at", desc=True)
        .execute()
    )
    values: dict[str, float] = {}
    for row in resp.data or []:
        if row["name"] not in values:
            values[row["name"]] = row.get("value") or 0.0
    return values


def run_pregate(*, company_numbers: list[str] | None = None) -> dict:
    """Compute + persist pregate_score for the given companies (default: all
    non-archived). Cheap enough to re-run over the whole universe whenever
    weights change."""
    client = db.get_client()
    weights = db.get_config("pregate_weights", DEFAULT_WEIGHTS)
    min_age = float(db.get_config("min_company_age_years", 8))

    if company_numbers is None:
        rows: list[dict] = []
        page = 0
        while True:
            resp = (
                client.table("companies")
                .select("id,company_number,size_band,sector_tags,sector_tag_source,incorporation_date,company_status,balance_sheet")
                .neq("lifecycle", "archived")
                .range(page * 1000, page * 1000 + 999)
                .execute()
            )
            batch = resp.data or []
            rows.extend(batch)
            if len(batch) < 1000:
                break
            page += 1
    else:
        rows = [c for n in company_numbers if (c := db.get_company_by_number(n)) is not None]

    stats = {"scored": 0, "eligible": 0, "failed": 0, "failures": []}
    threshold = float(db.get_config("pregate_threshold", 0.45))
    for company in rows:
        try:
            succession_values = _latest_succession_values(client, company["id"])
            score, detail = compute_pregate(company, succession_values, weights=weights, min_age_years=min_age)
            client.table("companies").update({"pregate_score": score, "pregate_detail": detail}).eq(
                "id", company["id"]
            ).execute()
            stats["scored"] += 1
            if score >= threshold:
                stats["eligible"] += 1
        except Exception as exc:  # noqa: BLE001
            stats["failed"] += 1
            stats["failures"].append({"company_number": company.get("company_number"), "error": str(exc)[:300]})
    stats["threshold"] = threshold
    return stats


def enrichment_candidates(limit: int | None = None) -> list[str]:
    """Budgeted promotion (spec 09 §5): above-threshold, not yet enriched,
    ordered by pregate_score desc, capped at the weekly budget."""
    client = db.get_client()
    threshold = float(db.get_config("pregate_threshold", 0.45))
    budget = int(limit if limit is not None else db.get_config("enrichment_budget_per_week", 150))
    resp = (
        client.table("companies")
        .select("company_number,pregate_score")
        .eq("lifecycle", "discovered")
        .gte("pregate_score", threshold)
        .order("pregate_score", desc=True)
        .limit(budget)
        .execute()
    )
    return [r["company_number"] for r in (resp.data or [])]
