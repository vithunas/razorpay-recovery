"""In-memory stand-ins for Supabase and the Razorpay gateway, for tests that
exercise the pipeline without external services."""
from __future__ import annotations

import uuid
from typing import Any

from app.db import SupabaseError


class InMemoryDB:
    """Emulates the slice of PostgREST behaviour app/db.py relies on, including
    the unique constraints that back idempotency."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "webhook_event": [], "recovery_case": [], "action_log": [],
            "merchant": [], "customer": [],
        }

    # ---- constraints -----------------------------------------------------
    def _violates_unique(self, table: str, row: dict[str, Any]) -> str | None:
        rows = self.tables[table]
        if table == "webhook_event":
            if any(r["event_id"] == row.get("event_id") for r in rows):
                return "webhook_event.event_id"
        if table == "recovery_case" and row.get("source_event_id"):
            if any(r.get("workflow_type") == row.get("workflow_type")
                   and r.get("source_event_id") == row.get("source_event_id") for r in rows):
                return "recovery_case.workflow_source"
        if table == "action_log" and row.get("event") == "action_executed" and row.get("idempotency_key"):
            if any(r.get("event") == "action_executed"
                   and r.get("idempotency_key") == row.get("idempotency_key") for r in rows):
                return "action_log.executed_idem"
        return None

    # ---- API mirrored from app/db.py -----------------------------------
    async def insert(self, table: str, row: dict[str, Any], *, upsert: bool = False):
        row = dict(row)
        violated = self._violates_unique(table, row)
        if violated:
            if table == "action_log":
                raise SupabaseError(f"duplicate key {violated}")
            return None
        pk = "case_id" if table == "recovery_case" else "id"
        row.setdefault(pk, str(uuid.uuid4()))
        self.tables[table].append(row)
        return row

    async def update(self, table: str, patch: dict[str, Any], *, params: dict[str, str]):
        updated = []
        for r in self.tables[table]:
            if self._matches(r, params):
                r.update(patch)
                updated.append(r)
        return updated

    async def select(self, table: str, *, params: dict[str, str] | None = None):
        params = params or {}
        out = [r for r in self.tables[table] if self._matches(r, params)]
        if "order" in params:
            field = params["order"].split(".")[0]
            out.sort(key=lambda r: r.get(field) or "")
        if "limit" in params:
            out = out[: int(params["limit"])]
        return out

    async def health(self):
        return {"configured": True, "reachable": True, "status": 200}

    @staticmethod
    def _matches(row: dict[str, Any], params: dict[str, str]) -> bool:
        for k, v in params.items():
            if k in ("select", "order", "limit", "offset"):
                continue
            if not isinstance(v, str) or "." not in v:
                continue
            op, _, val = v.partition(".")
            cur = row.get(k)
            if op == "eq" and str(cur) != val:
                return False
            if op == "gte" and (cur is None or str(cur) < val):
                return False
            if op == "lte" and (cur is None or str(cur) > val):
                return False
        return True


class FakeGateway:
    """Records calls; never touches the network."""

    def __init__(self) -> None:
        self.payment_links: list[dict[str, Any]] = []

    async def create_payment_link(self, **kwargs: Any) -> dict[str, Any]:
        self.payment_links.append(kwargs)
        n = len(self.payment_links)
        return {
            "id": f"plink_fake_{n}",
            "short_url": f"https://rzp.io/i/fake{n}",
            "amount": kwargs["amount"],
            "status": "created",
            "reference_id": kwargs.get("reference_id"),
        }

    async def fetch_payment_link(self, plink_id: str) -> dict[str, Any]:
        return {"id": plink_id, "status": "created"}

    @property
    def call_count(self) -> int:
        return len(self.payment_links)
