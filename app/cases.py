"""recovery_case persistence + state transitions.

State changes go through `transition()` so every move is validated against the
state machine and written to the audit log. Nothing here talks to Razorpay.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

from app import audit, db
from app.models import Cohort, RecoveryCase, CaseState, utcnow
from app.state_machine import assert_transition


def assign_cohort(customer_id: str | None) -> Cohort:
    """Deterministic 50/50 split, fixed at creation and never revisited."""
    seed = customer_id or "anonymous"
    digest = hashlib.sha256(seed.encode()).digest()
    return Cohort.treatment if digest[0] % 2 == 0 else Cohort.control


async def create_case(case: RecoveryCase) -> RecoveryCase:
    """Insert a case. If one already exists for (workflow_type, source_event_id)
    the DB unique index returns it instead of creating a duplicate."""
    row = case.model_dump(mode="json", exclude={"case_id"})
    inserted = await db.insert("recovery_case", row)
    if inserted is None:
        # duplicate source event -> return the existing case
        existing = await db.select(
            "recovery_case",
            params={
                "workflow_type": f"eq.{case.workflow_type.value}",
                "source_event_id": f"eq.{case.source_event_id}",
                "limit": "1",
            },
        )
        if existing:
            return RecoveryCase(**_from_row(existing[0]))
        return case
    case.case_id = inserted["case_id"]
    await audit.record(
        case_id=case.case_id, customer_id=case.customer_id, actor="pipeline",
        event="state_transition", to_state=CaseState.DETECTED,
        detail={"source_event_id": case.source_event_id,
                "workflow": case.workflow_type.value,
                "amount_at_risk": case.amount_at_risk,
                "cohort": case.cohort.value},
    )
    return case


async def get_case(case_id: str) -> RecoveryCase | None:
    rows = await db.select("recovery_case", params={"case_id": f"eq.{case_id}", "limit": "1"})
    return RecoveryCase(**_from_row(rows[0])) if rows else None


async def transition(
    case: RecoveryCase,
    to_state: CaseState,
    *,
    actor: str = "pipeline",
    detail: dict[str, Any] | None = None,
) -> RecoveryCase:
    assert_transition(case.state, to_state)
    frm = case.state
    case.state = to_state
    if case.case_id:
        await db.update("recovery_case", {"state": to_state.value},
                        params={"case_id": f"eq.{case.case_id}"})
    await audit.record(
        case_id=case.case_id, customer_id=case.customer_id, actor=actor,
        event="state_transition", from_state=frm, to_state=to_state,
        detail=detail or {},
    )
    return case


async def set_outcome(case: RecoveryCase, outcome: str) -> None:
    case.outcome = outcome
    if case.case_id:
        await db.update("recovery_case", {"outcome": outcome},
                        params={"case_id": f"eq.{case.case_id}"})


async def contacts_in_window(customer_id: str | None, window_hours: int) -> int:
    """How many customer-facing actions have already fired for this customer
    inside the window — feeds the shared contact budget in policy.evaluate()."""
    if not customer_id:
        return 0
    since = (utcnow() - timedelta(hours=window_hours)).isoformat()
    rows = await db.select(
        "action_log",
        params={
            "customer_id": f"eq.{customer_id}",
            "event": "eq.action_executed",
            "created_at": f"gte.{since}",
            "select": "id,detail",
        },
    )
    contacting = {"send_whatsapp_nudge", "create_payment_link", "create_partial_payment_link"}
    return sum(1 for r in rows if (r.get("detail") or {}).get("action") in contacting)


def _from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": row.get("case_id"),
        "workflow_type": row["workflow_type"],
        "customer_id": row.get("customer_id"),
        "merchant_id": row.get("merchant_id"),
        "amount_at_risk": row.get("amount_at_risk", 0),
        "reason": row.get("reason", "unknown"),
        "evidence": row.get("evidence") or {},
        "cohort": row["cohort"],
        "allowed_actions": row.get("allowed_actions") or [],
        "attempted_actions": row.get("attempted_actions") or [],
        "state": row.get("state", "DETECTED"),
        "outcome": row.get("outcome"),
        "source_event_id": row.get("source_event_id"),
    }
