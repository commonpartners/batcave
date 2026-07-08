"""Succession-family signal functions (spec 02 §4).

Pure functions returning ``(value: float 0-1, evidence: dict, rationale: str)``.
No I/O and no imports from other ``cp_workers`` modules — per CONTRACT.md,
signal modules stay import-free of each other so callers can mix and match.

Expected shape of a ``people`` entry — one dict per active/former
``company_people`` row joined with ``people`` (spec 01 §2). Callers assemble
this from the DB / CH officers+PSC payloads; fields not knowable are ``None``,
never guessed:

    {
        "name": str | None,
        "role": "director" | "psc" | "secretary",
        "is_active": bool,
        "birth_year": int | None,
        "birth_month": int | None,            # 1-12; CH gives month/year only
        "ownership_pct_band": "25-50" | "50-75" | "75-100" | None,
        "tenure_years": float | None,          # pre-derived (spec 01 §2)
        "other_active_directorships": int | None,
    }

``board_psc_event_recent`` takes a separate ``events`` list, one dict per
change event:

    {"type": "director_terminated" | "psc_change" | "family_member_removed" | str,
     "date": date | datetime | "YYYY-MM-DD", "detail": str | None}
"""
from __future__ import annotations

from datetime import date, datetime

SignalResult = tuple[float, dict, str]

_CONTROLLING_PSC_BANDS = {"25-50", "50-75", "75-100"}
_RETIREMENT_MAX = 78.0


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _age_years(birth_year: int | None, birth_month: int | None, now: date) -> float | None:
    """Age from CH birth month/year (day unknown, per spec 01 §2 — never
    store/assume a full DOB). Assumes the birthday has passed once the current
    month reaches the birth month."""
    if birth_year is None or birth_month is None:
        return None
    age = now.year - birth_year
    if now.month < birth_month:
        age -= 1
    return float(age)


def _retirement_curve(age: float) -> float:
    """0 at 60 -> 1.0 across 68-72 -> taper to 0.6 at/after 78 (spec 02 §4)."""
    if age < 60:
        return 0.0
    if age < 68:
        return round((age - 60) / 8.0, 4)
    if age <= 72:
        return 1.0
    if age < _RETIREMENT_MAX:
        return round(1.0 - (age - 72) / 6.0 * 0.4, 4)
    return 0.6


def director_retirement_window(people: list[dict], now: date | datetime) -> SignalResult:
    """Controlling director (PSC >= 25% or sole active director) aged 65-75
    scores highest; scales 0 at 60 -> 1.0 at 68-72 -> taper to 0.6 at 78."""
    now = _as_date(now)
    active_directors = [p for p in people if p.get("role") == "director" and p.get("is_active")]
    sole_director = len(active_directors) == 1

    candidates = []
    for person in people:
        if not person.get("is_active"):
            continue
        is_controlling_psc = (
            person.get("role") == "psc" and person.get("ownership_pct_band") in _CONTROLLING_PSC_BANDS
        )
        is_sole_director = person.get("role") == "director" and sole_director
        if not (is_controlling_psc or is_sole_director):
            continue
        age = _age_years(person.get("birth_year"), person.get("birth_month"), now)
        if age is None:
            continue
        value = _retirement_curve(age)
        candidates.append(
            {
                "name": person.get("name"),
                "role": person.get("role"),
                "age_years": age,
                "value": value,
            }
        )

    if not candidates:
        active_people = [p for p in people if p.get("is_active")]
        if not people:
            reason = "no officers on record"
        elif not active_people:
            reason = "no active officers on record (company appears dissolved/no active board)"
        else:
            controlling_present = any(
                (p.get("role") == "psc" and p.get("ownership_pct_band") in _CONTROLLING_PSC_BANDS)
                or (p.get("role") == "director" and sole_director)
                for p in active_people
            )
            reason = (
                "controlling director/PSC identified but date of birth unknown"
                if controlling_present
                else "no controlling director or PSC identified among active officers"
            )
        return 0.0, {"candidates": []}, reason

    best = max(candidates, key=lambda c: c["value"])
    rationale = (
        f"{best['name'] or 'controlling director'} aged {best['age_years']:.0f} "
        f"-> retirement-window signal {best['value']:.2f}"
    )
    return best["value"], {"candidates": candidates, "selected": best}, rationale


def _tenure_curve(tenure_years: float) -> float:
    """0.5 at >=12yrs -> 1.0 at >=20yrs, linear in between (spec 02 §4)."""
    if tenure_years < 12:
        return 0.0
    if tenure_years >= 20:
        return 1.0
    return round(0.5 + (tenure_years - 12) / 8.0 * 0.5, 4)


def long_single_owner_tenure(people: list[dict]) -> SignalResult:
    """Same person director >=12yrs (0.5) -> >=20yrs (1.0), AND <=2 other
    active directorships. Reads pre-derived ``tenure_years`` /
    ``other_active_directorships`` (spec 01 §2) rather than computing tenure
    itself — no ``now`` parameter per CONTRACT.md."""
    candidates = []
    for person in people:
        if person.get("role") != "director" or not person.get("is_active"):
            continue
        tenure = person.get("tenure_years")
        if tenure is None:
            continue
        other = person.get("other_active_directorships")
        disqualified = other is not None and other > 2
        value = 0.0 if disqualified else _tenure_curve(tenure)
        candidates.append(
            {
                "name": person.get("name"),
                "tenure_years": tenure,
                "other_active_directorships": other,
                "disqualified": disqualified,
                "value": value,
            }
        )

    if not candidates:
        active_directors = [p for p in people if p.get("role") == "director" and p.get("is_active")]
        if not people:
            reason = "no officers on record"
        elif not active_directors:
            reason = "no active directors on record (company appears dissolved/no active board)"
        else:
            reason = "no active director with known tenure"
        return 0.0, {"candidates": []}, reason

    best = max(candidates, key=lambda c: c["value"])
    if best["disqualified"]:
        rationale = (
            f"{best['name'] or 'director'} meets the tenure threshold but has "
            f"{best['other_active_directorships']} other active directorships (>2) -> disqualified"
        )
    else:
        other_desc = (
            "unknown" if best["other_active_directorships"] is None else str(best["other_active_directorships"])
        )
        rationale = (
            f"{best['name'] or 'director'} tenure {best['tenure_years']:.1f}y, "
            f"{other_desc} other directorships -> {best['value']:.2f}"
        )
    return best["value"], {"candidates": candidates, "selected": best}, rationale


def board_psc_event_recent(events: list[dict], now: date | datetime) -> SignalResult:
    """Director termination / PSC change / family member off the board within
    18 months -> 1.0 decaying linearly with the age of the event."""
    now = _as_date(now)
    candidates = []
    for event in events:
        raw_date = event.get("date")
        if raw_date is None:
            continue
        try:
            event_date = _as_date(raw_date)
        except (ValueError, TypeError):
            continue
        age_days = (now - event_date).days
        age_months = age_days / 30.44
        if age_days < 0 or age_months > 18:
            continue
        value = round(max(0.0, 1.0 - age_months / 18.0), 4)
        candidates.append(
            {
                "type": event.get("type"),
                "date": event_date.isoformat(),
                "age_months": round(age_months, 1),
                "value": value,
            }
        )

    if not candidates:
        reason = "no director/PSC change in the last 18 months" if events else "no board/PSC events on record"
        return 0.0, {"events": []}, reason

    best = max(candidates, key=lambda c: c["value"])
    rationale = f"{best['type'] or 'board/PSC event'} {best['age_months']:.1f} months ago -> {best['value']:.2f}"
    return best["value"], {"events": candidates, "selected": best}, rationale
