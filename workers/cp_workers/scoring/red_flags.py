"""Red flags — spec 04 §5.

Red flags are strictly separate from the numeric score: they cap pipeline
placement (a flagged company can't reach `shortlist` without a human
explicitly acknowledging the flag) but they **never** change `total_score`
(spec 04 §5 "flags don't alter the numeric score, so the score stays
comparable and the flag stays visible"). Nothing in this module touches a
score value — it only ever returns flag names.

Detection runs in two passes to preserve the cost ordering in spec 04 §1
(red-flag detection before any LLM call, so flagged/held companies can
short-circuit before spending an LLM call):

1. ``detect_rules_red_flags`` — pure rules, runs first, always available.
   Covers ``structural_decline`` (rules), a conservative keyword pre-filter
   for ``regulatory_exposure`` (rules proxy — a real LLM judgement call would
   require the very LLM call we're trying to avoid paying for on held/failed
   companies, so this stays a rules pre-filter for cost-ordering purposes and
   is intentionally conservative: any keyword hit flags for human review),
   ``customer_channel_concentration`` when distribution-share data is
   available, and ``owner_not_willing`` (manual only — read verbatim from the
   app, never inferred here).
2. ``merge_llm_red_flags`` — called only for gate-passers, after the single
   qualitative LLM call in ``llm_dimensions.py`` (which also returns
   ``tech_product_dependency`` / ``total_owner_dependency`` /
   ``customer_channel_concentration`` booleans piggy-backed on that same
   call, spec 04 §5 last column "LLM assist where not"). Adds any LLM-only
   flags to the rules-pass result.
"""
from __future__ import annotations

ALL_RED_FLAGS = (
    "tech_product_dependency",
    "structural_decline",
    "customer_channel_concentration",
    "regulatory_exposure",
    "owner_not_willing",
    "total_owner_dependency",
)

# Conservative keyword pre-filter for regulatory_exposure (spec 04 §5).
# A hit flags for human review; it never auto-clears the flag from absence.
REGULATORY_KEYWORDS = (
    "clinically proven",
    "clinically tested",
    "cures",
    "cure for",
    "treats acne",
    "treats eczema",
    "treats psoriasis",
    "medical grade",
    "fda approved",
    "prescription strength",
    "anti-cancer",
    "cancer-fighting",
)

CHANNEL_CONCENTRATION_SHARE_THRESHOLD = 0.8


def _has_regulatory_keyword(website_text: str | None) -> str | None:
    if not website_text:
        return None
    lowered = website_text.lower()
    for keyword in REGULATORY_KEYWORDS:
        if keyword in lowered:
            return keyword
    return None


def detect_rules_red_flags(profile: dict) -> tuple[list[str], dict]:
    """Pass 1 — rules only, safe to run before any LLM call.

    Returns (flags, evidence) where evidence maps flag name -> supporting facts.
    """
    flags: list[str] = []
    evidence: dict = {}

    review_trend = profile.get("review_trend")
    net_assets_shrinking = bool(profile.get("net_assets_shrinking", False))
    employee_count_falling = bool(profile.get("employee_count_falling", False))
    if review_trend == "declining" and (net_assets_shrinking or employee_count_falling):
        flags.append("structural_decline")
        evidence["structural_decline"] = {
            "review_trend": review_trend,
            "net_assets_shrinking": net_assets_shrinking,
            "employee_count_falling": employee_count_falling,
        }

    dominant_channel_share = profile.get("dominant_channel_share")
    if dominant_channel_share is not None and dominant_channel_share >= CHANNEL_CONCENTRATION_SHARE_THRESHOLD:
        flags.append("customer_channel_concentration")
        evidence["customer_channel_concentration"] = {"dominant_channel_share": dominant_channel_share}

    keyword_hit = _has_regulatory_keyword(profile.get("website_text"))
    if keyword_hit:
        flags.append("regulatory_exposure")
        evidence["regulatory_exposure"] = {"keyword_matched": keyword_hit}

    # Manual only — never inferred. Passed through verbatim if already set
    # by a human decision in the app; this module must never set it itself.
    if profile.get("owner_not_willing_manual", False):
        flags.append("owner_not_willing")
        evidence["owner_not_willing"] = {"source": "manual"}

    return flags, evidence


def merge_llm_red_flags(rules_flags: list[str], llm_flags: dict | None) -> list[str]:
    """Pass 2 — merge in the LLM-judged flags from the qualitative LLM call.

    ``llm_flags`` is the ``"flags"`` dict returned by
    ``llm_dimensions.score_qualitative_dimensions`` (keys may be ``None`` if
    the LLM call never completed — treated as "no evidence", not a flag).
    """
    merged = list(rules_flags)
    llm_flags = llm_flags or {}

    if llm_flags.get("tech_product_dependency") is True and "tech_product_dependency" not in merged:
        merged.append("tech_product_dependency")

    if llm_flags.get("total_owner_dependency") is True and "total_owner_dependency" not in merged:
        merged.append("total_owner_dependency")

    if (
        llm_flags.get("customer_channel_concentration") is True
        and "customer_channel_concentration" not in merged
    ):
        merged.append("customer_channel_concentration")

    return merged
