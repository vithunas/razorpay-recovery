"""RecoveryCase state machine.

    DETECTED -> ASSESSED -> ELIGIBLE -> INTERVENTION_SELECTED -> POLICY_CHECK
      -> APPROVED | SUPPRESSED
    APPROVED -> EXECUTING -> SUCCEEDED | FAILED
    FAILED -> RETRY | ESCALATE | STOP
    RETRY -> EXECUTING

SUPPRESSED is a clean terminal state — policy/budget blocked the action. It is
never conflated with FAILED (execution was attempted and errored).
"""
from __future__ import annotations

from app.models import CaseState, TERMINAL_STATES

ALLOWED_TRANSITIONS: dict[CaseState, set[CaseState]] = {
    CaseState.DETECTED: {CaseState.ASSESSED},
    CaseState.ASSESSED: {CaseState.ELIGIBLE, CaseState.STOP},
    CaseState.ELIGIBLE: {CaseState.INTERVENTION_SELECTED, CaseState.STOP},
    CaseState.INTERVENTION_SELECTED: {CaseState.POLICY_CHECK},
    CaseState.POLICY_CHECK: {CaseState.APPROVED, CaseState.SUPPRESSED},
    CaseState.APPROVED: {CaseState.EXECUTING},
    CaseState.EXECUTING: {CaseState.SUCCEEDED, CaseState.FAILED},
    CaseState.FAILED: {CaseState.RETRY, CaseState.ESCALATE, CaseState.STOP},
    CaseState.RETRY: {CaseState.EXECUTING},
    # terminal
    CaseState.SUCCEEDED: set(),
    CaseState.SUPPRESSED: set(),
    CaseState.ESCALATE: set(),
    CaseState.STOP: set(),
}


class IllegalTransition(RuntimeError):
    def __init__(self, frm: CaseState, to: CaseState) -> None:
        super().__init__(f"illegal case transition {frm.value} -> {to.value}")
        self.frm, self.to = frm, to


def can_transition(frm: CaseState, to: CaseState) -> bool:
    return to in ALLOWED_TRANSITIONS.get(frm, set())


def assert_transition(frm: CaseState, to: CaseState) -> None:
    if not can_transition(frm, to):
        raise IllegalTransition(frm, to)


def is_terminal(state: CaseState) -> bool:
    return state in TERMINAL_STATES
