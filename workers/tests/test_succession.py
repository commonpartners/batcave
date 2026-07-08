"""Exhaustive fixtures for signals/succession.py (spec 02 §4).

Covers: missing DOB, dissolved company (no active officers), no officers at
all, sole director at exactly the age boundaries (60/65/68/72/75/78) for
director_retirement_window, and tenure boundaries (12/20 years) for
long_single_owner_tenure.
"""
from __future__ import annotations

from datetime import date

import pytest

from cp_workers.signals.succession import (
    board_psc_event_recent,
    director_retirement_window,
    long_single_owner_tenure,
)

NOW = date(2026, 7, 8)


def _sole_director(birth_year: int | None, birth_month: int | None = 7) -> list[dict]:
    return [
        {
            "name": "Jane Sole",
            "role": "director",
            "is_active": True,
            "birth_year": birth_year,
            "birth_month": birth_month,
            "ownership_pct_band": None,
            "tenure_years": None,
            "other_active_directorships": None,
        }
    ]


# ---------------------------------------------------------------------------
# director_retirement_window
# ---------------------------------------------------------------------------


def test_retirement_window_no_officers():
    value, evidence, rationale = director_retirement_window([], NOW)
    assert value == 0.0
    assert evidence == {"candidates": []}
    assert "no officers on record" in rationale


def test_retirement_window_dissolved_company_no_active_officers():
    people = [
        {
            "name": "Former Director",
            "role": "director",
            "is_active": False,
            "birth_year": 1950,
            "birth_month": 7,
            "ownership_pct_band": None,
            "tenure_years": None,
            "other_active_directorships": None,
        }
    ]
    value, _evidence, rationale = director_retirement_window(people, NOW)
    assert value == 0.0
    assert "dissolved" in rationale


def test_retirement_window_missing_dob():
    people = _sole_director(birth_year=None, birth_month=None)
    value, evidence, rationale = director_retirement_window(people, NOW)
    assert value == 0.0
    assert evidence == {"candidates": []}
    assert "date of birth unknown" in rationale


def test_retirement_window_no_controlling_person():
    # Two active directors (no sole-director signal) and no PSC ownership
    # band on either -> nobody counts as "controlling".
    people = [
        {
            "name": "A",
            "role": "director",
            "is_active": True,
            "birth_year": 1955,
            "birth_month": 7,
            "ownership_pct_band": None,
            "tenure_years": None,
            "other_active_directorships": None,
        },
        {
            "name": "B",
            "role": "director",
            "is_active": True,
            "birth_year": 1960,
            "birth_month": 7,
            "ownership_pct_band": None,
            "tenure_years": None,
            "other_active_directorships": None,
        },
    ]
    value, _evidence, rationale = director_retirement_window(people, NOW)
    assert value == 0.0
    assert "no controlling director" in rationale


@pytest.mark.parametrize(
    "age,expected",
    [
        (60, 0.0),
        (65, 0.625),
        (68, 1.0),
        (72, 1.0),
        (75, 0.8),
        (78, 0.6),
    ],
)
def test_retirement_window_sole_director_age_boundaries(age, expected):
    birth_year = NOW.year - age
    people = _sole_director(birth_year=birth_year, birth_month=NOW.month)
    value, evidence, _rationale = director_retirement_window(people, NOW)
    assert value == pytest.approx(expected, abs=1e-4)
    assert evidence["selected"]["age_years"] == age


def test_retirement_window_controlling_psc_at_boundary():
    people = [
        {
            "name": "Controlling PSC",
            "role": "psc",
            "is_active": True,
            "birth_year": NOW.year - 68,
            "birth_month": NOW.month,
            "ownership_pct_band": "50-75",
            "tenure_years": None,
            "other_active_directorships": None,
        },
        {
            "name": "Co-director",
            "role": "director",
            "is_active": True,
            "birth_year": None,
            "birth_month": None,
            "ownership_pct_band": None,
            "tenure_years": None,
            "other_active_directorships": None,
        },
        {
            "name": "Other co-director",
            "role": "director",
            "is_active": True,
            "birth_year": None,
            "birth_month": None,
            "ownership_pct_band": None,
            "tenure_years": None,
            "other_active_directorships": None,
        },
    ]
    value, _evidence, _rationale = director_retirement_window(people, NOW)
    assert value == 1.0


# ---------------------------------------------------------------------------
# long_single_owner_tenure
# ---------------------------------------------------------------------------


def test_tenure_no_officers():
    value, evidence, rationale = long_single_owner_tenure([])
    assert value == 0.0
    assert evidence == {"candidates": []}
    assert "no officers on record" in rationale


def test_tenure_dissolved_company():
    people = [
        {
            "name": "Former Director",
            "role": "director",
            "is_active": False,
            "tenure_years": 25.0,
            "other_active_directorships": 0,
        }
    ]
    value, _evidence, rationale = long_single_owner_tenure(people)
    assert value == 0.0
    assert "dissolved" in rationale


def test_tenure_missing_tenure_data():
    people = [
        {
            "name": "Director",
            "role": "director",
            "is_active": True,
            "tenure_years": None,
            "other_active_directorships": 0,
        }
    ]
    value, evidence, rationale = long_single_owner_tenure(people)
    assert value == 0.0
    assert evidence == {"candidates": []}
    assert "known tenure" in rationale


@pytest.mark.parametrize(
    "tenure_years,expected",
    [
        (11.9, 0.0),
        (12, 0.5),
        (16, 0.75),
        (20, 1.0),
        (30, 1.0),
    ],
)
def test_tenure_boundaries(tenure_years, expected):
    people = [
        {
            "name": "Long Tenure Director",
            "role": "director",
            "is_active": True,
            "tenure_years": tenure_years,
            "other_active_directorships": 1,
        }
    ]
    value, _evidence, _rationale = long_single_owner_tenure(people)
    assert value == pytest.approx(expected, abs=1e-4)


def test_tenure_disqualified_by_other_directorships():
    people = [
        {
            "name": "Serial Director",
            "role": "director",
            "is_active": True,
            "tenure_years": 20,
            "other_active_directorships": 3,
        }
    ]
    value, evidence, rationale = long_single_owner_tenure(people)
    assert value == 0.0
    assert evidence["selected"]["disqualified"] is True
    assert "disqualified" in rationale


def test_tenure_unknown_other_directorships_not_disqualifying():
    people = [
        {
            "name": "Director",
            "role": "director",
            "is_active": True,
            "tenure_years": 20,
            "other_active_directorships": None,
        }
    ]
    value, _evidence, _rationale = long_single_owner_tenure(people)
    assert value == 1.0


# ---------------------------------------------------------------------------
# board_psc_event_recent
# ---------------------------------------------------------------------------


def test_psc_event_no_events():
    value, evidence, rationale = board_psc_event_recent([], NOW)
    assert value == 0.0
    assert evidence == {"events": []}
    assert "no board/PSC events on record" in rationale


def test_psc_event_just_happened():
    events = [{"type": "director_terminated", "date": NOW}]
    value, _evidence, _rationale = board_psc_event_recent(events, NOW)
    assert value == pytest.approx(1.0, abs=1e-4)


def test_psc_event_older_than_18_months_excluded():
    events = [{"type": "psc_change", "date": date(2024, 12, 1)}]  # ~19 months before NOW
    value, evidence, rationale = board_psc_event_recent(events, NOW)
    assert value == 0.0
    assert evidence == {"events": []}
    assert "18 months" in rationale


def test_psc_event_decays_with_age():
    events = [{"type": "family_member_removed", "date": date(2026, 1, 8)}]  # 6 months before NOW
    value, _evidence, _rationale = board_psc_event_recent(events, NOW)
    assert 0.5 < value < 0.75


def test_psc_event_string_date_accepted():
    events = [{"type": "psc_change", "date": "2026-07-08"}]
    value, _evidence, _rationale = board_psc_event_recent(events, NOW)
    assert value == pytest.approx(1.0, abs=1e-4)


def test_psc_event_picks_most_recent_of_several():
    events = [
        {"type": "director_terminated", "date": date(2025, 1, 8)},
        {"type": "psc_change", "date": date(2026, 6, 8)},
    ]
    value, evidence, _rationale = board_psc_event_recent(events, NOW)
    assert evidence["selected"]["type"] == "psc_change"
    assert value > 0.9
