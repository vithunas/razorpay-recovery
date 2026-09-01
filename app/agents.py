"""Workflow agents.

PHASE 1: the brain is STUBBED. `propose_intervention` returns a fixed,
schema-valid InterventionProposal with no LLM involved — just enough to drive
the deterministic pipeline (event -> case -> policy -> executor -> audit).

PHASE 2 swaps the body of `propose_intervention` for a real PydanticAI Agent
(GoogleModel / Gemini) behind this EXACT signature. Nothing downstream changes:
policy.py still clamps, executor.py still decides idempotency, the LLM output is
still just a proposal.
"""
from __future__ import annotations

from app.models import (
    ActionType,
    CaseReason,
    InterventionProposal,
    RecoveryCase,
    WorkflowType,
)

# default action per workflow for the stub
_STUB_ACTION = {
    WorkflowType.mandate_whisperer: ActionType.create_payment_link,
    WorkflowType.retry_router: ActionType.create_payment_link,
    WorkflowType.collections_copilot: ActionType.create_partial_payment_link,
}


async def propose_intervention(case: RecoveryCase) -> InterventionProposal:
    """STUB. Deterministic, schema-valid, no LLM. Replaced in Phase 2."""
    action = _STUB_ACTION.get(case.workflow_type, ActionType.create_payment_link)
    return InterventionProposal(
        reason=case.reason if case.reason != CaseReason.unknown else CaseReason.gateway_error,
        recommended_action=action,
        suggested_amount=None,  # let policy resolve from amount_at_risk
        message_template=(
            "Hi, your payment of {amount} to {merchant} didn't go through. "
            "You can complete it here: {link}"
        ),
        rationale="[stubbed brain] fixed proposal for Phase 1 pipeline proving",
        confidence=1.0,
    )
