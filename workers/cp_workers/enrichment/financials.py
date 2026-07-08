"""Financial estimation (spec 03 §7).

Micro/small filers hide P&L behind abbreviated accounts, so for most of the
universe we only have balance-sheet facts + employee count. This module fills
the gap with sector benchmark ratios where a full P&L isn't available, and
falls back to parsed iXBRL figures (`method: "filed"`, `confidence: "high"`)
when they are.

**Never present these as filed facts** — every output carries `method` and
`confidence` so the UI can badge estimates (spec 00 / 03 §7).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

# Benchmark ratio table — revenue-per-employee (GBP) and EBITDA margin ranges
# for skincare / personal-care, the spec 00 §1 launch sector.
#
# Sources (researched at seed time, confidence: med — small-sample UK indie
# beauty/personal-care brands vary widely; treat as a plausible range, not a
# precise figure):
#   - ONS Annual Business Survey, non-financial business economy by industry
#     (SIC 20.42 "Manufacture of perfumes and toilet preparations"), latest
#     published GVA/employee figures for small manufacturing enterprises.
#   - IBISWorld UK industry report "Cosmetics & Toiletries Manufacturing"
#     (typical EBITDA margin band for small-to-mid manufacturers).
#   - Practitioner priors from independent DTC beauty brand sale comps
#     (revenue-per-employee tends to run higher than manufacturing-only
#     comparables because much of headcount is lean/outsourced production).
#
# All figures are GBP, ranges expressed as (low, mid, high).
SECTOR_BENCHMARKS: dict[str, dict[str, tuple[float, float, float]]] = {
    "skincare-personal-care": {
        "revenue_per_employee_gbp": (80_000.0, 140_000.0, 220_000.0),
        "ebitda_margin": (0.05, 0.12, 0.20),
    },
    # Fallback bucket for sector tags we don't have a researched benchmark for yet.
    "default": {
        "revenue_per_employee_gbp": (70_000.0, 120_000.0, 180_000.0),
        "ebitda_margin": (0.04, 0.10, 0.16),
    },
}


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _estimate_shape(
    value_pence: int,
    *,
    source: str,
    method: str,
    confidence: str,
    as_of: str | None = None,
) -> dict[str, Any]:
    return {
        "value_pence": int(value_pence),
        "source": source,
        "method": method,
        "confidence": confidence,
        "as_of": as_of or _today_iso(),
    }


def estimate_financials(
    balance_sheet: dict[str, Any] | None,
    employee_count: int | None,
    sector_tag: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Estimate revenue and EBITDA for a company.

    Returns `(revenue_estimate, ebitda_estimate)`, each shaped
    `{"value_pence": int, "source": str, "method": "benchmark"|"filed",
    "confidence": "high"|"med"|"low", "as_of": str}`.

    Prefers filed P&L figures from `balance_sheet` (parsed iXBRL, spec 03 §7
    "medium/large filers: parse actual P&L ... confidence: high") when present;
    otherwise falls back to the sector benchmark table. Never raises: missing
    employee_count or sector_tag degrades to the lowest-confidence estimate
    rather than erroring, since micro filers routinely have thin data.
    """
    balance_sheet = balance_sheet or {}

    filed_revenue = balance_sheet.get("turnover_pence") or balance_sheet.get("revenue_pence")
    filed_ebitda = balance_sheet.get("ebitda_pence") or balance_sheet.get("operating_profit_pence")

    as_of = balance_sheet.get("as_of") or _today_iso()

    if filed_revenue is not None and filed_ebitda is not None:
        revenue_estimate = _estimate_shape(
            filed_revenue, source="ixbrl_accounts", method="filed", confidence="high", as_of=as_of
        )
        ebitda_estimate = _estimate_shape(
            filed_ebitda, source="ixbrl_accounts", method="filed", confidence="high", as_of=as_of
        )
        return revenue_estimate, ebitda_estimate

    benchmarks = SECTOR_BENCHMARKS.get(sector_tag or "", SECTOR_BENCHMARKS["default"])
    rev_low, rev_mid, rev_high = benchmarks["revenue_per_employee_gbp"]
    margin_low, margin_mid, margin_high = benchmarks["ebitda_margin"]

    if not employee_count or employee_count <= 0:
        # No headcount at all: lowest-confidence placeholder, still shaped correctly
        # so downstream code never has to special-case a missing estimate.
        revenue_estimate = _estimate_shape(
            0, source="sector_benchmark", method="benchmark", confidence="low", as_of=as_of
        )
        ebitda_estimate = _estimate_shape(
            0, source="sector_benchmark", method="benchmark", confidence="low", as_of=as_of
        )
        return revenue_estimate, ebitda_estimate

    revenue_gbp = rev_mid * employee_count
    revenue_pence = int(round(revenue_gbp * 100))
    ebitda_pence = int(round(revenue_pence * margin_mid))

    # Confidence: "med" when we at least have a real employee_count and sector
    # tag to key the benchmark off, "low" if we fell back to the default bucket
    # (i.e. sector wasn't in the researched table).
    confidence = "med" if sector_tag in SECTOR_BENCHMARKS else "low"

    revenue_estimate = _estimate_shape(
        revenue_pence,
        source=f"sector_benchmark:{sector_tag or 'default'}:revenue_per_employee(low={rev_low},high={rev_high})",
        method="benchmark",
        confidence=confidence,
        as_of=as_of,
    )
    ebitda_estimate = _estimate_shape(
        ebitda_pence,
        source=f"sector_benchmark:{sector_tag or 'default'}:ebitda_margin(low={margin_low},high={margin_high})",
        method="benchmark",
        confidence=confidence,
        as_of=as_of,
    )
    return revenue_estimate, ebitda_estimate
