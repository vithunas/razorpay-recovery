"""Razorpay webhook receiver.

Contract (Razorpay): respond 2xx within 5 seconds or the delivery is marked
failed and retried with backoff. So this module does the minimum inline —
read raw body, dedupe, persist — and hands heavy work to BackgroundTasks.

Phase 0: persist the raw event into `webhook_event`, deduped on the
`X-Razorpay-Event-Id` header via the table's unique constraint.
Phase 1 will add HMAC-SHA256 signature verification over the raw body and
the DETECTED -> ... state machine.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, Request
from fastapi.responses import JSONResponse

from app import db
from app.config import settings

router = APIRouter()


@router.post("/webhook")
async def razorpay_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_razorpay_event_id: str | None = Header(default=None),
    x_razorpay_signature: str | None = Header(default=None),
) -> JSONResponse:
    raw_body = await request.body()

    try:
        payload: dict[str, Any] = json.loads(raw_body or b"{}")
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": "invalid json"})

    event_id = x_razorpay_event_id or payload.get("id") or "unknown"
    event_type = payload.get("event")

    # TODO(Phase 1): verify HMAC-SHA256(raw_body, RAZORPAY_WEBHOOK_SECRET) == x_razorpay_signature
    signature_verified = False

    row = {
        "event_id": event_id,
        "event_type": event_type,
        "payload": payload,
        "signature_verified": signature_verified,
    }

    inserted = await db.insert("webhook_event", row)
    is_duplicate = inserted is None and settings.supabase_configured

    # Phase 1: background_tasks.add_task(process_event, event_id)

    return JSONResponse(
        status_code=200,
        content={
            "status": "received",
            "event_id": event_id,
            "event_type": event_type,
            "duplicate": is_duplicate,
        },
    )
