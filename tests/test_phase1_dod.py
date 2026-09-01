"""Phase 1 Definition of Done.

(a) duplicate webhook delivery -> only one action fires
(b) an out-of-policy stub proposal -> executor never fires, rejection is logged
"""
import pytest

from app import agents, cases, executor, pipeline
from app.models import (
    ActionType,
    CaseReason,
    CaseState,
    Cohort,
    InterventionProposal,
    PolicyDecision,
    RecoveryCase,
    WorkflowType,
)

PAYMENT_FAILED_EVENT = {
    "event_id": "evt_dupe_1",
    "event_type": "payment.failed",
    "payload": {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_x1", "amount": 50000, "email": "a@b.com",
            "contact": "+919820098200", "customer_id": "cust_dod",
        }}},
    },
}


# ---------------------------------------------------------------- DoD (a)
async def test_duplicate_webhook_event_fires_action_once(mem_db, fake_gateway):
    await mem_db.insert("webhook_event", dict(PAYMENT_FAILED_EVENT, signature_verified=True))

    c1 = await pipeline.process_webhook_event("evt_dupe_1")
    c2 = await pipeline.process_webhook_event("evt_dupe_1")   # redelivery

    assert c1.case_id == c2.case_id                            # same case, not a second
    assert fake_gateway.call_count == 1                        # exactly one payment link
    executed = await mem_db.select(
        "action_log", params={"event": "eq.action_executed"}
    )
    assert len(executed) == 1
    assert c2.state == CaseState.SUCCEEDED


async def test_executor_idempotency_key_blocks_second_fire(mem_db, fake_gateway):
    case = RecoveryCase(
        case_id="case-1", workflow_type=WorkflowType.retry_router,
        customer_id="cust_1", amount_at_risk=30000,
        reason=CaseReason.gateway_error, cohort=Cohort.treatment,
        state=CaseState.EXECUTING,
    )
    decision = PolicyDecision(
        approved=True, policy_version="v1",
        resolved_action=ActionType.create_payment_link, resolved_amount=30000,
        allowed_actions=[ActionType.create_payment_link],
    )
    r1 = await executor.execute(case, decision, gateway=fake_gateway)
    r2 = await executor.execute(case, decision, gateway=fake_gateway)

    assert r1.reused is False and r2.reused is True
    assert fake_gateway.call_count == 1


# ---------------------------------------------------------------- DoD (b)
async def test_out_of_policy_proposal_never_reaches_executor(mem_db, fake_gateway, monkeypatch):
    # stub brain returns an action NOT on retry_router's allowlist
    async def rogue_proposal(case):
        return InterventionProposal(
            reason=CaseReason.gateway_error,
            recommended_action=ActionType.send_whatsapp_nudge,  # not allowed for retry_router
            rationale="[test] deliberately out of policy",
        )

    monkeypatch.setattr(agents, "propose_intervention", rogue_proposal)
    await mem_db.insert("webhook_event", dict(
        PAYMENT_FAILED_EVENT, event_id="evt_oop", signature_verified=True))
    PAYMENT_FAILED_EVENT_OOP = await mem_db.select(
        "webhook_event", params={"event_id": "eq.evt_oop"})
    PAYMENT_FAILED_EVENT_OOP[0]["event_id"] = "evt_oop"

    case = await pipeline.process_webhook_event("evt_oop")

    assert case.state == CaseState.SUPPRESSED
    assert case.outcome == "suppressed"
    assert fake_gateway.call_count == 0                        # executor never fired

    log = await mem_db.select("action_log", params={"case_id": f"eq.{case.case_id}"})
    events = [r["event"] for r in log]
    assert "policy_decision" in events
    decision_row = next(r for r in log if r["event"] == "policy_decision")
    assert decision_row["detail"]["approved"] is False
    assert "not in allowlist" in decision_row["detail"]["suppressed_reason"]
    assert any(r["event"] == "state_transition" and r["to_state"] == "SUPPRESSED" for r in log)
    assert not any(r["event"] == "action_executed" for r in log)


async def test_amount_over_ceiling_escalates_not_pays(mem_db, fake_gateway):
    big = dict(PAYMENT_FAILED_EVENT, event_id="evt_big")
    big["payload"] = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": "pay_big", "amount": 5_000_000, "email": "big@b.com",
            "contact": "+919820098200", "customer_id": "cust_big",
        }}},
    }
    await mem_db.insert("webhook_event", dict(big, signature_verified=True))
    case = await pipeline.process_webhook_event("evt_big")

    assert case.state == CaseState.SUCCEEDED
    assert fake_gateway.call_count == 0
    log = await mem_db.select("action_log", params={"case_id": f"eq.{case.case_id}"})
    executed = next(r for r in log if r["event"] == "action_executed")
    assert executed["detail"]["action"] == "escalate_to_human"
