"""Watchlist — spec 02 §5.

- **Auto-entry:** a gate-pass company scoring >= ``watchlist_auto_score_threshold``
  (config, seeded 70) with no succession signal >= ``watchlist_succession_signal_floor``
  (config, seeded 0.5) enters the watchlist automatically. Manual entry from
  the app is a separate, already-covered insert path (not this module's
  concern — this module only implements the automatic side plus the weekly
  fire/expire sweep, which applies to every watching item regardless of how
  it was added).
- **Weekly fire:** any watching company whose latest succession signal
  crosses the floor -> ``status='fired'``, pushed to pipeline ``inbox``.
- **Expiry:** ``deprioritise_after`` passed with no fire -> ``status='expired'``,
  company lifecycle -> ``archived`` (reversible in the UI).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from cp_workers import db
from cp_workers.scoring.pipeline import _get_rubric, _latest_signals, _upsert_pipeline_item

AVG_DAYS_PER_MONTH = 30.44


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _latest_succession_signal_max(client, company_id: str) -> float | None:
    signals_by_name = _latest_signals(client, company_id)
    values = [
        row["value"] for row in signals_by_name.values() if row.get("family") == "succession"
    ]
    return max(values) if values else None


def _existing_watchlist_company_ids(client) -> set[str]:
    resp = client.table("watchlist_items").select("company_id").execute()
    return {row["company_id"] for row in (resp.data or [])}


def _latest_pass_scores(client) -> dict[str, dict]:
    """Latest gate-pass score row per company_id (dict company_id -> score row)."""
    resp = (
        client.table("scores")
        .select("*")
        .eq("gate_result", "pass")
        .order("scored_at", desc=True)
        .execute()
    )
    latest: dict[str, dict] = {}
    for row in resp.data or []:
        company_id = row["company_id"]
        if company_id not in latest:
            latest[company_id] = row
    return latest


def _add_to_watchlist(client, company_id: str, reason: str, patience_months: float) -> None:
    now = datetime.now(timezone.utc)
    deprioritise_after = now + timedelta(days=patience_months * AVG_DAYS_PER_MONTH)
    client.table("watchlist_items").insert(
        {
            "company_id": company_id,
            "reason": reason,
            "added_at": now.isoformat(),
            "last_signal_check": now.isoformat(),
            "deprioritise_after": deprioritise_after.isoformat(),
            "status": "watching",
        }
    ).execute()


def watchlist_check() -> dict:
    """Runs the auto-entry pass then the weekly fire/expire sweep.

    Returns a stats dict: ``{"auto_entered", "fired", "expired", "checked",
    "errors"}`` — one company's failure never aborts the run (each step is
    wrapped so it lands in ``errors`` instead, per spec 02 §6 failure
    discipline).
    """
    client = db.get_client()
    rubric = _get_rubric(client, None)
    gate_config = rubric.get("gate_config", {})
    auto_score_threshold = gate_config.get("watchlist_auto_score_threshold", 70)
    succession_floor = gate_config.get("watchlist_succession_signal_floor", 0.5)
    patience_months = db.get_config("watchlist_patience_months", 24)
    try:
        patience_months = float(patience_months)
    except (TypeError, ValueError):
        patience_months = 24.0

    stats: dict[str, Any] = {"auto_entered": 0, "fired": 0, "expired": 0, "checked": 0, "errors": []}

    # --- 1. auto-entry ---
    already_on_watchlist = _existing_watchlist_company_ids(client)
    for company_id, score_row in _latest_pass_scores(client).items():
        if company_id in already_on_watchlist:
            continue
        total_score = score_row.get("total_score")
        if total_score is None or total_score < auto_score_threshold:
            continue
        try:
            succession_signal_max = _latest_succession_signal_max(client, company_id)
            if succession_signal_max is not None and succession_signal_max >= succession_floor:
                continue  # already has a strong succession signal — not a watchlist case
            _add_to_watchlist(
                client,
                company_id,
                reason=(
                    f"auto: gate pass + score {total_score} >= {auto_score_threshold}, "
                    f"no succession signal >= {succession_floor}"
                ),
                patience_months=patience_months,
            )
            stats["auto_entered"] += 1
        except Exception as exc:  # noqa: BLE001 - one company's failure must not abort the run
            stats["errors"].append({"company_id": company_id, "step": "auto_entry", "error": str(exc)})

    # --- 2. weekly fire / expire sweep over every currently-watching item ---
    watching_items = (
        client.table("watchlist_items").select("*").eq("status", "watching").execute().data or []
    )
    now = datetime.now(timezone.utc)
    for item in watching_items:
        stats["checked"] += 1
        company_id = item["company_id"]
        try:
            succession_signal_max = _latest_succession_signal_max(client, company_id)
            if succession_signal_max is not None and succession_signal_max >= succession_floor:
                client.table("watchlist_items").update(
                    {"status": "fired", "last_signal_check": now.isoformat()}
                ).eq("id", item["id"]).execute()
                _upsert_pipeline_item(client, company_id)
                stats["fired"] += 1
                continue

            deprioritise_after = _parse_dt(item.get("deprioritise_after"))
            if deprioritise_after is not None and deprioritise_after <= now:
                client.table("watchlist_items").update(
                    {"status": "expired", "last_signal_check": now.isoformat()}
                ).eq("id", item["id"]).execute()
                client.table("companies").update({"lifecycle": "archived"}).eq(
                    "id", company_id
                ).execute()
                stats["expired"] += 1
                continue

            client.table("watchlist_items").update({"last_signal_check": now.isoformat()}).eq(
                "id", item["id"]
            ).execute()
        except Exception as exc:  # noqa: BLE001
            stats["errors"].append({"company_id": company_id, "step": "weekly_check", "error": str(exc)})

    return stats
