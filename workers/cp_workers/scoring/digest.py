"""Weekly digest — spec 02 §5/§6.

``build_digest()`` assembles new qualifiers, watchlist fires, newly-held
companies, and run health stats for the last 7 days into a plain dict.
``send_digest(content)`` emails it via Resend.

Per the build brief for this module: ``send_digest`` must never raise if
``resend_api_key`` is unset — it skips sending and says so in the return
value. That means this function intentionally returns a small status dict
(``{"sent": bool, "reason": str | None, "recipients": list[str]}``) rather
than ``None`` — a deliberate, documented deviation from the plain ``-> None``
sketched in CONTRACT.md, since silently returning ``None`` either way would
make "did it actually send" unobservable to the caller/tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from cp_workers import db
from cp_workers.config import settings
from cp_workers.scoring.pipeline import _get_rubric

DEFAULT_LOOKBACK_DAYS = 7


def _fetch_companies_by_ids(client, company_ids: list[str]) -> dict[str, dict]:
    if not company_ids:
        return {}
    unique_ids = list(dict.fromkeys(company_ids))
    resp = client.table("companies").select("*").in_("id", unique_ids).execute()
    return {row["id"]: row for row in (resp.data or [])}


def _new_qualifiers(client, since_iso: str, shortlist_threshold: float) -> list[dict]:
    resp = (
        client.table("scores")
        .select("*")
        .eq("gate_result", "pass")
        .gte("scored_at", since_iso)
        .order("scored_at", desc=True)
        .execute()
    )
    rows = [
        r
        for r in (resp.data or [])
        if r.get("total_score") is not None and r["total_score"] >= shortlist_threshold
    ]
    companies_by_id = _fetch_companies_by_ids(client, [r["company_id"] for r in rows])

    qualifiers = []
    for row in sorted(rows, key=lambda r: r["total_score"], reverse=True):
        company = companies_by_id.get(row["company_id"], {})
        angles = row.get("value_angles") or []
        qualifiers.append(
            {
                "company_number": company.get("company_number"),
                "name": company.get("legal_name"),
                "score": row["total_score"],
                "angle": angles[0] if angles else None,
                "link": f"/companies/{company.get('company_number')}",
            }
        )
    return qualifiers


def _watchlist_fires(client, since_iso: str) -> list[dict]:
    resp = (
        client.table("watchlist_items")
        .select("*")
        .eq("status", "fired")
        .gte("updated_at", since_iso)
        .execute()
    )
    rows = resp.data or []
    companies_by_id = _fetch_companies_by_ids(client, [r["company_id"] for r in rows])
    fires = []
    for row in rows:
        company = companies_by_id.get(row["company_id"], {})
        fires.append(
            {
                "company_number": company.get("company_number"),
                "name": company.get("legal_name"),
                "reason": row.get("reason"),
                "link": f"/companies/{company.get('company_number')}",
            }
        )
    return fires


def _newly_held(client, since_iso: str) -> list[dict]:
    resp = (
        client.table("scores")
        .select("*")
        .eq("gate_result", "hold")
        .gte("scored_at", since_iso)
        .order("scored_at", desc=True)
        .execute()
    )
    rows = resp.data or []
    latest_per_company: dict[str, dict] = {}
    for row in rows:
        if row["company_id"] not in latest_per_company:
            latest_per_company[row["company_id"]] = row
    companies_by_id = _fetch_companies_by_ids(client, list(latest_per_company.keys()))

    held = []
    for company_id, row in latest_per_company.items():
        company = companies_by_id.get(company_id, {})
        detail = row.get("gate_detail") or {}
        failing_tests = [name for name, result in detail.items() if result.get("result") == "hold"]
        held.append(
            {
                "company_number": company.get("company_number"),
                "name": company.get("legal_name"),
                "failing_tests": failing_tests,
                "link": f"/companies/{company.get('company_number')}",
            }
        )
    return held


def _run_health(client, since_iso: str) -> dict:
    resp = client.table("jobs").select("*").gte("started_at", since_iso).execute()
    rows = resp.data or []
    by_job: dict[str, dict] = {}
    for row in rows:
        job_name = row["job_name"]
        entry = by_job.setdefault(
            job_name, {"job_name": job_name, "runs": 0, "succeeded": 0, "failed": 0, "failures": []}
        )
        entry["runs"] += 1
        if row["status"] == "succeeded":
            entry["succeeded"] += 1
        elif row["status"] == "failed":
            entry["failed"] += 1
            if row.get("error"):
                entry["failures"].append({"run_key": row.get("run_key"), "error": row["error"]})
        stats_failures = (row.get("stats") or {}).get("failures") or []
        entry["failures"].extend(stats_failures)
    return {"jobs": list(by_job.values()), "total_runs": len(rows)}


def build_digest(*, since: datetime | None = None) -> dict:
    """Assemble the weekly digest content dict (spec 02 §6)."""
    client = db.get_client()
    since = since or (datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    since_iso = since.isoformat()

    rubric = _get_rubric(client, None)
    shortlist_threshold = rubric.get("gate_config", {}).get("shortlist_threshold", 60)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period_since": since_iso,
        "new_qualifiers": _new_qualifiers(client, since_iso, shortlist_threshold),
        "watchlist_fires": _watchlist_fires(client, since_iso),
        "newly_held": _newly_held(client, since_iso),
        "run_health": _run_health(client, since_iso),
    }


def _render_html(content: dict) -> str:
    def _rows(items: list[dict], fields: list[str]) -> str:
        if not items:
            return "<p><em>None this week.</em></p>"
        lines = ["<ul>"]
        for item in items:
            parts = " — ".join(str(item.get(f, "")) for f in fields)
            lines.append(f"<li>{parts}</li>")
        lines.append("</ul>")
        return "\n".join(lines)

    run_health = content.get("run_health", {})
    job_lines = "".join(
        f"<li>{j['job_name']}: {j['succeeded']}/{j['runs']} succeeded"
        f"{', ' + str(len(j['failures'])) + ' failure(s)' if j['failures'] else ''}</li>"
        for j in run_health.get("jobs", [])
    )

    return f"""
    <h2>Common Partners weekly digest</h2>
    <p>Generated {content.get('generated_at')}, covering since {content.get('period_since')}.</p>
    <h3>New qualifiers</h3>
    {_rows(content.get('new_qualifiers', []), ['name', 'score', 'angle', 'link'])}
    <h3>Watchlist fires</h3>
    {_rows(content.get('watchlist_fires', []), ['name', 'reason', 'link'])}
    <h3>Newly held</h3>
    {_rows(content.get('newly_held', []), ['name', 'failing_tests', 'link'])}
    <h3>Run health</h3>
    <ul>{job_lines}</ul>
    """


def send_digest(content: dict) -> dict:
    """Email the digest via Resend. Never raises: a missing API key or
    recipients list results in a skipped-send status, not an exception.
    """
    if not settings.resend_api_key:
        return {"sent": False, "reason": "RESEND_API_KEY not configured — skipped", "recipients": []}

    recipients = settings.digest_recipients
    if not recipients:
        return {"sent": False, "reason": "no digest recipients configured (DIGEST_TO)", "recipients": []}

    try:
        import resend

        resend.api_key = settings.resend_api_key
        html = _render_html(content)
        resend.Emails.send(
            {
                "from": "Common Partners Digest <digest@commonpartners.dev>",
                "to": recipients,
                "subject": f"Common Partners weekly digest — {content.get('generated_at', '')[:10]}",
                "html": html,
            }
        )
        return {"sent": True, "reason": None, "recipients": recipients}
    except Exception as exc:  # noqa: BLE001 - a failed send must not crash the run
        return {"sent": False, "reason": f"resend send failed: {exc}", "recipients": recipients}
