"""Rules-based attractiveness dimensions — spec 04 §3. No LLM, no network I/O.

Every function returns ``(raw_score_0_to_5: float, evidence: dict, rationale: str)``
per the shared signal-function convention (spec 02 §4 / CONTRACT.md preamble).

``latent_digital_upside`` is a thin wrapper around Agent B's
``cp_workers.signals.latent_upside.latent_digital_upside_dimension`` — that is
the *only* place the formula is implemented (spec 04 §3). The import is done
lazily inside the function body so that importing this module never fails
even before Agent B's file lands (it is being written in parallel); see the
module docstring in ``scoring/pipeline.py`` for how tests stub it.
"""
from __future__ import annotations

from typing import Any


def _clamp(value: float, lo: float = 0.0, hi: float = 5.0) -> float:
    return max(lo, min(hi, value))


def financial_quality(
    balance_sheet: dict | None,
    revenue_estimate: dict | None,
    ebitda_estimate: dict | None,
    employee_count: int | None = None,
    previous_balance_sheet: dict | None = None,
) -> tuple[float, dict, str]:
    """Net-asset trend, cash position, creditor ratio, confidence discount.

    Spec 04 §3: "from balance sheet + estimates — net-asset trend, cash
    position, creditor ratio, estimate confidence discount (score capped at 3
    when confidence low)". Missing inputs degrade the score toward a neutral
    midpoint rather than crashing or being treated as zero.
    """
    balance_sheet = balance_sheet or {}
    evidence: dict[str, Any] = {}
    components: list[float] = []

    net_assets = balance_sheet.get("net_assets")
    if net_assets is not None:
        components.append(5.0 if net_assets > 0 else 0.5)
        evidence["net_assets"] = net_assets

    if previous_balance_sheet and net_assets is not None:
        prev_net_assets = previous_balance_sheet.get("net_assets")
        if prev_net_assets is not None:
            trend = "improving" if net_assets > prev_net_assets else (
                "flat" if net_assets == prev_net_assets else "declining"
            )
            evidence["net_asset_trend"] = trend
            components.append({"improving": 5.0, "flat": 3.0, "declining": 1.0}[trend])

    cash = balance_sheet.get("cash")
    total_assets = balance_sheet.get("total_assets")
    if cash is not None and total_assets:
        cash_ratio = cash / total_assets if total_assets else 0
        evidence["cash_ratio"] = round(cash_ratio, 3)
        components.append(_clamp(cash_ratio * 10))
    elif cash is not None:
        evidence["cash"] = cash
        components.append(3.0 if cash > 0 else 1.0)

    creditors = balance_sheet.get("creditors")
    if creditors is not None and total_assets:
        creditor_ratio = creditors / total_assets if total_assets else 0
        evidence["creditor_ratio"] = round(creditor_ratio, 3)
        # lower creditor ratio is healthier
        components.append(_clamp(5 - creditor_ratio * 5))

    if not components:
        return (2.5, evidence, "no balance-sheet data available — neutral default score")

    raw = sum(components) / len(components)

    confidences = [
        est.get("confidence")
        for est in (revenue_estimate, ebitda_estimate)
        if est
    ]
    low_confidence = "low" in confidences
    if low_confidence:
        raw = min(raw, 3.0)
        evidence["confidence_capped"] = True

    raw = round(_clamp(raw), 2)
    rationale = (
        f"financial_quality={raw} from "
        f"{len(components)} component(s)"
        + (" (capped at 3 for low-confidence estimates)" if low_confidence else "")
    )
    return (raw, evidence, rationale)


def deal_accessibility(succession_signals: dict, unadvised: bool) -> tuple[float, dict, str]:
    """Direct mapping of the succession-family signal values + unadvised proxy.

    ``succession_signals`` is expected to be a mapping of signal name -> value
    (0-1), e.g. ``{"director_retirement_window": 0.8, "long_single_owner_tenure": 0.5,
    "board_psc_event_recent": 0.0}`` (spec 01 §3 signal names). We take the
    strongest signal as the primary driver — any one strong succession signal
    is meaningful on its own — and add a flat bonus if the company shows no
    broker/advisor involvement (more directly approachable).
    """
    succession_signals = succession_signals or {}
    values = [v for v in succession_signals.values() if v is not None]
    strongest = max(values) if values else 0.0

    raw = strongest * 5.0
    if unadvised:
        raw += 0.5

    raw = round(_clamp(raw), 2)
    evidence = {
        "succession_signals": succession_signals,
        "strongest_signal": strongest,
        "unadvised": unadvised,
    }
    rationale = f"deal_accessibility={raw} from strongest succession signal {strongest}" + (
        " + unadvised bonus" if unadvised else ""
    )
    return (raw, evidence, rationale)


def market_consolidation(
    fragmented_subcategory_value: float | None,
    adjacency_value: float | None,
) -> tuple[float, dict, str]:
    """From ``fragmented_subcategory`` + ``adjacency`` signals (spec 02 §4).

    ``adjacency`` is a stub returning 0 until a portfolio exists (Agent A) —
    weighted lower accordingly so an empty portfolio doesn't drag every score.
    """
    fragmented = fragmented_subcategory_value or 0.0
    adjacency = adjacency_value or 0.0

    raw = round(_clamp((fragmented * 0.7 + adjacency * 0.3) * 5.0), 2)
    evidence = {"fragmented_subcategory": fragmented, "adjacency": adjacency}
    rationale = f"market_consolidation={raw} from fragmented={fragmented}, adjacency={adjacency}"
    return (raw, evidence, rationale)


def latent_digital_upside(
    review_strength: float | None,
    digital_maturity: int | None,
    distribution_breadth: float | None,
) -> tuple[float, dict, str]:
    """Thin wrapper calling Agent B's ``latent_digital_upside_dimension``.

    Lazy import so this module can always be imported even if
    ``cp_workers.signals.latent_upside`` doesn't exist yet (parallel build).
    Missing inputs are treated conservatively (0 review strength, mid-range
    digital maturity, and 0 distribution breadth) rather than raising.
    """
    from cp_workers.signals.latent_upside import latent_digital_upside_dimension

    rs = review_strength if review_strength is not None else 0.0
    dm = digital_maturity if digital_maturity is not None else 3
    db = distribution_breadth if distribution_breadth is not None else 1.0

    raw = latent_digital_upside_dimension(rs, dm, db)
    raw = round(_clamp(float(raw)), 2)

    evidence = {
        "review_strength": rs,
        "digital_maturity": dm,
        "distribution_breadth": db,
        "review_strength_missing": review_strength is None,
        "digital_maturity_missing": digital_maturity is None,
        "distribution_breadth_missing": distribution_breadth is None,
    }
    rationale = (
        f"latent_digital_upside={raw} from review_strength={rs}, "
        f"digital_maturity={dm}, distribution_breadth={db}"
    )
    return (raw, evidence, rationale)
