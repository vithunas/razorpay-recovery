"""Action executor — the ONLY module allowed to call money-adjacent APIs
(Razorpay-mutating endpoints, and Twilio send in Phase 2).

Guarantees:
  * runs only on a policy decision with approved=True
  * idempotent: an action already executed for (case_id, action) is never
    re-fired — the prior result is returned with reused=True
  * every attempt is appended to recovery_case.attempted_actions and written
    to the append-only audit log
"""
from __future__ import annotations

from typing import Any

from app import audit, db, razorpay_client
from app.models import (
    ActionType,
    ExecutionResult,
    PolicyDecision,
    RecoveryCase,
    utcnow,
)
from app.razorpay_client import RazorpayGateway


def idempotency_key(case: RecoveryCase, action: ActionType) -> str:
    return f"{case.case_id}:{action.value}"


async def _already_executed(key: str) -> dict[str, Any] | None:
    rows = await db.select(
        "action_log",
        params={"idempotency_key": f"eq.{key}", "event": "eq.action_executed"},
    )
    return rows[0] if rows else None


async def execute(
    case: RecoveryCase,
    decision: PolicyDecision,
    *,
    gateway: RazorpayGateway | None = None,
) -> ExecutionResult:
    if not decision.approved:
        raise ValueError("executor called with a non-approved decision")

    action = decision.resolved_action
    key = idempotency_key(case, action)

    prior = await _already_executed(key)
    if prior is not None:
        return ExecutionResult(
            ok=True, action=action, idempotency_key=key, reused=True,
            detail=prior.get("detail", {}),
        )

    gw = gateway or razorpay_client.get_gateway()

    try:
        detail = await _dispatch(case, decision, gw)
    except Exception as exc:  # noqa: BLE001 - executor must never crash the pipeline
        await audit.record(
            case_id=case.case_id, customer_id=case.customer_id,
            actor="executor", event="error", idempotency_key=key,
            detail={"action": action.value, "error": repr(exc)},
        )
        return ExecutionResult(ok=False, action=action, idempotency_key=key,
                               error=repr(exc))

    attempt = {"action": action.value, "at": utcnow().isoformat(),
               "idempotency_key": key, "detail": detail}
    case.attempted_actions.append(attempt)
    if case.case_id:
        await db.update(
            "recovery_case",
            {"attempted_actions": case.attempted_actions},
            params={"case_id": f"eq.{case.case_id}"},
        )

    try:
        await audit.record(
            case_id=case.case_id, customer_id=case.customer_id,
            actor="executor", event="action_executed", idempotency_key=key,
            detail={"action": action.value, "amount": decision.resolved_amount, **detail},
        )
    except db.SupabaseError:
        # unique index on (idempotency_key) where event='action_executed' -> a
        # concurrent duplicate beat us. Treat as reuse, not a new fire.
        prior = await _already_executed(key)
        return ExecutionResult(ok=True, action=action, idempotency_key=key,
                               reused=True, detail=(prior or {}).get("detail", {}))

    return ExecutionResult(ok=True, action=action, idempotency_key=key, detail=detail)


async def _dispatch(
    case: RecoveryCase, decision: PolicyDecision, gw: RazorpayGateway
) -> dict[str, Any]:
    action = decision.resolved_action

    if action in (ActionType.create_payment_link, ActionType.create_partial_payment_link):
        link = await gw.create_payment_link(
            amount=decision.resolved_amount,
            description=f"Recovery for case {case.case_id} ({case.workflow_type.value})",
            reference_id=idempotency_key(case, action),
            customer=_customer_block(case),
            accept_partial=(action == ActionType.create_partial_payment_link),
        )
        return {
            "payment_link_id": link.get("id"),
            "short_url": link.get("short_url"),
            "amount": link.get("amount"),
            "status": link.get("status"),
        }

    if action == ActionType.escalate_to_human:
        return {"escalated": True, "note": "queued for manual review"}

    if action == ActionType.retry_charge:
        # subscription retry lands in Phase 2 (needs the Subscriptions API)
        return {"retry_charge": "not_implemented_phase1"}

    if action == ActionType.send_whatsapp_nudge:
        # Twilio send lands in Phase 2
        return {"whatsapp": "not_implemented_phase1"}

    raise ValueError(f"executor cannot dispatch action {action.value}")


def _customer_block(case: RecoveryCase) -> dict[str, str] | None:
    ev = case.evidence or {}
    cust = ev.get("customer") or {}
    out = {}
    if cust.get("name"):
        out["name"] = cust["name"]
    if cust.get("email"):
        out["email"] = cust["email"]
    if cust.get("contact"):
        out["contact"] = cust["contact"]
    return out or None
