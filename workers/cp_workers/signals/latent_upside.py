"""Latent-upside signal family (spec 01 §3 `family = 'latent_upside'`, spec 02 §4).

Every signal function is a pure function returning the shared tuple shape
`(value: float 0-1, evidence: dict, rationale: str)` per spec 02 §4 / CONTRACT.md
(no shared dataclass, so this module stays import-free of the other signal
families).

`latent_digital_upside_dimension` is the single source of truth for the rules
dimension consumed by the scoring engine (Agent C, spec 04 §3) — keep its
signature and formula exact; Agent C's `scoring/dimensions.py` imports it
directly.
"""
from __future__ import annotations

from typing import Any


def reviews_strong_digital_weak(
    review_strength: float,
    digital_maturity: int,
) -> tuple[float, dict[str, Any], str]:
    """Strong reviews (proven demand) paired with weak digital execution.

    Spec 02 §4: "review score >= 4.3 with >= 100 reviews AND digital_maturity <= 2
    -> high. Formula: review_strength * (1 - (digital_maturity-1)/4)."
    `review_strength` already folds rating + volume (see `reviews.review_strength`),
    so this is a direct application of that formula against the 1-5 maturity score.
    """
    digital_maturity = max(1, min(5, digital_maturity))
    value = review_strength * (1 - (digital_maturity - 1) / 4)
    value = max(0.0, min(1.0, value))
    evidence = {
        "review_strength": review_strength,
        "digital_maturity": digital_maturity,
    }
    if review_strength >= 0.6 and digital_maturity <= 2:
        rationale = "Strong review signal with weak digital execution — clear digitisation upside."
    elif review_strength < 0.3:
        rationale = "Review signal too weak to indicate proven demand."
    else:
        rationale = "Partial signal: reviews and/or digital maturity are middling."
    return value, evidence, rationale


def narrow_distribution(
    review_strength: float,
    notable_stockists_count: int,
    marketplace_presence: bool,
) -> tuple[float, dict[str, Any], str]:
    """Strong reviews but a narrow distribution footprint (spec 02 §4).

    "strong reviews but <= 2 notable stockists and no marketplace presence."
    Scaled: full narrow-distribution value requires review_strength to be
    meaningful (a great product not yet where its customers are), reduced
    toward 0 as stockist count grows past the 2-stockist threshold, and
    reduced if a marketplace listing already exists.
    """
    notable_stockists_count = max(0, notable_stockists_count)
    stockist_factor = max(0.0, 1 - (notable_stockists_count / 3))  # 0 stockists -> 1.0, >=3 -> 0
    marketplace_factor = 0.5 if marketplace_presence else 1.0
    value = review_strength * stockist_factor * marketplace_factor
    value = max(0.0, min(1.0, value))
    evidence = {
        "review_strength": review_strength,
        "notable_stockists_count": notable_stockists_count,
        "marketplace_presence": marketplace_presence,
    }
    if review_strength >= 0.5 and notable_stockists_count <= 2 and not marketplace_presence:
        rationale = "Proven product with a narrow distribution footprint — distribution-expansion candidate."
    else:
        rationale = "Distribution is already reasonably broad, or reviews too thin to judge."
    return value, evidence, rationale


def heritage_underexploited(
    company_age_years: float,
    brand_recognition_evidence: bool,
    digital_maturity: int,
) -> tuple[float, dict[str, Any], str]:
    """Old, recognised brand not yet leveraging digital channels (spec 02 §4).

    "company age >= 20 yrs + brand recognition evidence (press/awards) +
    digital_maturity <= 2." Age scales in below 20 years rather than being a
    hard cliff, so near-miss companies still surface a partial value.
    """
    digital_maturity = max(1, min(5, digital_maturity))
    age_factor = max(0.0, min(1.0, company_age_years / 20))
    recognition_factor = 1.0 if brand_recognition_evidence else 0.0
    digital_gap_factor = max(0.0, (5 - digital_maturity) / 4)  # maturity 1 -> 1.0, 5 -> 0.0
    value = age_factor * recognition_factor * digital_gap_factor
    value = max(0.0, min(1.0, value))
    evidence = {
        "company_age_years": company_age_years,
        "brand_recognition_evidence": brand_recognition_evidence,
        "digital_maturity": digital_maturity,
    }
    if company_age_years >= 20 and brand_recognition_evidence and digital_maturity <= 2:
        rationale = "Established, recognised heritage brand underexploiting digital channels."
    elif not brand_recognition_evidence:
        rationale = "No brand recognition evidence found (press/awards) — heritage angle unproven."
    else:
        rationale = "Company too young or digital maturity too high for a heritage-underexploited read."
    return value, evidence, rationale


def latent_digital_upside_dimension(
    review_strength: float,
    digital_maturity: int,
    distribution_breadth: float,
) -> float:
    """The rules-based `latent_digital_upside` scoring dimension (spec 04 §3).

    THE ONLY place this formula is implemented — Agent C's `scoring/dimensions.py`
    imports this function directly for its rules dimension. Do not change the
    formula here without bumping a rubric version (spec 04 §3 "changing weights =
    new rubric version, never edit in place" applies to this formula too).

    Formula (exact, spec 04 §3 / CONTRACT.md):
        5 * review_strength * (1 - (digital_maturity - 1) / 4)
        + 0.5 bonus if distribution_breadth < 0.3
        capped at 5 (and floored at 0).
    """
    digital_maturity = max(1, min(5, digital_maturity))
    score = 5 * review_strength * (1 - (digital_maturity - 1) / 4)
    if distribution_breadth < 0.3:
        score += 0.5
    return max(0.0, min(5.0, score))
