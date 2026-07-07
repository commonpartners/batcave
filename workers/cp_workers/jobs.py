"""jobs table helpers — idempotency + run stats for every cron-invoked CLI command.

Usage:
    job = start_job("refresh", run_key="2026-W28")
    if job is None:
        return  # already succeeded this run_key
    try:
        ...
        finish_job(job, "succeeded", stats={"scanned": 42})
    except Exception as exc:
        finish_job(job, "failed", error=str(exc))
        raise
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from cp_workers.db import get_client


def start_job(job_name: str, run_key: str) -> dict | None:
    """Create (or resume) a jobs row. Returns None if this run_key already succeeded."""
    client = get_client()
    existing = (
        client.table("jobs")
        .select("*")
        .eq("job_name", job_name)
        .eq("run_key", run_key)
        .limit(1)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        if row["status"] == "succeeded":
            return None
        return row

    resp = (
        client.table("jobs")
        .insert(
            {
                "job_name": job_name,
                "run_key": run_key,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "stats": {},
            }
        )
        .execute()
    )
    return resp.data[0]


def finish_job(
    job: dict,
    status: str,
    *,
    stats: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    client = get_client()
    client.table("jobs").update(
        {
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "stats": stats or {},
            "error": error,
        }
    ).eq("id", job["id"]).execute()
