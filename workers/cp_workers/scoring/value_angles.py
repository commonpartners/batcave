"""Value-creation angles — spec 04 §6. Max 2 returned per company.

Rules decide which angles *qualify* (0..5 of them can trigger). When more
than 2 qualify, an LLM tie-break narrows to the strongest 2; when the LLM is
unavailable or fails, a documented deterministic ranking is used instead so
this step never blocks scoring.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from cp_workers.config import settings

ALL_VALUE_ANGLES = (
    "digitise",
    "performance_market",
    "rollup_buy_and_build",
    "succession_continuity",
    "distribution_expansion",
)

# spec 04 §6 doesn't pin a numeric threshold for "review_strength high" —
# review_strength is 0-1 (log-scaled volume x normalised rating, spec 03 §3);
# 0.6 is our documented interpretation, tunable via app_config later.
REVIEW_STRENGTH_HIGH_THRESHOLD = 0.6

ANGLE_DEFINITIONS = {
    "digitise": "latent_digital_upside >= 4 and digital_maturity <= 2",
    "performance_market": "review_strength high, no ad pixels, e-commerce exists",
    "rollup_buy_and_build": "fragmented_subcategory >= 0.6",
    "succession_continuity": "succession signal >= 0.5 and team evidence present",
    "distribution_expansion": "narrow_distribution >= 0.6",
}

_ANGLE_STRENGTH_KEYS = {
    "digitise": "latent_digital_upside_raw",
    "performance_market": "review_strength",
    "rollup_buy_and_build": "fragmented_subcategory",
    "succession_continuity": "succession_signal_max",
    "distribution_expansion": "narrow_distribution",
}

# Arbitrary but fixed priority used only to break ties when strengths are
# equal (or absent) — provisional pending Ben's input, same spirit as the
# other "provisional" defaults seeded in 0007_seeds.sql.
_FIXED_PRIORITY = [
    "digitise",
    "distribution_expansion",
    "rollup_buy_and_build",
    "succession_continuity",
    "performance_market",
]


def qualifying_value_angles(profile: dict) -> list[str]:
    """Rules pass — returns every angle whose trigger condition holds."""
    qualifying: list[str] = []

    latent_digital_upside_raw = profile.get("latent_digital_upside_raw")
    digital_maturity = profile.get("digital_maturity")
    if (
        latent_digital_upside_raw is not None
        and digital_maturity is not None
        and latent_digital_upside_raw >= 4
        and digital_maturity <= 2
    ):
        qualifying.append("digitise")

    review_strength = profile.get("review_strength")
    ad_pixels_present = profile.get("ad_pixels_present")
    has_ecommerce = profile.get("has_ecommerce")
    if (
        review_strength is not None
        and review_strength >= REVIEW_STRENGTH_HIGH_THRESHOLD
        and ad_pixels_present is False
        and has_ecommerce is True
    ):
        qualifying.append("performance_market")

    fragmented_subcategory = profile.get("fragmented_subcategory")
    if fragmented_subcategory is not None and fragmented_subcategory >= 0.6:
        qualifying.append("rollup_buy_and_build")

    succession_signal_max = profile.get("succession_signal_max")
    team_evidence_present = profile.get("team_evidence_present")
    if (
        succession_signal_max is not None
        and succession_signal_max >= 0.5
        and team_evidence_present
    ):
        qualifying.append("succession_continuity")

    narrow_distribution = profile.get("narrow_distribution")
    if narrow_distribution is not None and narrow_distribution >= 0.6:
        qualifying.append("distribution_expansion")

    return qualifying


def _deterministic_tie_break(qualifying: list[str], profile: dict) -> list[str]:
    def sort_key(angle: str) -> tuple[float, int]:
        strength_key = _ANGLE_STRENGTH_KEYS.get(angle, "")
        strength = profile.get(strength_key) or 0.0
        priority_index = _FIXED_PRIORITY.index(angle) if angle in _FIXED_PRIORITY else len(_FIXED_PRIORITY)
        return (-strength, priority_index)

    return sorted(qualifying, key=sort_key)


class _TieBreakResponse(BaseModel):
    selected_angles: list[str] = Field(min_length=1, max_length=2)


def _tie_break_prompt(qualifying: list[str], profile: dict) -> tuple[str, str]:
    definitions = "\n".join(f"- {a}: {ANGLE_DEFINITIONS[a]}" for a in qualifying)
    system_prompt = (
        "You are picking the two strongest value-creation angles for an "
        "acquisition target from a list of angles that all technically "
        "qualify. Pick exactly 2 (or 1 if only one is truly meaningful), "
        "choosing the ones best supported by the evidence in the profile. "
        "Return strict JSON: {\"selected_angles\": [\"<angle>\", ...]} "
        "using only angle names from the qualifying list, nothing else."
    )
    profile_json = json.dumps(profile, indent=2, default=str, sort_keys=True)
    user_message = (
        f"Qualifying angles:\n{definitions}\n\nCompany profile (JSON):\n{profile_json}\n\n"
        "Return the JSON object with your 2 picks."
    )
    return system_prompt, user_message


def _extract_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text)


def llm_tie_break_value_angles(qualifying: list[str], profile: dict, *, client: Any = None) -> list[str]:
    """LLM tie-break when > 2 angles qualify (spec 04 §6).

    Never raises: any failure (missing key, bad JSON, schema mismatch)
    returns an empty list, and the caller falls back to the deterministic
    ranking. This keeps a flaky tie-break call from ever blocking scoring.
    """
    try:
        if client is None:
            if not settings.anthropic_api_key:
                return []
            import anthropic

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        system_prompt, user_message = _tie_break_prompt(qualifying, profile)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=300,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw_text = response.content[0].text
        parsed = _extract_json(raw_text)
        validated = _TieBreakResponse.model_validate(parsed)
        return [a for a in validated.selected_angles if a in qualifying]
    except Exception:  # noqa: BLE001 - tie-break is best-effort, never fatal
        return []


def select_value_angles(
    qualifying: list[str],
    profile: dict,
    llm_tie_break: Callable[[list[str], dict], list[str]] | None = None,
) -> list[str]:
    """Max 2 angles. <=2 qualify -> return them. >2 qualify -> LLM tie-break,
    falling back to a deterministic ranking if the tie-break is unavailable
    or returns nothing usable.
    """
    qualifying = list(dict.fromkeys(qualifying))  # dedupe, preserve order
    if len(qualifying) <= 2:
        return qualifying

    if llm_tie_break is not None:
        picked = llm_tie_break(qualifying, profile)
        picked = [a for a in picked if a in qualifying]
        if picked:
            return picked[:2]

    return _deterministic_tie_break(qualifying, profile)[:2]
