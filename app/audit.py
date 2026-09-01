"""Append-only audit trail.

Every meaningful step in a case's life writes one row here and never mutates
it. This is the record the Phase 7 dashboard renders as the case timeline and
the trust signal ("policy blocked N actions").
"""
from __future__ import annotations

from typing import Any

from app import db
from app.models import CaseState


async def record(
    *,
    case_id: str | None,
    actor: str,
    event: str,
    customer_id: str | None = None,
    from_state: CaseState | str | None = None,
    to_state: CaseState | str | None = None,
    idempotency_key: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    row = {
        "case_id": case_id,
        "customer_id": customer_id,
        "actor": actor,
        "event": event,
        "from_state": from_state.value if isinstance(from_state, CaseState) else from_state,
        "to_state": to_state.value if isinstance(to_state, CaseState) else to_state,
        "idempotency_key": idempotency_key,
        "detail": detail or {},
    }
    await db.insert("action_log", row)


async def entries_for_case(case_id: str) -> list[dict[str, Any]]:
    return await db.select(
        "action_log",
        params={"case_id": f"eq.{case_id}", "order": "created_at.asc"},
    )
