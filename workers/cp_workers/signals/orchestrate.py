"""Signals orchestration for `cli.py compute-signals` — wires the succession
and consolidation signal families (spec 02 §3b: recomputed from refreshed CH
data, ahead of and independent from enrichment) to the database.

Not owned by any single build agent (see CONTRACT.md) — assembled in the
integration pass since it's the one place these two families meet. The
latent_upside family is *not* handled here: Agent B's
`cp_workers.enrichment.orchestrate.enrich_company` already computes and
writes those signals as part of enrichment (its inputs — review_strength,
digital_maturity, distribution_breadth — only exist once a company has been
enriched), so recomputing them here would just double up rows.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from cp_workers import db
from cp_workers.signals import consolidation, succession

SIGNAL_VERSION = "1.0.0"


def _people_for_signals(client, company_id: str) -> list[dict]:
    resp = (
        client.table("company_people")
        .select(
            "role, is_active, tenure_years, other_active_directorships, "
            "ownership_pct_band, people(name, birth_year, birth_month)"
        )
        .eq("company_id", company_id)
        .execute()
    )
    people = []
    for row in resp.data or []:
        person = row.get("people") or {}
        people.append(
            {
                "name": person.get("name"),
                "role": row.get("role"),
                "is_active": bool(row.get("is_active")),
                "birth_year": person.get("birth_year"),
                "birth_month": person.get("birth_month"),
                "ownership_pct_band": row.get("ownership_pct_band"),
                "tenure_years": row.get("tenure_years"),
                "other_active_directorships": row.get("other_active_directorships"),
            }
        )
    return people


def _events_for_signals(client, company_id: str) -> list[dict]:
    """Board/PSC change events derived from resignations on record. A real
    filing-history diff (spec 02 §3b "change events") would be richer, but
    resigned_on already captures the departures board_psc_event_recent cares
    about without needing a separate event log."""
    resp = (
        client.table("company_people")
        .select("role, resigned_on")
        .eq("company_id", company_id)
        .not_.is_("resigned_on", "null")
        .execute()
    )
    events = []
    for row in resp.data or []:
        event_type = "psc_change" if row.get("role") == "psc" else "director_terminated"
        events.append({"type": event_type, "date": row["resigned_on"], "detail": None})
    return events


def _write_signal(client, *, company_id: str, family: str, name: str, result: tuple[float, dict, str]) -> None:
    value, evidence, rationale = result
    client.table("signals").insert(
        {
            "company_id": company_id,
            "family": family,
            "name": name,
            "value": value,
            "evidence": evidence,
            "rationale": rationale,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "signal_version": SIGNAL_VERSION,
        }
    ).execute()


def _fetch_universe(client) -> list[dict]:
    resp = (
        client.table("companies")
        .select("company_number, sector_tags, size_band, employee_count, revenue_estimate")
        .execute()
    )
    return resp.data or []


def compute_signals_for_company(
    company_number: str, *, universe_companies: list[dict] | None = None
) -> dict[str, float]:
    """Succession + consolidation signals for one company, computed purely
    from data already fetched during `refresh` (CH profile/officers/PSC) —
    safe to run before enrichment exists."""
    client = db.get_client()
    company = db.get_company_by_number(company_number)
    if company is None:
        raise ValueError(f"unknown company_number {company_number!r}")
    company_id = company["id"]
    today = date.today()

    people = _people_for_signals(client, company_id)
    events = _events_for_signals(client, company_id)
    universe_companies = universe_companies if universe_companies is not None else _fetch_universe(client)

    written: dict[str, float] = {}
    for name, result in (
        ("director_retirement_window", succession.director_retirement_window(people, today)),
        ("long_single_owner_tenure", succession.long_single_owner_tenure(people)),
        ("board_psc_event_recent", succession.board_psc_event_recent(events, today)),
    ):
        _write_signal(client, company_id=company_id, family="succession", name=name, result=result)
        written[name] = result[0]

    for name, result in (
        ("fragmented_subcategory", consolidation.fragmented_subcategory(universe_companies, company)),
        ("adjacency", consolidation.adjacency(company, [])),
    ):
        _write_signal(client, company_id=company_id, family="consolidation", name=name, result=result)
        written[name] = result[0]

    return written


def compute_signals(
    company_numbers: list[str] | None = None, *, changed_only: bool = False
) -> dict[str, Any]:
    """CLI-facing loop (`cli.py compute-signals`). One company's failure never
    aborts the batch (spec 00 §4 "idempotent jobs")."""
    client = db.get_client()

    if company_numbers is None:
        if changed_only:
            # `like refresh%` so tiered runs (refresh-new / refresh-shard,
            # spec 09 §3) feed signal recompute too, not just weekly hot.
            last_refresh = (
                client.table("jobs")
                .select("stats")
                .like("job_name", "refresh%")
                .eq("status", "succeeded")
                .order("finished_at", desc=True)
                .limit(1)
                .execute()
            )
            stats = (last_refresh.data[0]["stats"] if last_refresh.data else {}) or {}
            company_numbers = stats.get("changed_company_numbers", [])
        else:
            # Paged past PostgREST's 1k cap — the universe is tens of
            # thousands once spec 09 widens discovery.
            company_numbers = []
            page = 0
            while True:
                resp = (
                    client.table("companies")
                    .select("company_number")
                    .in_("lifecycle", ["discovered", "enriched", "scored"])
                    .range(page * 1000, page * 1000 + 999)
                    .execute()
                )
                batch = [row["company_number"] for row in (resp.data or [])]
                company_numbers.extend(batch)
                if len(batch) < 1000:
                    break
                page += 1

    universe_companies = _fetch_universe(client)
    processed, failures = [], []
    for number in company_numbers:
        try:
            compute_signals_for_company(number, universe_companies=universe_companies)
            processed.append(number)
        except Exception as exc:  # noqa: BLE001 - one company failing must not abort the batch
            failures.append({"company_number": number, "error": str(exc)})

    return {"processed": len(processed), "failures": failures}
