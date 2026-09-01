"""Razorpay webhook receiver.

Contract (Razorpay): respond 2xx within 5 seconds or the delivery is marked
failed and retried with backoff. So this endpoint does the minimum inline —
verify signature, dedupe-insert — and hands the pipeline to BackgroundTasks.

Signature verification and idempotency are deterministic code; the LLM is never
on this path (architectural law).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, Request
from fastapi.responses import JSONResponse

from app import audit, db, pipeline
from app.config import settings
from app.security import verify_webhook_signature

router = APIRouter()


@router.post("/webhook/razorpay")
@router.post("/webhook")
async def razorpay_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_razorpay_event_id: str | None = Header(default=None),
    x_razorpay_signature: str | None = Header(default=None),
) -> JSONResponse:
    raw_body = await request.body()

    signature_ok = verify_webhook_signature(
        raw_body, x_razorpay_signature, settings.razorpay_webhook_secret
    )
    if not signature_ok:
        # Not a transient error — do not make Razorpay retry a bad-signature body.
        await audit.record(
            case_id=None, actor="webhook", event="error",
            detail={"reason": "invalid_signature", "event_id": x_razorpay_event_id},
        )
        return JSONResponse(status_code=400, content={"error": "invalid signature"})

    try:
        payload: dict[str, Any] = json.loads(raw_body or b"{}")
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": "invalid json"})

    event_id = x_razorpay_event_id or payload.get("id") or "unknown"
    event_type = payload.get("event")

    inserted = await db.insert("webhook_event", {
        "event_id": event_id,
        "event_type": event_type,
        "payload": payload,
        "signature_verified": True,
    })
    is_duplicate = inserted is None and settings.supabase_configured

    # Only the first delivery of a given event id enqueues work.
    if not is_duplicate:
        background_tasks.add_task(pipeline.process_webhook_event, event_id)

    return JSONResponse(status_code=200, content={
        "status": "received",
        "event_id": event_id,
        "event_type": event_type,
        "duplicate": is_duplicate,
    })
