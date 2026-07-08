"""Consolidation-family signal functions (spec 02 §4).

Pure functions returning ``(value: float 0-1, evidence: dict, rationale: str)``.
No I/O and no imports from other ``cp_workers`` modules.
"""
from __future__ import annotations

import statistics
from typing import Any

SignalResult = tuple[float, dict, str]

# How many comparable companies count as "fully fragmented" for the density
# component of the score. Tunable; not config-backed since it's an internal
# shape parameter of a rules signal rather than a business threshold.
_FRAGMENTED_DENSITY_CEILING = 20
_DOMINANT_PLAYER_MULTIPLE = 10
_DOMINANT_PENALTY_FACTOR = 0.35


def _size_proxy(company: dict) -> float | None:
    """Best-effort single number to compare company sizes by. Prefers
    employee_count (most reliably disclosed by small companies, spec 02 §1);
    falls back to a revenue estimate's pence value. Returns None (never a
    guess) if neither is available."""
    employee_count = company.get("employee_count")
    if isinstance(employee_count, (int, float)) and employee_count > 0:
        return float(employee_count)
    revenue_estimate = company.get("revenue_estimate") or {}
    value_pence = revenue_estimate.get("value_pence") if isinstance(revenue_estimate, dict) else None
    if isinstance(value_pence, (int, float)) and value_pence > 0:
        return float(value_pence)
    return None


def fragmented_subcategory(universe_companies: list[dict], target: dict) -> SignalResult:
    """Count of universe companies sharing the sector tag within the target's
    size band; many small + no dominant player (no company > 10x median size)
    -> high (spec 02 §4)."""
    target_tags = set(target.get("sector_tags") or [])
    target_band = target.get("size_band")
    target_number = target.get("company_number")

    if not target_tags or not target_band or target_band == "unknown":
        return 0.0, {"matched_count": 0}, "target has no sector tag / size band to compare against"

    matched = [
        c
        for c in universe_companies
        if c.get("company_number") != target_number
        and set(c.get("sector_tags") or []) & target_tags
        and c.get("size_band") == target_band
    ]
    n = len(matched)
    if n == 0:
        return 0.0, {"matched_count": 0}, "no comparable companies share this sector tag and size band"

    sizes = [s for s in (_size_proxy(c) for c in matched) if s is not None]
    median_size = statistics.median(sizes) if sizes else None
    dominant = bool(median_size and median_size > 0 and any(s > median_size * _DOMINANT_PLAYER_MULTIPLE for s in sizes))

    density = min(n / _FRAGMENTED_DENSITY_CEILING, 1.0)
    value = round(density * (_DOMINANT_PENALTY_FACTOR if dominant else 1.0), 4)

    evidence: dict[str, Any] = {
        "matched_count": n,
        "sized_count": len(sizes),
        "median_size_proxy": median_size,
        "dominant_player_present": dominant,
    }
    rationale = (
        f"{n} comparable companies in size band '{target_band}'"
        + (", dominant player present -> discounted" if dominant else ", no dominant player")
    )
    return value, evidence, rationale


def adjacency(company: dict, portfolio_companies: list[dict]) -> SignalResult:
    """Shares stockists/channels/suppliers with a company already tagged
    'pursue' or portfolio-flagged. Stub until a portfolio exists (CONTRACT.md)
    — build the interface, not the logic. Always returns 0."""
    return 0.0, {}, "no portfolio yet"
