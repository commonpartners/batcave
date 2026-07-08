"""Single entry point: `python -m cp_workers.cli <command>` (spec 00 §3).

Every command that's cron-invoked (spec 02 §6) acquires a `jobs` row keyed by
a run_key (ISO week for weekly jobs, month for monthly ones) via
`cp_workers.jobs` — re-running the same run_key after success is a no-op, and
an individual company failing never aborts the whole run (spec 00 §4).

This module is the integration point between the four parallel build
workstreams (see workers/CONTRACT.md) — it owns no business logic of its own
beyond looping/job-bookkeeping/output formatting.
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timezone
from typing import Any

import click

from cp_workers import db, jobs
from cp_workers.config import settings
from cp_workers.connectors.companies_house import CompaniesHouseClient
from cp_workers.connectors.discovery import (
    discover_universe,
    export_phase0,
    intake_from_csv,
    officers_and_psc_to_people,
    refresh_universe_company,
)
from cp_workers.enrichment.orchestrate import enrich_company
from cp_workers.scoring.calibration import run_calibration_audit
from cp_workers.scoring.pregate import enrichment_candidates, run_pregate
from cp_workers.scoring.digest import build_digest, send_digest
from cp_workers.scoring.pipeline import score_company
from cp_workers.scoring.watchlist import watchlist_check
from cp_workers.signals.orchestrate import compute_signals


_OFFICER_ID_RE = re.compile(r"/officers/([^/]+)/appointments")
_PSC_ID_RE = re.compile(r"/persons-with-significant-control/[^/]+/([^/]+)$")


def _extract_ch_person_id(item: dict) -> str | None:
    """Best-effort stable id for dedup across weekly refreshes: officers carry
    it in their self-appointments link, PSCs in their self link. Falls back to
    None (a fresh `people` row each refresh) rather than guessing — this is a
    known simplification, not a guess at identity."""
    links = item.get("links") or {}
    officer_link = (links.get("officer") or {}).get("appointments")
    if officer_link:
        m = _OFFICER_ID_RE.search(officer_link)
        if m:
            return f"officer:{m.group(1)}"
    self_link = links.get("self")
    if self_link:
        m = _PSC_ID_RE.search(self_link)
        if m:
            return f"psc:{m.group(1)}"
    return None


def _sync_people(company_id: str, company_number: str, client: CompaniesHouseClient) -> None:
    """Persists officers + PSCs into `people`/`company_people` (spec 01 §2).

    Agent A's `officers_and_psc_to_people` maps CH payloads into the shape the
    succession signals expect, but nothing wired that mapping to the database
    before now — `refresh_universe_company` only diffs/upserts the profile.
    Re-fetches officers/PSC (already throttled + cached via `record_source`
    inside the client, so this is not extra network cost beyond one more
    cached-and-recorded call pair) so the raw payloads are available here for
    the officer/PSC-id extraction `officers_and_psc_to_people` doesn't do.
    """
    db_client = db.get_client()
    officers_payload = client.get_officers(company_number)
    psc_payload = client.get_psc(company_number)
    today = date.today()

    # officers_and_psc_to_people silently skips non-director/secretary officer
    # roles (spec 02 §4 only cares about those two) — mapping each raw item
    # through the same single-item function keeps the (person, raw_item)
    # pairing exact instead of zipping two lists of different lengths.
    officer_items = list((officers_payload or {}).get("items", []))
    psc_items = list((psc_payload or {}).get("items", []))
    pairs: list[tuple[dict, dict]] = []
    for item in officer_items:
        mapped = officers_and_psc_to_people({"items": [item]}, {"items": []}, today)
        if mapped:
            pairs.append((mapped[0], item))
    for item in psc_items:
        mapped = officers_and_psc_to_people({"items": []}, {"items": [item]}, today)
        if mapped:
            pairs.append((mapped[0], item))

    for person, raw_item in pairs:
        ch_person_id = _extract_ch_person_id(raw_item)
        person_id = None
        if ch_person_id:
            existing = db_client.table("people").select("id").eq("ch_officer_id", ch_person_id).limit(1).execute()
            if existing.data:
                person_id = existing.data[0]["id"]
                db_client.table("people").update(
                    {"name": person["name"], "birth_year": person["birth_year"], "birth_month": person["birth_month"]}
                ).eq("id", person_id).execute()
        if person_id is None:
            resp = db_client.table("people").insert(
                {
                    "ch_officer_id": ch_person_id,
                    "name": person["name"],
                    "birth_year": person["birth_year"],
                    "birth_month": person["birth_month"],
                }
            ).execute()
            person_id = resp.data[0]["id"]

        appointed_on = raw_item.get("appointed_on")
        resigned_on = raw_item.get("resigned_on") or raw_item.get("ceased_on")
        cp_fields = {
            "company_id": company_id,
            "person_id": person_id,
            "role": person["role"],
            "appointed_on": appointed_on,
            "resigned_on": resigned_on,
            "ownership_pct_band": person["ownership_pct_band"],
            "tenure_years": person["tenure_years"],
            "other_active_directorships": person["other_active_directorships"],
        }
        existing_cp = (
            db_client.table("company_people")
            .select("id")
            .eq("company_id", company_id)
            .eq("person_id", person_id)
            .eq("role", person["role"])
            .execute()
        )
        if existing_cp.data:
            db_client.table("company_people").update(cp_fields).eq("id", existing_cp.data[0]["id"]).execute()
        else:
            db_client.table("company_people").insert(cp_fields).execute()


def _iso_week(dt: date | None = None) -> str:
    dt = dt or date.today()
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def _iso_month(dt: date | None = None) -> str:
    dt = dt or date.today()
    return f"{dt.year}-{dt.month:02d}"


def _pending_company_numbers(lifecycles: list[str]) -> list[str]:
    client = db.get_client()
    resp = client.table("companies").select("company_number").in_("lifecycle", lifecycles).execute()
    return [row["company_number"] for row in (resp.data or [])]


def _send_alert_email(job_name: str, error: str, run_url: str | None) -> None:
    """Spec 02 §6: "Any job that fails outright sends an alert email." Best
    effort — an alert that itself fails to send must never mask the original
    job failure, so this only logs, never raises."""
    if not settings.resend_api_key or not settings.digest_recipients:
        click.echo(f"[alert skipped: no RESEND_API_KEY/DIGEST_TO configured] {job_name} failed: {error}", err=True)
        return
    try:
        import resend

        resend.api_key = settings.resend_api_key
        link = f"<p><a href=\"{run_url}\">View run</a></p>" if run_url else ""
        resend.Emails.send(
            {
                "from": "Common Partners Alerts <alerts@commonpartners.dev>",
                "to": settings.digest_recipients,
                "subject": f"[Common Partners] job '{job_name}' failed",
                "html": f"<p>Job <b>{job_name}</b> failed:</p><pre>{error}</pre>{link}",
            }
        )
    except Exception as exc:  # noqa: BLE001 - alerting must never raise
        click.echo(f"[alert send failed: {exc}] {job_name} failed: {error}", err=True)


@click.group()
def main() -> None:
    pass


def _download_snapshot() -> str:
    """Fetch this month's Free Company Data Product (spec 02 §3a) so the
    workflow can call bare `discover` — the file is ~450MB zipped, streamed
    to a temp dir."""
    import tempfile
    from pathlib import Path

    import httpx

    month = date.today().strftime("%Y-%m-01")
    url = f"https://download.companieshouse.gov.uk/BasicCompanyDataAsOneFile-{month}.zip"
    click.echo(f"discover: downloading {url}")
    tmpdir = Path(tempfile.mkdtemp(prefix="ch-snapshot-"))
    zip_path = tmpdir / "snapshot.zip"
    with httpx.stream("GET", url, timeout=600, follow_redirects=True) as resp:
        resp.raise_for_status()
        with open(zip_path, "wb") as fh:
            for chunk in resp.iter_bytes(1024 * 1024):
                fh.write(chunk)
    return str(zip_path)


@main.command()
@click.option("--file", "snapshot_path", default=None, help="Path to the CH Free Company Data Product CSV/zip (downloaded automatically if omitted).")
def discover(snapshot_path: str | None) -> None:
    """Monthly bulk-snapshot universe scan (spec 02 §3a)."""
    job = jobs.start_job("discover", _iso_month())
    if job is None:
        click.echo("discover: this month's run already succeeded, skipping.")
        return
    try:
        stats = discover_universe(snapshot_path or _download_snapshot())
        jobs.finish_job(job, "succeeded", stats=vars(stats))
        click.echo(
            f"discover: scanned={stats.rows_scanned} candidates={stats.candidates} "
            f"upserted={stats.upserted} filtered_out={stats.filtered_out} errors={len(stats.errors)}"
        )
    except Exception as exc:
        jobs.finish_job(job, "failed", error=str(exc))
        _send_alert_email("discover", str(exc), None)
        raise


def _paged_rows(query_builder) -> list[dict]:
    """Page past PostgREST's 1k row cap — mandatory once the universe is
    tens of thousands (spec 09)."""
    rows: list[dict] = []
    page = 0
    while True:
        resp = query_builder().range(page * 1000, page * 1000 + 999).execute()
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        page += 1


def _refresh_targets(scope: str, shard: int | None) -> list[str]:
    """Refresh tiers (spec 09 §3): `new` = discovered companies with no CH
    officer detail yet (nightly backfill, ordered oldest-incorporation first
    as a stable proxy for T0 priority); `hot` = pregate-eligible + in-play
    companies (weekly); `shard` = cold-tail monthly quarter; `all` = everyone."""
    client = db.get_client()
    if scope == "new":
        universe = _paged_rows(
            lambda: client.table("companies")
            .select("id,company_number,incorporation_date")
            .eq("lifecycle", "discovered")
            .order("incorporation_date")
        )
        with_detail = {
            r["company_id"]
            for r in _paged_rows(
                lambda: client.table("source_records")
                .select("company_id")
                .eq("source", "companies_house_officers")
            )
            if r.get("company_id")
        }
        return [c["company_number"] for c in universe if c["id"] not in with_detail]
    if scope == "hot":
        hot_threshold = float(db.get_config("pregate_hot_threshold", 0.60))
        rows = _paged_rows(
            lambda: client.table("companies")
            .select("company_number,pregate_score,lifecycle")
            .neq("lifecycle", "archived")
        )
        return [
            r["company_number"]
            for r in rows
            if (r.get("pregate_score") or 0) >= hot_threshold
            or r.get("lifecycle") in ("enriched", "scored", "shortlisted", "watchlist")
        ]
    rows = _paged_rows(
        lambda: client.table("companies").select("company_number").neq("lifecycle", "archived")
    )
    numbers = [r["company_number"] for r in rows]
    if scope == "shard":
        import hashlib

        return [
            n for n in numbers
            if int(hashlib.sha256(n.encode()).hexdigest(), 16) % 4 == (shard or 0)
        ]
    return numbers


@main.command()
@click.option("--new", "scope_new", is_flag=True, help="Backfill CH detail for discovered companies with none yet (nightly).")
@click.option("--shard", type=int, default=None, help="Cold-tail shard 0-3 (monthly rotation).")
@click.option("--all", "scope_all", is_flag=True, help="Refresh the entire universe (small universes only).")
@click.option("--max-companies", type=int, default=None, help="Cap targets this run (rate-limit budgeting, spec 09 §3).")
def refresh(scope_new: bool, shard: int | None, scope_all: bool, max_companies: int | None) -> None:
    """CH detail refresh — default scope `hot` (spec 09 §3)."""
    scope = "new" if scope_new else "shard" if shard is not None else "all" if scope_all else "hot"
    job_name = "refresh" if scope == "hot" else f"refresh-{scope}"
    run_key = _iso_week() if scope == "hot" else f"{scope}-{date.today().isoformat()}"
    job = jobs.start_job(job_name, run_key)
    if job is None:
        click.echo(f"{job_name}: this run already succeeded, skipping.")
        return
    try:
        numbers = _refresh_targets(scope, shard)
        if max_companies:
            numbers = numbers[:max_companies]
        changed: list[str] = []
        failures: list[dict[str, str]] = []
        client = CompaniesHouseClient()
        try:
            for number in numbers:
                try:
                    if refresh_universe_company(number, client=client):
                        changed.append(number)
                    company = db.get_company_by_number(number)
                    if company:
                        _sync_people(company["id"], number, client)
                except Exception as exc:  # noqa: BLE001 - one company must not abort the run
                    failures.append({"company_number": number, "error": str(exc)})
        finally:
            client.close()
        stats = {"scope": scope, "scanned": len(numbers), "changed_company_numbers": changed, "failures": failures}
        jobs.finish_job(job, "succeeded", stats=stats)
        click.echo(f"{job_name}: scanned={len(numbers)} changed={len(changed)} failures={len(failures)}")
    except Exception as exc:
        jobs.finish_job(job, "failed", error=str(exc))
        _send_alert_email(job_name, str(exc), None)
        raise


@main.command("compute-signals")
@click.option("--changed-only", is_flag=True, help="Only recompute for companies the last refresh marked changed.")
@click.option("--company", "company_number", default=None, help="Limit to a single company_number.")
def compute_signals_cmd(changed_only: bool, company_number: str | None) -> None:
    """Succession + consolidation signals (spec 02 §4)."""
    job = jobs.start_job("compute-signals", _iso_week())
    if job is None:
        click.echo("compute-signals: this week's run already succeeded, skipping.")
        return
    try:
        numbers = [company_number] if company_number else None
        result = compute_signals(numbers, changed_only=changed_only)
        jobs.finish_job(job, "succeeded", stats=result)
        click.echo(f"compute-signals: processed={result['processed']} failures={len(result['failures'])}")
    except Exception as exc:
        jobs.finish_job(job, "failed", error=str(exc))
        _send_alert_email("compute-signals", str(exc), None)
        raise


@main.command()
@click.option("--company", "company_number", default=None, help="Limit to a single company_number.")
def pregate(company_number: str | None) -> None:
    """Free-data pre-gate scoring (spec 09 §4) — ranks the whole universe for
    enrichment priority using CH data only. Cheap; re-run any time weights change."""
    job = jobs.start_job("pregate", f"{date.today().isoformat()}")
    if job is None:
        click.echo("pregate: today's run already succeeded, skipping.")
        return
    try:
        result = run_pregate(company_numbers=[company_number] if company_number else None)
        jobs.finish_job(job, "succeeded", stats=result)
        click.echo(
            f"pregate: scored={result['scored']} eligible={result['eligible']} "
            f"(threshold={result['threshold']}) failed={result['failed']}"
        )
    except Exception as exc:
        jobs.finish_job(job, "failed", error=str(exc))
        _send_alert_email("pregate", str(exc), None)
        raise


@main.command()
@click.option("--file", "path", required=True, help="CSV with company_number or name(+website) columns.")
def intake(path: str) -> None:
    """Manual intake (spec 02 §7) — the Phase-1 path before automated discovery."""
    report = intake_from_csv(path)
    click.echo(f"intake: total={report.total_rows} resolved={report.resolved} created={report.created}")
    for row in report.unresolved:
        click.echo(f"  unresolved: {row}", err=True)


@main.command("export-phase0")
@click.option("--file", "out_path", required=True)
@click.option("--company-numbers", default=None, help="Comma-separated; default = every company in the DB.")
def export_phase0_cmd(out_path: str, company_numbers: str | None) -> None:
    """Phase-0 Excel export (spec 06 Phase 0)."""
    numbers = (
        [n.strip() for n in company_numbers.split(",") if n.strip()]
        if company_numbers
        else _pending_company_numbers(["discovered", "enriched", "scored", "watchlist", "shortlisted"])
    )
    export_phase0(numbers, out_path)
    click.echo(f"export-phase0: wrote {len(numbers)} companies to {out_path}")


@main.command()
@click.option("--pending", is_flag=True, help="Enrich pre-gate winners: above pregate_threshold, ranked by pregate_score, capped at enrichment_budget_per_week (spec 09 §5).")
@click.option("--company", "company_number", default=None, help="Limit to a single company_number.")
@click.option("--limit", type=int, default=None, help="Override enrichment_budget_per_week for this run.")
def enrich(pending: bool, company_number: str | None, limit: int | None) -> None:
    """Enrichment pipeline (spec 03) — budgeted promotion, never the whole universe."""
    if not pending and not company_number:
        raise click.UsageError("pass --pending or --company <number>")
    job = jobs.start_job("enrich", _iso_week())
    if job is None:
        click.echo("enrich: this week's run already succeeded, skipping.")
        return
    try:
        numbers = [company_number] if company_number else enrichment_candidates(limit)
        budget = int(db.get_config("llm_budget_per_run", 300))
        succeeded, run_failures = [], []
        # `enrich_company(..., job=job)` mutates job["stats"]["failures"] itself
        # (per-step failures, via Agent B's _run_step) — only a whole-company
        # exception (a bug outside the per-step retry/failure handling) is
        # caught here, so the two failure lists don't double-count.
        for number in numbers[:budget]:
            try:
                enrich_company(number, job=job)
                succeeded.append(number)
            except Exception as exc:  # noqa: BLE001 - one company must not abort the run
                run_failures.append({"company_number": number, "error": str(exc)})
        skipped = len(numbers) - len(numbers[:budget])
        stats = dict(job.get("stats") or {})
        stats["succeeded"] = len(succeeded)
        stats["run_failures"] = run_failures
        stats["skipped_over_budget"] = max(skipped, 0)
        jobs.finish_job(job, "succeeded", stats=stats)
        step_failures = len((job.get("stats") or {}).get("failures") or [])
        click.echo(
            f"enrich: succeeded={len(succeeded)} run_failures={len(run_failures)} "
            f"step_failures={step_failures} skipped_over_budget={max(skipped, 0)}"
        )
    except Exception as exc:
        jobs.finish_job(job, "failed", error=str(exc))
        _send_alert_email("enrich", str(exc), None)
        raise


@main.command()
@click.option("--pending", is_flag=True, help="Process every company at lifecycle 'enriched' or 'scored'.")
@click.option("--company", "company_number", default=None, help="Limit to a single company_number.")
@click.option("--rescore-all", is_flag=True, help="Rescore every company under --rubric.")
@click.option("--rubric", "rubric_version", default=None, help="Rubric version for --rescore-all.")
@click.option("--calibration-audit", "calibration_audit", is_flag=True, help="Run the monthly calibration audit.")
def score(
    pending: bool,
    company_number: str | None,
    rescore_all: bool,
    rubric_version: str | None,
    calibration_audit: bool,
) -> None:
    """Scoring engine (spec 04)."""
    if calibration_audit:
        job = jobs.start_job("calibration-audit", _iso_month())
        if job is None:
            click.echo("score --calibration-audit: this month's run already succeeded, skipping.")
            return
        try:
            benchmark = db.get_config("calibration_benchmark_company_numbers", [])
            result = run_calibration_audit(benchmark)
            jobs.finish_job(job, "succeeded", stats=result)
            click.echo(f"calibration-audit: {result}")
        except Exception as exc:
            jobs.finish_job(job, "failed", error=str(exc))
            _send_alert_email("calibration-audit", str(exc), None)
            raise
        return

    if not any([pending, company_number, rescore_all]):
        raise click.UsageError("pass --pending, --company <number>, or --rescore-all --rubric <version>")

    job = jobs.start_job("score", _iso_week())
    if job is None:
        click.echo("score: this week's run already succeeded, skipping.")
        return
    try:
        if company_number:
            numbers = [company_number]
        else:
            numbers = _pending_company_numbers(["enriched", "scored"])
        succeeded, failures = [], []
        for number in numbers:
            try:
                score_company(number, rubric_version)
                succeeded.append(number)
            except Exception as exc:  # noqa: BLE001 - one company must not abort the run
                failures.append({"company_number": number, "error": str(exc)})
        stats = {"succeeded": len(succeeded), "failures": failures}
        jobs.finish_job(job, "succeeded", stats=stats)
        click.echo(f"score: succeeded={len(succeeded)} failures={len(failures)}")
    except Exception as exc:
        jobs.finish_job(job, "failed", error=str(exc))
        _send_alert_email("score", str(exc), None)
        raise


@main.command("watchlist-check")
def watchlist_check_cmd() -> None:
    """Watchlist entry/fire/expire (spec 02 §5)."""
    job = jobs.start_job("watchlist-check", _iso_week())
    if job is None:
        click.echo("watchlist-check: this week's run already succeeded, skipping.")
        return
    try:
        result = watchlist_check()
        jobs.finish_job(job, "succeeded", stats=result)
        click.echo(f"watchlist-check: {result}")
    except Exception as exc:
        jobs.finish_job(job, "failed", error=str(exc))
        _send_alert_email("watchlist-check", str(exc), None)
        raise


@main.command()
def digest() -> None:
    """Weekly digest email (spec 02 §6)."""
    job = jobs.start_job("digest", _iso_week())
    if job is None:
        click.echo("digest: this week's run already succeeded, skipping.")
        return
    try:
        content = build_digest()
        result = send_digest(content)
        jobs.finish_job(job, "succeeded", stats={"content": content, "send_result": result})
        click.echo(f"digest: {result}")
    except Exception as exc:
        jobs.finish_job(job, "failed", error=str(exc))
        _send_alert_email("digest", str(exc), None)
        raise


@main.command("alert-failure")
@click.option("--job", "job_name", required=True)
@click.option("--run-url", default=None)
def alert_failure(job_name: str, run_url: str | None) -> None:
    """Invoked by GitHub Actions `if: failure()` steps — the workflow step
    that ran already failed, so this just reads the last failed jobs row for
    context and emails it. Never exits non-zero itself."""
    try:
        client = db.get_client()
        resp = (
            client.table("jobs")
            .select("*")
            .eq("job_name", job_name)
            .eq("status", "failed")
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        error = resp.data[0].get("error") if resp.data else "(no jobs row found — check the Actions log directly)"
    except Exception as exc:  # noqa: BLE001 - the alert path must not itself crash the workflow
        error = f"(could not read jobs table: {exc})"
    _send_alert_email(job_name, error or "unknown error", run_url)


if __name__ == "__main__":
    main()
