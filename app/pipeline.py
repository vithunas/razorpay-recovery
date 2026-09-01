"""Orchestrator: webhook event -> RecoveryCase -> proposal -> policy -> executor -> audit.

This is the deterministic spine. The only non-deterministic step is
`agents.propose_intervention` (stubbed in Phase 1, Gemini in Phase 2), and its
output is just a proposal — policy.evaluate() decides, executor.execute() acts.
"""
from __future__ import annotations

from typing import Any

from app import agents, audit, cases, db, executor, policy
from app.models import (
    CaseReason,
    CaseState,
    InterventionProposal,
    RecoveryCase,
    WorkflowType,
)

# webhook event -> (workflow, default reason). Subscription events wired here
# for Phase 2; payment.failed / invoice.* usable now.
ROUTING: dict[str, tuple[WorkflowType, CaseReason]] = {
    "payment.failed": (WorkflowType.retry_router, CaseReason.gateway_error),
    "subscription.halted": (WorkflowType.mandate_whisperer, CaseReason.insufficient_funds),
    "subscription.pending": (WorkflowType.mandate_whisperer, CaseReason.insufficient_funds),
    "invoice.expired": (WorkflowType.collections_copilot, CaseReason.invoice_overdue),
    "payment_link.expired": (WorkflowType.collections_copilot, CaseReason.invoice_overdue),
}


async def process_webhook_event(event_id: str) -> RecoveryCase | None:
    rows = await db.select("webhook_event", params={"event_id": f"eq.{event_id}", "limit": "1"})
    if not rows:
        return None
    ev = rows[0]
    event_type = ev.get("event_type")
    if event_type not in ROUTING:
        await db.update("webhook_event", {"processed": True},
                        params={"event_id": f"eq.{event_id}"})
        return None

    workflow, reason = ROUTING[event_type]
    case = _build_case(ev, workflow, reason)
    case = await cases.create_case(case)

    await db.update("webhook_event", {"processed": True},
                    params={"event_id": f"eq.{event_id}"})

    if case.state == CaseState.DETECTED:
        await run_case(case)
    return case


async def run_case(case: RecoveryCase) -> RecoveryCase:
    """Walk a freshly-DETECTED case through the state machine once."""
    # DETECTED -> ASSESSED : ask the brain (stub/LLM) for a proposal
    proposal = await agents.propose_intervention(case)
    await _persist_proposal(case, proposal)
    await cases.transition(case, CaseState.ASSESSED,
                           detail={"proposal": proposal.model_dump(mode="json")})

    # eligibility gate (deterministic)
    if case.amount_at_risk <= 0:
        await cases.transition(case, CaseState.STOP, detail={"why": "nothing at risk"})
        await cases.set_outcome(case, "not_eligible")
        return case
    await cases.transition(case, CaseState.ELIGIBLE)
    await cases.transition(case, CaseState.INTERVENTION_SELECTED,
                           detail={"action": proposal.recommended_action.value})
    await cases.transition(case, CaseState.POLICY_CHECK)

    # POLICY_CHECK -> APPROVED | SUPPRESSED  (CODE DECIDES)
    cfg = policy.load_policy()
    contacts = await cases.contacts_in_window(
        case.customer_id, cfg["contact_budget"]["window_hours"]
    )
    decision = policy.evaluate(case, proposal, contacts_in_window=contacts)
    case.allowed_actions = decision.allowed_actions
    await _persist_decision(case, decision)
    await audit.record(
        case_id=case.case_id, customer_id=case.customer_id, actor="policy",
        event="policy_decision",
        detail=decision.model_dump(mode="json"),
    )

    if not decision.approved:
        await cases.transition(case, CaseState.SUPPRESSED,
                               actor="policy",
                               detail={"suppressed_reason": decision.suppressed_reason})
        await cases.set_outcome(case, "suppressed")
        return case

    await cases.transition(case, CaseState.APPROVED, actor="policy",
                           detail={"resolved_action": decision.resolved_action.value,
                                   "resolved_amount": decision.resolved_amount})

    # APPROVED -> EXECUTING -> SUCCEEDED | FAILED  (CODE EXECUTES)
    await cases.transition(case, CaseState.EXECUTING)
    result = await executor.execute(case, decision)

    if result.ok:
        await cases.transition(case, CaseState.SUCCEEDED, actor="executor",
                               detail={"reused": result.reused, **result.detail})
        await cases.set_outcome(case, "action_taken" if not result.reused else "action_reused")
    else:
        await cases.transition(case, CaseState.FAILED, actor="executor",
                               detail={"error": result.error})
        await cases.set_outcome(case, "execution_failed")
    return case


# --------------------------------------------------------------------------
def _build_case(ev: dict[str, Any], workflow: WorkflowType, reason: CaseReason) -> RecoveryCase:
    payload = ev.get("payload") or {}
    inner = payload.get("payload") or {}
    entity = (
        (inner.get("payment") or {}).get("entity")
        or (inner.get("subscription") or {}).get("entity")
        or (inner.get("invoice") or {}).get("entity")
        or (inner.get("payment_link") or {}).get("entity")
        or {}
    )
    amount = int(entity.get("amount") or entity.get("amount_due") or 0)
    customer = {
        "name": entity.get("customer_details", {}).get("name") if isinstance(entity.get("customer_details"), dict) else None,
        "email": entity.get("email"),
        "contact": entity.get("contact"),
    }
    customer_id = entity.get("customer_id") or entity.get("email") or ev.get("event_id")

    return RecoveryCase(
        workflow_type=workflow,
        customer_id=customer_id,
        merchant_id=entity.get("notes", {}).get("merchant_id") if isinstance(entity.get("notes"), dict) else None,
        amount_at_risk=amount,
        reason=reason,
        evidence={"webhook_event_id": ev.get("event_id"), "event_type": ev.get("event_type"),
                  "entity_id": entity.get("id"), "customer": {k: v for k, v in customer.items() if v}},
        cohort=cases.assign_cohort(customer_id),
        state=CaseState.DETECTED,
        source_event_id=ev.get("event_id"),
    )


async def _persist_proposal(case: RecoveryCase, proposal: InterventionProposal) -> None:
    if case.case_id:
        await db.update("recovery_case",
                        {"last_proposal": proposal.model_dump(mode="json")},
                        params={"case_id": f"eq.{case.case_id}"})


async def _persist_decision(case: RecoveryCase, decision) -> None:
    if case.case_id:
        await db.update("recovery_case",
                        {"last_decision": decision.model_dump(mode="json"),
                         "policy_version": decision.policy_version,
                         "allowed_actions": [a.value for a in decision.allowed_actions]},
                        params={"case_id": f"eq.{case.case_id}"})
