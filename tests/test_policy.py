import pytest

from app.models import (
    ActionType,
    CaseReason,
    Cohort,
    InterventionProposal,
    RecoveryCase,
    WorkflowType,
)
from app.policy import clamp_amount, evaluate, load_policy, resolve_allowed_actions


def make_case(**kw) -> RecoveryCase:
    base = dict(
        workflow_type=WorkflowType.retry_router,
        cohort=Cohort.treatment,
        amount_at_risk=50000,
        reason=CaseReason.gateway_error,
    )
    base.update(kw)
    return RecoveryCase(**base)


def make_proposal(**kw) -> InterventionProposal:
    base = dict(
        reason=CaseReason.gateway_error,
        recommended_action=ActionType.create_payment_link,
        suggested_amount=None,
    )
    base.update(kw)
    return InterventionProposal(**base)


def test_policy_version_matches_filename():
    assert load_policy("v1")["version"] == "v1"


def test_allowlist_resolved_from_config_not_llm():
    allowed = resolve_allowed_actions(WorkflowType.retry_router)
    assert ActionType.create_payment_link in allowed
    assert ActionType.send_whatsapp_nudge not in allowed  # not allowed for retry_router


def test_action_off_allowlist_is_suppressed():
    case = make_case()
    proposal = make_proposal(recommended_action=ActionType.send_whatsapp_nudge)
    decision = evaluate(case, proposal)
    assert decision.approved is False
    assert "not in allowlist" in decision.suppressed_reason


def test_amount_resolved_from_ground_truth_not_llm_inflation():
    case = make_case(amount_at_risk=50000)
    proposal = make_proposal(suggested_amount=9_99_99_999)  # LLM tries to inflate
    decision = evaluate(case, proposal)
    assert decision.approved is True
    assert decision.resolved_amount == 50000
    assert any("ignored LLM suggested_amount" in c for c in decision.clamps_applied)


def test_llm_may_only_reduce_amount_for_partial():
    case = make_case(amount_at_risk=50000)
    proposal = make_proposal(suggested_amount=20000)
    decision = evaluate(case, proposal)
    assert decision.resolved_amount == 20000


def test_amount_clamped_to_config_max():
    amount, clamps = clamp_amount(9_99_99_999)
    assert amount == load_policy("v1")["payment_link"]["max_amount"]
    assert clamps


def test_amount_above_workflow_ceiling_escalates():
    case = make_case(workflow_type=WorkflowType.retry_router, amount_at_risk=2_000_000)
    decision = evaluate(case, make_proposal())
    assert decision.approved is True
    assert decision.resolved_action == ActionType.escalate_to_human
    assert decision.resolved_amount == 0


def test_contact_budget_exhausted_suppresses():
    case = make_case()
    decision = evaluate(case, make_proposal(), contacts_in_window=1)
    assert decision.approved is False
    assert "contact budget" in decision.suppressed_reason


def test_no_action_proposal_is_suppressed():
    decision = evaluate(make_case(), make_proposal(recommended_action=ActionType.no_action))
    assert decision.approved is False
