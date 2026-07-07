"""Supabase client + shared provenance/write helpers.

Every worker module should go through here for source_records writes so
provenance stays consistent (spec 00 §4 "Provenance everywhere").
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from cp_workers.config import settings


@lru_cache(maxsize=1)
def get_client() -> Client:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (see .env.example)"
        )
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def content_hash(payload: Any) -> str:
    """Stable hash of a JSON-serialisable payload, used for skip-unchanged checks."""
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def record_source(
    *,
    company_id: str | None,
    source: str,
    source_url: str | None,
    raw: Any,
) -> dict:
    """Insert a source_records row and return it. Always call this before parsing."""
    client = get_client()
    row = {
        "company_id": company_id,
        "source": source,
        "source_url": source_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "raw": raw,
        "content_hash": content_hash(raw),
    }
    resp = client.table("source_records").insert(row).execute()
    return resp.data[0]


def last_source_hash(*, company_id: str, source: str) -> str | None:
    """Most recent content_hash for (company_id, source) — used for skip-unchanged logic."""
    client = get_client()
    resp = (
        client.table("source_records")
        .select("content_hash")
        .eq("company_id", company_id)
        .eq("source", source)
        .order("fetched_at", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0]["content_hash"] if resp.data else None


def upsert_company(company_number: str, fields: dict) -> dict:
    """Upsert companies by natural key company_number. Never overwrites with None."""
    client = get_client()
    clean = {k: v for k, v in fields.items() if v is not None}
    clean["company_number"] = company_number
    resp = (
        client.table("companies")
        .upsert(clean, on_conflict="company_number")
        .execute()
    )
    return resp.data[0]


def get_company_by_number(company_number: str) -> dict | None:
    client = get_client()
    resp = (
        client.table("companies")
        .select("*")
        .eq("company_number", company_number)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_config(key: str, default: Any = None) -> Any:
    client = get_client()
    resp = client.table("app_config").select("value").eq("key", key).limit(1).execute()
    return resp.data[0]["value"] if resp.data else default
