"""Tests for signals/consolidation.py (spec 02 §4)."""
from __future__ import annotations

import pytest

from cp_workers.signals.consolidation import adjacency, fragmented_subcategory


def _company(number, sector_tags, size_band, employee_count=None):
    return {
        "company_number": number,
        "sector_tags": sector_tags,
        "size_band": size_band,
        "employee_count": employee_count,
    }


def test_adjacency_always_stub():
    value, evidence, rationale = adjacency({"company_number": "1"}, [{"company_number": "2"}])
    assert value == 0.0
    assert evidence == {}
    assert rationale == "no portfolio yet"


def test_fragmented_subcategory_target_missing_tags_or_band():
    target = {"company_number": "1", "sector_tags": [], "size_band": "fit-now"}
    value, evidence, rationale = fragmented_subcategory([], target)
    assert value == 0.0
    assert evidence["matched_count"] == 0
    assert "sector tag" in rationale


def test_fragmented_subcategory_no_comparable_companies():
    target = _company("1", ["skincare-personal-care"], "fit-now")
    value, evidence, rationale = fragmented_subcategory([target], target)
    assert value == 0.0
    assert evidence["matched_count"] == 0
    assert "no comparable companies" in rationale


def test_fragmented_subcategory_many_small_no_dominant():
    target = _company("1", ["skincare-personal-care"], "fit-now", employee_count=10)
    universe = [target] + [
        _company(str(i), ["skincare-personal-care"], "fit-now", employee_count=8 + i)
        for i in range(2, 22)
    ]
    value, evidence, rationale = fragmented_subcategory(universe, target)
    assert evidence["matched_count"] == 20
    assert evidence["dominant_player_present"] is False
    assert value == pytest.approx(1.0, abs=1e-4)
    assert "no dominant player" in rationale


def test_fragmented_subcategory_dominant_player_discounts_score():
    target = _company("1", ["skincare-personal-care"], "fit-now", employee_count=10)
    universe = [target] + [
        _company(str(i), ["skincare-personal-care"], "fit-now", employee_count=10) for i in range(2, 12)
    ]
    universe.append(_company("999", ["skincare-personal-care"], "fit-now", employee_count=500))
    value, evidence, rationale = fragmented_subcategory(universe, target)
    assert evidence["dominant_player_present"] is True
    assert value < 0.5
    assert "dominant player" in rationale


def test_fragmented_subcategory_requires_shared_size_band():
    target = _company("1", ["skincare-personal-care"], "fit-now", employee_count=10)
    universe = [target, _company("2", ["skincare-personal-care"], "too-large", employee_count=500)]
    value, evidence, _rationale = fragmented_subcategory(universe, target)
    assert value == 0.0
    assert evidence["matched_count"] == 0
