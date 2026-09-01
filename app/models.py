"""Shared schemas + closed enums.

Money is always integer paise. Enums are closed — `reason` and `action` are
never free text (architectural law: the LLM proposes within these bounds, it
does not invent new values).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# closed enums
# ---------------------------------------------------------------------------
class WorkflowType(str, Enum):
    mandate_whisperer = "mandate_whisperer"
    retry_router = "retry_router"
    collections_copilot = "collections_copilot"


class Cohort(str, Enum):
    treatment = "treatment"
    control = "control"


class CaseState(str, Enum):
    DETECTED = "DETECTED"
    ASSESSED = "ASSESSED"
    ELIGIBLE = "ELIGIBLE"
    INTERVENTION_SELECTED = "INTERVENTION_SELECTED"
    POLICY_CHECK = "POLICY_CHECK"
    APPROVED = "APPROVED"
    SUPPRESSED = "SUPPRESSED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    RETRY = "RETRY"
    ESCALATE = "ESCALATE"
    STOP = "STOP"


class CaseReason(str, Enum):
    # subscription / mandate
    insufficient_funds = "insufficient_funds"
    card_expired = "card_expired"
    mandate_revoked = "mandate_revoked"
    bank_declined = "bank_declined"
    authentication_failed = "authentication_failed"
    technical_decline = "technical_decline"
    # checkout retry
    gateway_error = "gateway_error"
    bank_downtime = "bank_downtime"
    card_declined = "card_declined"
    # collections
    invoice_overdue = "invoice_overdue"
    partial_payment_pending = "partial_payment_pending"
    # fallback
    unknown = "unknown"


class ActionType(str, Enum):
    send_whatsapp_nudge = "send_whatsapp_nudge"        # Phase 2
    create_payment_link = "create_payment_link"
    create_partial_payment_link = "create_partial_payment_link"
    retry_charge = "retry_charge"
    escalate_to_human = "escalate_to_human"
    no_action = "no_action"


TERMINAL_STATES: set[CaseState] = {
    CaseState.SUCCEEDED,
    CaseState.SUPPRESSED,
    CaseState.ESCALATE,
    CaseState.STOP,
}


# ---------------------------------------------------------------------------
# intervention proposal — the schema the stubbed brain (Phase 1) and the real
# PydanticAI agent (Phase 2) must both produce.  `action` is Literal-constrained.
# ---------------------------------------------------------------------------
class InterventionProposal(BaseModel):
    reason: CaseReason
    recommended_action: ActionType
    # the LLM *suggests* an amount; policy.py clamps / overrides it. May be None.
    suggested_amount: int | None = Field(default=None, ge=0)
    message_template: str = ""
    rationale: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# policy decision — produced only by policy.py, never by the LLM
# ---------------------------------------------------------------------------
class PolicyDecision(BaseModel):
    approved: bool
    policy_version: str
    resolved_action: ActionType
    resolved_amount: int = 0
    allowed_actions: list[ActionType] = Field(default_factory=list)
    suppressed_reason: str | None = None      # set iff approved is False
    clamps_applied: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# recovery case (mirror of the recovery_case table)
# ---------------------------------------------------------------------------
class RecoveryCase(BaseModel):
    case_id: str | None = None
    workflow_type: WorkflowType
    customer_id: str | None = None
    merchant_id: str | None = None
    amount_at_risk: int = 0
    reason: CaseReason = CaseReason.unknown
    evidence: dict[str, Any] = Field(default_factory=dict)
    cohort: Cohort
    allowed_actions: list[ActionType] = Field(default_factory=list)
    attempted_actions: list[dict[str, Any]] = Field(default_factory=list)
    state: CaseState = CaseState.DETECTED
    outcome: str | None = None
    source_event_id: str | None = None


class ExecutionResult(BaseModel):
    ok: bool
    action: ActionType
    idempotency_key: str
    reused: bool = False            # True -> a prior identical action was found, nothing re-fired
    detail: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
