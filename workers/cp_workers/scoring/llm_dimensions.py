"""LLM-judged attractiveness dimensions — spec 04 §3.

One Anthropic call per company covers ``brand_customer_equity``,
``team_continuity``, ``differentiation`` (the three dimensions rules can't
score) plus three boolean red-flag hints (``tech_product_dependency``,
``total_owner_dependency``, ``customer_channel_concentration`` — spec 04 §5)
piggy-backed onto the same call so red-flag detection doesn't need a second
LLM round-trip.

Temperature 0, strict pydantic-validated JSON, retry once on any failure to
parse/validate; two failures return every dimension as ``None`` with
``scoring_incomplete=True`` — this module never fabricates a score. The
anchored rubric + 3 worked few-shot examples live in
``workers/prompts/score_qualitative.md`` (versioned front-matter).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from cp_workers.config import settings

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "score_qualitative.md"
PROMPT_VERSION = "1.0.0"

LLM_DIMENSION_NAMES = ("brand_customer_equity", "team_continuity", "differentiation")


class DimensionResult(BaseModel):
    score_0_to_5: int = Field(ge=0, le=5)
    rationale_one_line: str
    evidence: list[str] = Field(default_factory=list)


class QualitativeLLMResponse(BaseModel):
    brand_customer_equity: DimensionResult
    team_continuity: DimensionResult
    differentiation: DimensionResult
    tech_product_dependency: bool = False
    total_owner_dependency: bool = False
    customer_channel_concentration: bool = False


def _load_prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _system_prompt(full_text: str) -> str:
    match = re.search(r"# System prompt\n(.*?)\n# User message template", full_text, re.DOTALL)
    return match.group(1).strip() if match else full_text


def _user_template(full_text: str) -> str:
    match = re.search(r"# User message template\s*```\s*(.*?)\s*```", full_text, re.DOTALL)
    if not match:
        return (
            "COMPANY PROFILE (JSON):\n{profile_json}\n\nWEBSITE TEXT:\n{website_text}\n\n"
            "REVIEW SUMMARY:\n{review_summary}"
        )
    return match.group(1)


def build_messages(profile: dict) -> tuple[str, str, str]:
    """Returns (system_prompt, user_message, prompt_hash). Exposed for tests."""
    full_text = _load_prompt_text()
    system_prompt = _system_prompt(full_text)
    template = _user_template(full_text)
    profile_json = json.dumps(
        profile.get("structured", profile), indent=2, default=str, sort_keys=True
    )
    website_text = profile.get("website_text") or "(no website text available)"
    review_summary = profile.get("review_summary") or "(no review data available)"
    user_message = template.format(
        profile_json=profile_json, website_text=website_text, review_summary=review_summary
    )
    prompt_hash = hashlib.sha256((system_prompt + "\n" + template).encode("utf-8")).hexdigest()
    return system_prompt, user_message, prompt_hash


def _empty_result(prompt_hash: str, error: str | None = None) -> dict:
    result = {
        "dimensions": {name: None for name in LLM_DIMENSION_NAMES},
        "flags": {
            "tech_product_dependency": None,
            "total_owner_dependency": None,
            "customer_channel_concentration": None,
        },
        "scoring_incomplete": True,
        "prompt_hash": prompt_hash,
        "prompt_version": PROMPT_VERSION,
    }
    if error:
        result["error"] = error
    return result


def _call_llm(client: Any, system_prompt: str, user_message: str) -> str:
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1500,
        temperature=0,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def _extract_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text)


def score_qualitative_dimensions(profile: dict, *, client: Any = None) -> dict:
    """Score the three LLM dimensions for one company.

    ``client`` is an Anthropic-SDK-shaped client (``.messages.create(...)``);
    pass a mock in tests. If ``client`` is None and no API key is configured,
    returns the incomplete result immediately without raising.
    """
    system_prompt, user_message, prompt_hash = build_messages(profile)

    if client is None:
        if not settings.anthropic_api_key:
            return _empty_result(prompt_hash, error="ANTHROPIC_API_KEY not configured")
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    validated: QualitativeLLMResponse | None = None
    last_error: Exception | None = None

    for _attempt in range(2):
        try:
            raw_text = _call_llm(client, system_prompt, user_message)
            parsed = _extract_json(raw_text)
            validated = QualitativeLLMResponse.model_validate(parsed)
            break
        except Exception as exc:  # noqa: BLE001 - any failure means retry-once-then-give-up
            last_error = exc
            validated = None
            continue

    if validated is None:
        return _empty_result(prompt_hash, error=str(last_error) if last_error else "validation failed")

    dimensions = {
        name: {
            "raw_score": float(getattr(validated, name).score_0_to_5),
            "rationale": getattr(validated, name).rationale_one_line,
            "evidence": getattr(validated, name).evidence,
        }
        for name in LLM_DIMENSION_NAMES
    }
    return {
        "dimensions": dimensions,
        "flags": {
            "tech_product_dependency": validated.tech_product_dependency,
            "total_owner_dependency": validated.total_owner_dependency,
            "customer_channel_concentration": validated.customer_channel_concentration,
        },
        "scoring_incomplete": False,
        "prompt_hash": prompt_hash,
        "prompt_version": PROMPT_VERSION,
    }
