"""Deterministic policy engine.

AI PROPOSES -> **CODE DECIDES** -> CODE EXECUTES.

`evaluate()` takes a case + an InterventionProposal (from the stub brain in
Phase 1, a real agent in Phase 2) and returns a PolicyDecision. The proposal
is advisory only:

  * the action must be on the workflow's allowlist, else SUPPRESSED
  * the amount is recomputed from ground truth and clamped to config bounds —
    the LLM's `suggested_amount` is never trusted as-is
  * the shared contact budget can SUPPRESS even a valid action
  * cases above the workflow's max_amount_at_risk escalate, not auto-act

Limits come from a versioned TOML file, never inline magic numbers.
"""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.models import (
    ActionType,
    InterventionProposal,
    PolicyDecision,
    RecoveryCase,
    WorkflowType,
)

POLICY_DIR = Path(__file__).resolve().parent.parent / "policy"
DEFAULT_VERSION = "v1"

# actions that count against the shared contact budget
CONTACTING_ACTIONS = {ActionType.send_whatsapp_nudge, ActionType.create_payment_link,
                      ActionType.create_partial_payment_link}


@lru_cache(maxsize=8)
def load_policy(version: str = DEFAULT_VERSION) -> dict[str, Any]:
    path = POLICY_DIR / f"policy_config.{version}.toml"
    if not path.exists():
        raise FileNotFoundError(f"policy config not found: {path}")
    with path.open("rb") as fh:
        cfg = tomllib.load(fh)
    if cfg.get("version") != version:
        raise ValueError(f"{path.name} declares version {cfg.get('version')!r}, expected {version!r}")
    return cfg


def resolve_allowed_actions(workflow: WorkflowType, version: str = DEFAULT_VERSION) -> list[ActionType]:
    cfg = load_policy(version)
    wf = cfg["workflows"][workflow.value]
    return [ActionType(a) for a in wf["allowed_actions"]]


def clamp_amount(raw: int, version: str = DEFAULT_VERSION) -> tuple[int, list[str]]:
    cfg = load_policy(version)["payment_link"]
    clamps: list[str] = []
    amount = int(raw)
    if amount < cfg["min_amount"]:
        clamps.append(f"amount raised to min {cfg['min_amount']}")
        amount = cfg["min_amount"]
    if amount > cfg["max_amount"]:
        clamps.append(f"amount lowered to max {cfg['max_amount']}")
        amount = cfg["max_amount"]
    return amount, clamps


def evaluate(
    case: RecoveryCase,
    proposal: InterventionProposal,
    *,
    contacts_in_window: int = 0,
    version: str = DEFAULT_VERSION,
) -> PolicyDecision:
    cfg = load_policy(version)
    wf = cfg["workflows"][case.workflow_type.value]
    allowed = resolve_allowed_actions(case.workflow_type, version)
    clamps: list[str] = []

    def suppressed(reason: str, action: ActionType = ActionType.no_action) -> PolicyDecision:
        return PolicyDecision(
            approved=False, policy_version=version, resolved_action=action,
            resolved_amount=0, allowed_actions=allowed, suppressed_reason=reason,
            clamps_applied=clamps,
        )

    if not wf.get("enabled", False):
        return suppressed(f"workflow {case.workflow_type.value} disabled in policy {version}")

    action = proposal.recommended_action

    # 1. allowlist — the LLM cannot pick an action outside policy
    if action not in allowed:
        return suppressed(
            f"action {action.value} not in allowlist for {case.workflow_type.value}",
        )

    if action == ActionType.no_action:
        return suppressed("proposal recommended no_action", ActionType.no_action)

    # 2. amount-at-risk ceiling -> escalate rather than auto-act
    if case.amount_at_risk > wf["max_amount_at_risk"]:
        if ActionType.escalate_to_human in allowed:
            return PolicyDecision(
                approved=True, policy_version=version,
                resolved_action=ActionType.escalate_to_human, resolved_amount=0,
                allowed_actions=allowed,
                clamps_applied=[f"amount_at_risk {case.amount_at_risk} > "
                                f"{wf['max_amount_at_risk']} -> escalate"],
            )
        return suppressed(
            f"amount_at_risk {case.amount_at_risk} exceeds "
            f"{wf['max_amount_at_risk']} and no escalation path",
        )

    # 3. shared contact budget
    if action in CONTACTING_ACTIONS:
        budget = cfg["contact_budget"]["max_contacts_per_window"]
        if contacts_in_window >= budget:
            return suppressed(
                f"contact budget exhausted ({contacts_in_window}/{budget} in "
                f"{cfg['contact_budget']['window_hours']}h window)",
            )

    # 4. resolve amount from GROUND TRUTH (amount_at_risk), not the LLM's number.
    #    suggested_amount may only *reduce* the ask (e.g. propose a partial), never raise it.
    resolved = case.amount_at_risk
    if proposal.suggested_amount is not None and proposal.suggested_amount < resolved:
        resolved = proposal.suggested_amount
        clamps.append(f"amount reduced to proposed {resolved} (partial)")
    elif proposal.suggested_amount is not None and proposal.suggested_amount > resolved:
        clamps.append(
            f"ignored LLM suggested_amount {proposal.suggested_amount} > amount_at_risk {resolved}"
        )

    if action in (ActionType.create_payment_link, ActionType.create_partial_payment_link):
        resolved, more = clamp_amount(resolved, version)
        clamps.extend(more)

    return PolicyDecision(
        approved=True, policy_version=version, resolved_action=action,
        resolved_amount=resolved, allowed_actions=allowed, clamps_applied=clamps,
    )
