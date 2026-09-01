"""FastAPI entrypoint.  Run: uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

from fastapi import FastAPI

from app import db
from app.config import settings
from app.webhooks import router as webhooks_router

app = FastAPI(title="AI Revenue Recovery Engine", version="0.1.0")

app.include_router(webhooks_router)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "env": settings.app_env,
        "supabase": await db.health(),
        "razorpay_key_id_set": bool(settings.razorpay_key_id),
        "webhook_secret_set": bool(settings.razorpay_webhook_secret),
    }
