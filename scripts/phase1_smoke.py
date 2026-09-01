"""Phase 1 live smoke test.

Signs a synthetic `payment.failed` webhook with the real webhook secret, POSTs
it to a running local server twice (to prove idempotency), then reads back the
RecoveryCase and its audit-log timeline from Supabase.

    python scripts/phase1_smoke.py            # assumes server on :8000
    python scripts/phase1_smoke.py --port 8000

Requires migration 002 applied. Creates a REAL Razorpay Test Mode payment link.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx

sys.path.insert(0, ".")
from app.config import settings  # noqa: E402
from app.security import compute_signature  # noqa: E402


def build_event() -> tuple[bytes, dict]:
    event_id = f"evt_smoke_{int(time.time())}"
    body = {
        "entity": "event",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {"payment": {"entity": {
            "id": f"pay_smoke_{int(time.time())}",
            "amount": 42700,
            "currency": "INR",
            "status": "failed",
            "email": "smoke@example.com",
            "contact": "+919820098200",
            "customer_id": "cust_smoke_phase1",
            "error_reason": "payment_failed",
        }}},
        "created_at": int(time.time()),
    }
    raw = json.dumps(body, separators=(",", ":")).encode()
    return raw, {"event_id": event_id}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    raw, meta = build_event()
    sig = compute_signature(raw, settings.razorpay_webhook_secret)
    headers = {
        "Content-Type": "application/json",
        "X-Razorpay-Event-Id": meta["event_id"],
        "X-Razorpay-Signature": sig,
    }

    async with httpx.AsyncClient(timeout=20) as c:
        r1 = await c.post(f"{base}/webhook/razorpay", content=raw, headers=headers)
        r2 = await c.post(f"{base}/webhook/razorpay", content=raw, headers=headers)
        print("delivery 1:", r1.status_code, r1.json())
        print("delivery 2:", r2.status_code, r2.json(), "  <- duplicate expected True")

        await asyncio.sleep(2.0)  # let BackgroundTasks finish

        rest = settings.rest_url
        k = settings.supabase_secret_key
        h = {"apikey": k, "Authorization": f"Bearer {k}"}
        cases = (await c.get(f"{rest}/recovery_case",
                             headers=h,
                             params={"source_event_id": f"eq.{meta['event_id']}",
                                     "select": "case_id,state,outcome,cohort,amount_at_risk,"
                                               "reason,last_decision"})).json()
        if not cases:
            print("\nNO CASE FOUND — is migration 002 applied and the server on new code?")
            return
        case = cases[0]
        print("\nRecoveryCase:")
        for kk in ("case_id", "state", "outcome", "cohort", "amount_at_risk", "reason"):
            print(f"  {kk:16} {case[kk]}")
        dec = case.get("last_decision") or {}
        print(f"  resolved_action  {dec.get('resolved_action')}")
        print(f"  resolved_amount  {dec.get('resolved_amount')}")

        log = (await c.get(f"{rest}/action_log",
                           headers=h,
                           params={"case_id": f"eq.{case['case_id']}",
                                   "order": "created_at.asc",
                                   "select": "event,from_state,to_state,actor,detail"})).json()
        print(f"\nAudit timeline ({len(log)} entries):")
        for e in log:
            arrow = f"{e['from_state'] or '-'} -> {e['to_state'] or '-'}"
            extra = ""
            if e["event"] == "action_executed":
                extra = f"  {e['detail'].get('short_url') or e['detail'].get('action')}"
            if e["event"] == "policy_decision":
                extra = f"  approved={e['detail'].get('approved')}"
            print(f"  [{e['actor']:8}] {e['event']:18} {arrow}{extra}")

        n_exec = sum(1 for e in log if e["event"] == "action_executed")
        print(f"\nactions executed: {n_exec}  (idempotency OK)" if n_exec == 1
              else f"\n!! actions executed: {n_exec}")


if __name__ == "__main__":
    asyncio.run(main())
