"""Fit gate — spec 04 §2. Pure rules, no LLM, no network I/O.

``run_gate`` implements the six tests in the exact order of the spec table
(sector, product type, size, foundations, situation, geography). Every test
returns ``pass`` / ``hold`` / ``fail`` plus a human-readable reason; the
overall result is: any fail -> fail; else any hold -> hold; else pass.

The ``situation`` test never hard-fails (worst case is hold) and neither does
``geography`` in the spec table (its Fail column is empty) — both are
implemented so they can only return pass/hold.

**Missing data never causes a silent drop.** Where a test lacks the data to
decide, it returns ``hold`` (queued for a human look under "Held"), never
``fail`` and never a crash. ``compute_size_band`` in particular returns
``"unknown"`` (which gates to hold) rather than raising or guessing.

Profile keys read by this module (all optional; sourced upstream by
``scoring/pipeline.py`` — see that module's PROFILE SCHEMA comment for exactly
where each one comes from):

    sector_tags: list[str] | None
    sector_tag_source: str | None            ("rules" / "llm" / "manual")
    product_type: str | None                 ("physical_product" / "service" / "tech_product" / "ambiguous")
    ebitda_estimate: dict | None              ({"value_pence": int, "confidence": ...})
    revenue_estimate: dict | None
    balance_sheet: dict | None
    employee_count: int | None
    company_age_years: float | None
    company_status: str | None
    insolvency_events: bool
    pre_revenue: bool
    shrinking: bool                          (revenue/employee count trending down)
    plausibly_profitable: bool | None
    succession_signal_max: float | None       (max of the succession-family signal values)
    recently_funded: bool                    ("freshly-funded scaling founder" situation)
    country: str | None                      (defaults to "UK" — universe is UK-only by construction)

``gate_config`` is ``rubric_versions.gate_config`` (see 0007_seeds.sql), plus
two optional keys this module adds on top of the seeded shape since the seed
doesn't define them (documented, flagged in the build report):
``too_small_ebitda_min_gbp`` (floor below which size is "too-small") and
``launch_sector_tags`` / ``adjacent_sector_tags`` / ``excluded_sector_tags``
(sector allow/deny lists — the seed only carries this in `app_config.launch_sector_taxonomy`
and `taxonomy_rules`, not in `gate_config`; caller may merge it in).
"""
from __future__ import annotations

from typing import Any, TypedDict

# --- defaults for the two gate_config extensions not present in the seed ---
DEFAULT_TOO_SMALL_EBITDA_MIN_GBP = 150_000
DEFAULT_LAUNCH_SECTOR_TAGS = ["skincare-personal-care"]
DEFAULT_ADJACENT_SECTOR_TAGS: list[str] = []
DEFAULT_EXCLUDED_SECTOR_TAGS = ["software", "non-consumer"]

# Coarse, gate-only fallback ratios used solely to decide a size *band*
# when Agent B's proper estimates are absent. These are deliberately rough
# and never written back as the company's revenue/ebitda estimate.
FALLBACK_REVENUE_TO_EBITDA_MARGIN = 0.10  # 10% — conservative consumer-goods margin
FALLBACK_EBITDA_PER_EMPLOYEE_GBP = 15_000  # coarse per-head proxy for micro filers


class TestResult(TypedDict):
    result: str  # "pass" | "hold" | "fail"
    reason: str


class GateResult(TypedDict):
    result: str
    detail: dict[str, TestResult]


def _pass(reason: str) -> TestResult:
    return {"result": "pass", "reason": reason}


def _hold(reason: str) -> TestResult:
    return {"result": "hold", "reason": reason}


def _fail(reason: str) -> TestResult:
    return {"result": "fail", "reason": reason}


def _pence_to_gbp(value_pence: Any) -> float | None:
    if value_pence is None:
        return None
    try:
        return float(value_pence) / 100.0
    except (TypeError, ValueError):
        return None


def compute_size_band(
    ebitda_estimate: dict | None,
    revenue_estimate: dict | None,
    balance_sheet: dict | None,
    employee_count: int | None,
    thresholds: dict,
) -> str:
    """Spec 04 §2 size_band computation.

    Fallback chain: actual/estimated EBITDA -> revenue estimate (coarse margin)
    -> balance-sheet + employee heuristic -> ``"unknown"`` if all missing.
    Never raises; never returns anything but one of the five documented bands.
    """
    ebitda_gbp = _best_ebitda_gbp(ebitda_estimate, revenue_estimate, balance_sheet, employee_count)
    if ebitda_gbp is None:
        return "unknown"

    fit_now_max = thresholds.get("fit_now_ev_max_gbp")
    stretch_max = thresholds.get("stretch_ebitda_max_gbp")
    too_small_min = thresholds.get("too_small_ebitda_min_gbp", DEFAULT_TOO_SMALL_EBITDA_MIN_GBP)

    if fit_now_max is None or stretch_max is None:
        # Can't gate on size without both configured thresholds — hold, don't guess.
        return "unknown"

    if ebitda_gbp < too_small_min:
        return "too-small"
    if ebitda_gbp <= fit_now_max:
        return "fit-now"
    if ebitda_gbp <= stretch_max:
        return "stretch"
    return "too-large"


def _best_ebitda_gbp(
    ebitda_estimate: dict | None,
    revenue_estimate: dict | None,
    balance_sheet: dict | None,
    employee_count: int | None,
) -> float | None:
    if ebitda_estimate:
        value = _pence_to_gbp(ebitda_estimate.get("value_pence"))
        if value is not None:
            return value

    if revenue_estimate:
        revenue_gbp = _pence_to_gbp(revenue_estimate.get("value_pence"))
        if revenue_gbp is not None:
            return revenue_gbp * FALLBACK_REVENUE_TO_EBITDA_MARGIN

    if balance_sheet and employee_count:
        # Coarse heuristic for the dark end of the market (micro filers with no
        # P&L at all) — employee count is the most reliable free size proxy
        # (spec 02 §1). Only used when we have *some* balance-sheet evidence
        # the company is a going concern, to avoid inventing a size for shells.
        if balance_sheet.get("net_assets") is not None:
            return float(employee_count) * FALLBACK_EBITDA_PER_EMPLOYEE_GBP

    return None


def _test_sector(profile: dict, gate_config: dict) -> TestResult:
    sector_tags = profile.get("sector_tags") or []
    sector_tag_source = profile.get("sector_tag_source")

    excluded = set(gate_config.get("excluded_sector_tags", DEFAULT_EXCLUDED_SECTOR_TAGS))
    launch = set(gate_config.get("launch_sector_tags", DEFAULT_LAUNCH_SECTOR_TAGS))
    adjacent = set(gate_config.get("adjacent_sector_tags", DEFAULT_ADJACENT_SECTOR_TAGS))

    if "needs-review" in sector_tags or sector_tag_source == "needs-review":
        return _hold("sector tag needs-review (low classifier confidence)")

    if any(tag in excluded for tag in sector_tags):
        return _fail("sector tag is software/non-consumer")

    if any(tag in launch or tag in adjacent for tag in sector_tags):
        return _pass(f"sector tag in launch/adjacent set: {sector_tags}")

    if not sector_tags:
        return _hold("no sector tag assigned yet")

    return _fail(f"sector tag(s) {sector_tags} outside launch/adjacent set")


def _test_product_type(profile: dict, gate_config: dict) -> TestResult:
    product_type = profile.get("product_type")
    if product_type in ("physical_product", "service"):
        return _pass(f"product_type={product_type}")
    if product_type == "tech_product":
        return _fail("primarily a tech product")
    return _hold(f"product_type ambiguous or unknown ({product_type!r})")


def _test_size(profile: dict, gate_config: dict) -> TestResult:
    thresholds = gate_config.get("size_band_thresholds", {})
    size_band = profile.get("size_band")
    if size_band is None:
        size_band = compute_size_band(
            profile.get("ebitda_estimate"),
            profile.get("revenue_estimate"),
            profile.get("balance_sheet"),
            profile.get("employee_count"),
            thresholds,
        )

    if size_band == "fit-now":
        return _pass("size_band=fit-now")
    if size_band == "too-small":
        return _fail("size_band=too-small")
    if size_band in ("stretch", "too-large", "unknown"):
        return _hold(f"size_band={size_band}")
    return _hold(f"unrecognised size_band={size_band!r}")


def _test_foundations(profile: dict, gate_config: dict) -> TestResult:
    min_age = gate_config.get("min_company_age_years", 8)
    age = profile.get("company_age_years")
    status = profile.get("company_status")
    balance_sheet = profile.get("balance_sheet") or {}
    net_assets = balance_sheet.get("net_assets")
    insolvency_events = bool(profile.get("insolvency_events", False))
    pre_revenue = bool(profile.get("pre_revenue", False))
    shrinking = bool(profile.get("shrinking", False))
    plausibly_profitable = profile.get("plausibly_profitable")

    if pre_revenue:
        return _fail("pre-revenue")
    if insolvency_events:
        return _fail("insolvency event(s) in filing history")
    if net_assets is not None and net_assets < 0 and shrinking:
        return _fail("negative net assets and shrinking")

    if age is None or status is None or net_assets is None:
        return _hold("thin data: missing one of age/status/net-assets")

    if age >= min_age and status == "active" and (net_assets > 0 or plausibly_profitable):
        return _pass(f"age={age}, status={status}, net_assets={net_assets}")

    if age < min_age:
        return _hold(f"age {age} below min {min_age}")
    if status != "active":
        return _hold(f"company_status={status}")

    return _hold("net assets not positive and not plausibly profitable")


def _test_situation(profile: dict, gate_config: dict) -> TestResult:
    """Never fails — worst case is hold, per spec 04 §2."""
    floor = gate_config.get("situation_succession_signal_floor", 0.3)
    succession_signal = profile.get("succession_signal_max")
    recently_funded = bool(profile.get("recently_funded", False))

    if recently_funded:
        return _hold("freshly-funded scaling founder")
    if succession_signal is not None and succession_signal >= floor:
        return _pass(f"succession_signal_max={succession_signal} >= {floor}")
    return _hold("no strong succession signal or approachability evidence yet")


def _test_geography(profile: dict, gate_config: dict) -> TestResult:
    """No fail case per spec 04 §2 (Fail column is empty) — pass or hold only."""
    country = profile.get("country", "UK")
    if country == "UK":
        return _pass("UK-registered")
    return _hold(f"footprint outside UK ({country})")


_TEST_FNS = {
    "sector": _test_sector,
    "product_type": _test_product_type,
    "size": _test_size,
    "foundations": _test_foundations,
    "situation": _test_situation,
    "geography": _test_geography,
}


def run_gate(profile: dict, gate_config: dict) -> GateResult:
    detail: dict[str, TestResult] = {}
    for name, fn in _TEST_FNS.items():
        detail[name] = fn(profile, gate_config or {})

    results = {r["result"] for r in detail.values()}
    if "fail" in results:
        overall = "fail"
    elif "hold" in results:
        overall = "hold"
    else:
        overall = "pass"

    return {"result": overall, "detail": detail}
