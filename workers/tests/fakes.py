"""A minimal in-memory fake of the subset of the Supabase/postgrest client
API this package uses (table().select/insert/update/upsert with
.eq/.gte/.in_/.order/.limit/.execute chains). Good enough to exercise
pipeline.py / watchlist.py / digest.py / calibration.py without a live
database, per the task instruction to mock the Anthropic client and avoid
any live network calls in tests -- this does the equivalent for Supabase.
"""
from __future__ import annotations

import uuid
from typing import Any, Callable


class FakeResponse:
    def __init__(self, data: list[dict]):
        self.data = data


class FakeQuery:
    def __init__(self, client: "FakeSupabaseClient", table_name: str, mode: str, payload: Any = None):
        self.client = client
        self.table_name = table_name
        self.mode = mode
        self.payload = payload
        self._filters: list[Callable[[dict], bool]] = []
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None

    # --- filter builders -------------------------------------------------
    def eq(self, col: str, val: Any) -> "FakeQuery":
        self._filters.append(lambda row: row.get(col) == val)
        return self

    def gte(self, col: str, val: Any) -> "FakeQuery":
        self._filters.append(lambda row: row.get(col) is not None and row.get(col) >= val)
        return self

    def in_(self, col: str, vals: list[Any]) -> "FakeQuery":
        vals = set(vals)
        self._filters.append(lambda row: row.get(col) in vals)
        return self

    def order(self, col: str, desc: bool = False) -> "FakeQuery":
        self._order = (col, desc)
        return self

    def limit(self, n: int) -> "FakeQuery":
        self._limit = n
        return self

    # --- execution ---------------------------------------------------------
    def _rows(self) -> list[dict]:
        return self.client.tables.setdefault(self.table_name, [])

    def _matching(self) -> list[dict]:
        rows = self._rows()
        result = [r for r in rows if all(f(r) for f in self._filters)]
        if self._order:
            col, desc = self._order
            result = sorted(result, key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
        if self._limit is not None:
            result = result[: self._limit]
        return result

    def execute(self) -> FakeResponse:
        rows = self._rows()
        if self.mode == "select":
            return FakeResponse(self._matching())

        if self.mode == "insert":
            payloads = self.payload if isinstance(self.payload, list) else [self.payload]
            inserted = []
            for p in payloads:
                row = dict(p)
                row.setdefault("id", str(uuid.uuid4()))
                row.setdefault("created_at", "2026-01-01T00:00:00+00:00")
                row.setdefault("updated_at", row["created_at"])
                rows.append(row)
                inserted.append(row)
            return FakeResponse(inserted)

        if self.mode == "update":
            matched = [r for r in rows if all(f(r) for f in self._filters)]
            for r in matched:
                r.update(self.payload)
            return FakeResponse(matched)

        if self.mode == "upsert":
            on_conflict_cols = list(self.payload.get("__on_conflict__", [])) if isinstance(self.payload, dict) else []
            payload = {k: v for k, v in self.payload.items() if k != "__on_conflict__"}
            match = None
            if on_conflict_cols:
                for r in rows:
                    if all(r.get(c) == payload.get(c) for c in on_conflict_cols):
                        match = r
                        break
            if match is not None:
                match.update(payload)
                return FakeResponse([match])
            row = dict(payload)
            row.setdefault("id", str(uuid.uuid4()))
            rows.append(row)
            return FakeResponse([row])

        raise ValueError(f"unsupported mode {self.mode!r}")


class FakeTable:
    def __init__(self, client: "FakeSupabaseClient", name: str):
        self.client = client
        self.name = name

    def select(self, *_args, **_kwargs) -> FakeQuery:
        return FakeQuery(self.client, self.name, "select")

    def insert(self, payload) -> FakeQuery:
        return FakeQuery(self.client, self.name, "insert", payload)

    def update(self, payload) -> FakeQuery:
        return FakeQuery(self.client, self.name, "update", payload)

    def upsert(self, payload, on_conflict: str | None = None) -> FakeQuery:
        merged = dict(payload)
        if on_conflict:
            merged["__on_conflict__"] = [c.strip() for c in on_conflict.split(",")]
        return FakeQuery(self.client, self.name, "upsert", merged)


class FakeSupabaseClient:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}

    def table(self, name: str) -> FakeTable:
        return FakeTable(self, name)

    def seed(self, name: str, rows: list[dict]) -> None:
        self.tables[name] = [dict(r) for r in rows]
