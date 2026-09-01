import pytest

from app.executor import execute, idempotency_key, razorpay_reference_id
from app.models import (
    ActionType,
    CaseReason,
    Cohort,
    PolicyDecision,
    RecoveryCase,
    WorkflowType,
)
from tests.fakes import FakeGateway


def _case() -> RecoveryCase:
    return RecoveryCase(
        case_id="136c06df-ac6e-4f7b-915d-1b9c892469b0",
        workflow_type=WorkflowType.retry_router, customer_id="cust_1",
        amount_at_risk=42700, reason=CaseReason.gateway_error, cohort=Cohort.control,
    )


def test_razorpay_reference_id_within_40_chars():
    for action in ActionType:
        ref = razorpay_reference_id(_case(), action)
        assert len(ref) <= 40, (action, ref)


def test_idempotency_key_is_case_plus_action():
    assert idempotency_key(_case(), ActionType.create_payment_link) == (
        "136c06df-ac6e-4f7b-915d-1b9c892469b0:create_payment_link"
    )


async def test_execute_rejects_unapproved_decision():
    decision = PolicyDecision(approved=False, policy_version="v1",
                              resolved_action=ActionType.no_action)
    with pytest.raises(ValueError):
        await execute(_case(), decision, gateway=FakeGateway())


async def test_execute_escalation_makes_no_gateway_call(mem_db):
    gw = FakeGateway()
    decision = PolicyDecision(approved=True, policy_version="v1",
                              resolved_action=ActionType.escalate_to_human)
    res = await execute(_case(), decision, gateway=gw)
    assert res.ok and gw.call_count == 0
    assert res.detail.get("escalated") is True
