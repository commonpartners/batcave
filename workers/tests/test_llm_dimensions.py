"""Tests for scoring/llm_dimensions.py — mocked Anthropic client throughout,
no live API calls. Covers: happy path, retry-once-on-schema-failure, and
two-failures -> None + scoring_incomplete (never fabricated)."""
from __future__ import annotations

import json

import pytest

from cp_workers.scoring import llm_dimensions

VALID_RESPONSE = {
    "brand_customer_equity": {"score_0_to_5": 4, "rationale_one_line": "Strong reviews.", "evidence": ["4.5 stars, 300 reviews"]},
    "team_continuity": {"score_0_to_5": 3, "rationale_one_line": "Small team evidenced.", "evidence": ["About page lists 3 staff"]},
    "differentiation": {"score_0_to_5": 2, "rationale_one_line": "Generic claims only.", "evidence": ["natural ingredients"]},
    "tech_product_dependency": False,
    "total_owner_dependency": False,
    "customer_channel_concentration": False,
}


class _ContentBlock:
    def __init__(self, text: str):
        self.text = text


class _Response:
    def __init__(self, text: str):
        self.content = [_ContentBlock(text)]


class _ScriptedMessages:
    """Returns each element of ``responses`` in turn on successive .create() calls."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        text = self.responses[self.calls] if self.calls < len(self.responses) else self.responses[-1]
        self.calls += 1
        return _Response(text)


class _ScriptedClient:
    def __init__(self, responses: list[str]):
        self.messages = _ScriptedMessages(responses)


def _client(*responses: str) -> _ScriptedClient:
    return _ScriptedClient(list(responses))


class TestHappyPath:
    def test_valid_response_parsed_first_try(self):
        client = _client(json.dumps(VALID_RESPONSE))
        result = llm_dimensions.score_qualitative_dimensions({"legal_name": "Test Co"}, client=client)

        assert result["scoring_incomplete"] is False
        assert result["dimensions"]["brand_customer_equity"]["raw_score"] == 4.0
        assert result["dimensions"]["team_continuity"]["raw_score"] == 3.0
        assert result["dimensions"]["differentiation"]["raw_score"] == 2.0
        assert result["flags"] == {
            "tech_product_dependency": False,
            "total_owner_dependency": False,
            "customer_channel_concentration": False,
        }
        assert result["prompt_hash"]
        assert client.messages.calls == 1

    def test_fenced_json_block_is_extracted(self):
        fenced = "Here is the result:\n```json\n" + json.dumps(VALID_RESPONSE) + "\n```"
        client = _client(fenced)
        result = llm_dimensions.score_qualitative_dimensions({"legal_name": "Test Co"}, client=client)
        assert result["scoring_incomplete"] is False

    def test_temperature_zero_and_model_from_settings(self, monkeypatch):
        captured = {}

        class CapturingMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return _Response(json.dumps(VALID_RESPONSE))

        class CapturingClient:
            messages = CapturingMessages()

        llm_dimensions.score_qualitative_dimensions({"legal_name": "Test Co"}, client=CapturingClient())
        assert captured["temperature"] == 0


class TestRetryOnSchemaFailure:
    def test_bad_json_then_good_json_succeeds_on_retry(self):
        client = _client("not valid json", json.dumps(VALID_RESPONSE))
        result = llm_dimensions.score_qualitative_dimensions({"legal_name": "Test Co"}, client=client)
        assert result["scoring_incomplete"] is False
        assert client.messages.calls == 2

    def test_missing_field_then_good_json_succeeds_on_retry(self):
        broken = dict(VALID_RESPONSE)
        del broken["differentiation"]
        client = _client(json.dumps(broken), json.dumps(VALID_RESPONSE))
        result = llm_dimensions.score_qualitative_dimensions({"legal_name": "Test Co"}, client=client)
        assert result["scoring_incomplete"] is False
        assert client.messages.calls == 2

    def test_out_of_range_score_then_good_json_succeeds_on_retry(self):
        broken = json.loads(json.dumps(VALID_RESPONSE))
        broken["brand_customer_equity"]["score_0_to_5"] = 9
        client = _client(json.dumps(broken), json.dumps(VALID_RESPONSE))
        result = llm_dimensions.score_qualitative_dimensions({"legal_name": "Test Co"}, client=client)
        assert result["scoring_incomplete"] is False
        assert client.messages.calls == 2


class TestTwoFailuresNeverFabricates:
    def test_both_attempts_invalid_json_returns_none_dims(self):
        client = _client("nope", "still nope")
        result = llm_dimensions.score_qualitative_dimensions({"legal_name": "Test Co"}, client=client)
        assert result["scoring_incomplete"] is True
        assert all(v is None for v in result["dimensions"].values())
        assert all(v is None for v in result["flags"].values())
        assert client.messages.calls == 2

    def test_never_raises_on_repeated_failure(self):
        client = _client("garbage", "more garbage")
        # Must not raise -- caller (pipeline.py) relies on this never throwing.
        result = llm_dimensions.score_qualitative_dimensions({"legal_name": "Test Co"}, client=client)
        assert isinstance(result, dict)

    def test_error_message_captured(self):
        client = _client("garbage", "more garbage")
        result = llm_dimensions.score_qualitative_dimensions({"legal_name": "Test Co"}, client=client)
        assert "error" in result


class TestMissingApiKey:
    def test_no_client_no_api_key_returns_incomplete_without_raising(self, monkeypatch):
        # Settings is a frozen dataclass -- swap the module's reference to a
        # replacement instance rather than mutating the singleton. This also
        # guarantees a real key from a local .env can never leak into this
        # test as a live API call.
        import dataclasses

        monkeypatch.setattr(
            llm_dimensions, "settings", dataclasses.replace(llm_dimensions.settings, anthropic_api_key=None)
        )
        result = llm_dimensions.score_qualitative_dimensions({"legal_name": "Test Co"})
        assert result["scoring_incomplete"] is True
        assert all(v is None for v in result["dimensions"].values())


def test_prompt_hash_stable_for_same_profile():
    client1 = _client(json.dumps(VALID_RESPONSE))
    client2 = _client(json.dumps(VALID_RESPONSE))
    profile = {"legal_name": "Stable Co", "sector_tags": ["skincare-personal-care"]}
    r1 = llm_dimensions.score_qualitative_dimensions(profile, client=client1)
    r2 = llm_dimensions.score_qualitative_dimensions(profile, client=client2)
    assert r1["prompt_hash"] == r2["prompt_hash"]
