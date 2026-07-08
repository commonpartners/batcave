"""Tests for connectors/companies_house.py: token bucket throttle, 429
backoff, and iXBRL parsing (never raises on malformed input)."""
from __future__ import annotations

import httpx
import pytest
import respx

from cp_workers.connectors import companies_house
from cp_workers.connectors.companies_house import (
    BASE_URL,
    CompaniesHouseClient,
    TokenBucket,
    _parse_retry_after,
    parse_ixbrl,
)


@pytest.fixture(autouse=True)
def fake_db(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(companies_house.db, "get_company_by_number", lambda number: None)
    monkeypatch.setattr(companies_house.db, "record_source", lambda **kwargs: calls.append(kwargs))
    return calls


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


def test_token_bucket_allows_burst_up_to_capacity():
    clock = {"t": 0.0}
    slept = []
    bucket = TokenBucket(
        capacity=3,
        window_seconds=300,
        clock=lambda: clock["t"],
        sleep_fn=lambda s: slept.append(s),
    )
    bucket.acquire()
    bucket.acquire()
    bucket.acquire()
    assert slept == []


def test_token_bucket_blocks_once_exhausted():
    clock = {"t": 0.0}
    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    bucket = TokenBucket(capacity=2, window_seconds=10, clock=lambda: clock["t"], sleep_fn=fake_sleep)
    bucket.acquire()
    bucket.acquire()
    bucket.acquire()  # exhausted -> must wait for a refill
    assert slept
    assert slept[0] > 0


def test_token_bucket_refills_over_time():
    clock = {"t": 0.0}
    bucket = TokenBucket(capacity=1, window_seconds=10, clock=lambda: clock["t"], sleep_fn=lambda s: None)
    bucket.acquire()
    clock["t"] += 10  # a full window later, should be back to full
    bucket.acquire()  # must not raise/hang


# ---------------------------------------------------------------------------
# Retry-After parsing
# ---------------------------------------------------------------------------


def test_parse_retry_after_integer_seconds():
    assert _parse_retry_after("5") == 5.0


def test_parse_retry_after_missing_uses_default():
    assert _parse_retry_after(None) == pytest.approx(5.0)


def test_parse_retry_after_garbage_uses_default():
    assert _parse_retry_after("not-a-valid-value") == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Client endpoints: provenance + 429 backoff
# ---------------------------------------------------------------------------


@respx.mock
def test_get_profile_records_source_before_returning(fake_db):
    route = respx.get(f"{BASE_URL}/company/12345678").mock(
        return_value=httpx.Response(200, json={"company_name": "Acme Ltd", "company_status": "active"})
    )
    client = CompaniesHouseClient(api_key="dummy")
    result = client.get_profile("12345678")

    assert route.called
    assert result["company_name"] == "Acme Ltd"
    assert len(fake_db) == 1
    assert fake_db[0]["source"] == "companies_house_profile"
    assert fake_db[0]["raw"]["company_name"] == "Acme Ltd"


@respx.mock
def test_429_backs_off_per_retry_after_then_succeeds(fake_db):
    respx.get(f"{BASE_URL}/company/12345678").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"company_name": "Acme Ltd"}),
        ]
    )
    sleeps: list[float] = []
    client = CompaniesHouseClient(api_key="dummy", sleep_fn=lambda s: sleeps.append(s))
    result = client.get_profile("12345678")

    assert result["company_name"] == "Acme Ltd"
    assert sleeps == [2.0]
    assert len(fake_db) == 1  # only the successful response is recorded


@respx.mock
def test_officers_endpoint_uses_correct_path_and_source(fake_db):
    respx.get(f"{BASE_URL}/company/12345678/officers").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    client = CompaniesHouseClient(api_key="dummy")
    client.get_officers("12345678")
    assert fake_db[0]["source"] == "companies_house_officers"


# ---------------------------------------------------------------------------
# parse_ixbrl — never raises
# ---------------------------------------------------------------------------


def test_parse_ixbrl_empty_bytes_returns_empty_dict():
    assert parse_ixbrl(b"") == {}


def test_parse_ixbrl_malformed_input_never_raises():
    garbage = b"\x00\x01 this is not xml <<<>>> \xff\xfe"
    result = parse_ixbrl(garbage)
    assert result == {}


def test_parse_ixbrl_extracts_balance_sheet_and_employees():
    document = b"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:core="http://xbrl.frc.org.uk/fr/2014-09-01/core">
  <body>
    <ix:nonFraction name="core:CashBankInHand" contextRef="c1" unitRef="GBP" scale="0" sign="" decimals="0">12345</ix:nonFraction>
    <ix:nonFraction name="core:NetAssetsLiabilities" contextRef="c1" unitRef="GBP" scale="3" sign="" decimals="-3">67</ix:nonFraction>
    <ix:nonFraction name="core:ShareholderFunds" contextRef="c1" unitRef="GBP" scale="0" sign="-" decimals="0">500</ix:nonFraction>
    <ix:nonFraction name="core:AverageNumberEmployeesDuringPeriod" contextRef="c1" unitRef="pure" scale="0" sign="" decimals="0">7</ix:nonFraction>
  </body>
</html>
"""
    result = parse_ixbrl(document)
    assert result["balance_sheet"]["cash"] == 1234500
    assert result["balance_sheet"]["net_assets"] == 6700000
    assert result["balance_sheet"]["shareholders_funds"] == -50000
    assert result["balance_sheet"]["total_assets"] is None
    assert result["balance_sheet"]["creditors"] is None
    assert result["employee_count"] == 7


def test_parse_ixbrl_no_recognised_concepts_returns_empty_dict():
    document = b"<root><unrelated>hello</unrelated></root>"
    assert parse_ixbrl(document) == {}
