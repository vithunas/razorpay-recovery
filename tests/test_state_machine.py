import pytest

from app.models import CaseState
from app.state_machine import (
    IllegalTransition,
    assert_transition,
    can_transition,
    is_terminal,
)

HAPPY_PATH = [
    CaseState.DETECTED, CaseState.ASSESSED, CaseState.ELIGIBLE,
    CaseState.INTERVENTION_SELECTED, CaseState.POLICY_CHECK,
    CaseState.APPROVED, CaseState.EXECUTING, CaseState.SUCCEEDED,
]


def test_happy_path_is_legal():
    for frm, to in zip(HAPPY_PATH, HAPPY_PATH[1:]):
        assert can_transition(frm, to)


def test_suppressed_is_terminal_and_distinct_from_failed():
    assert is_terminal(CaseState.SUPPRESSED)
    assert not can_transition(CaseState.SUPPRESSED, CaseState.EXECUTING)
    assert not can_transition(CaseState.SUPPRESSED, CaseState.FAILED)


def test_policy_check_forks_only_to_approved_or_suppressed():
    assert can_transition(CaseState.POLICY_CHECK, CaseState.APPROVED)
    assert can_transition(CaseState.POLICY_CHECK, CaseState.SUPPRESSED)
    assert not can_transition(CaseState.POLICY_CHECK, CaseState.EXECUTING)


def test_failed_can_retry_escalate_or_stop():
    assert can_transition(CaseState.FAILED, CaseState.RETRY)
    assert can_transition(CaseState.FAILED, CaseState.ESCALATE)
    assert can_transition(CaseState.FAILED, CaseState.STOP)
    assert can_transition(CaseState.RETRY, CaseState.EXECUTING)


def test_cannot_skip_policy_check():
    assert not can_transition(CaseState.INTERVENTION_SELECTED, CaseState.EXECUTING)
    with pytest.raises(IllegalTransition):
        assert_transition(CaseState.DETECTED, CaseState.EXECUTING)


def test_terminal_states_have_no_exits():
    for s in (CaseState.SUCCEEDED, CaseState.SUPPRESSED, CaseState.ESCALATE, CaseState.STOP):
        assert is_terminal(s)
