"""Thin async Supabase (PostgREST) client.

Phase 0 keeps the dependency surface tiny: just httpx against the REST API,
no supabase-py. If a webhook arrives before Supabase is configured we fall
back to appending the event to a local log file so the pipeline is still
observable in dev.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

_LOCAL_LOG = Path("data/webhook_events.log")


class SupabaseError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    key = settings.supabase_secret_key
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def insert(table: str, row: dict[str, Any], *, upsert: bool = False) -> dict[str, Any] | None:
    """Insert one row. Returns the inserted row, or None on a swallowed duplicate.

    Raises SupabaseError on unexpected failures. A 409 unique-violation is
    returned as None so callers can treat it as an idempotent no-op.
    """
    if not settings.supabase_configured:
        _local_append(table, row)
        return None

    prefer = "resolution=merge-duplicates,return=representation" if upsert else "return=representation"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.rest_url}/{table}",
            headers={**_headers(), "Prefer": prefer},
            json=row,
        )
    if resp.status_code in (200, 201):
        data = resp.json()
        return data[0] if isinstance(data, list) and data else data
    if resp.status_code == 409:
        return None  # unique violation -> idempotent no-op
    raise SupabaseError(f"insert {table} failed: {resp.status_code} {resp.text}")


async def select(table: str, *, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    if not settings.supabase_configured:
        return []
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{settings.rest_url}/{table}",
            headers=_headers(),
            params=params or {},
        )
    if resp.status_code == 200:
        return resp.json()
    raise SupabaseError(f"select {table} failed: {resp.status_code} {resp.text}")


async def health() -> dict[str, Any]:
    """Lightweight connectivity probe against PostgREST."""
    if not settings.supabase_configured:
        return {"configured": False, "reachable": False}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.rest_url}/webhook_event",
                headers={**_headers(), "Range": "0-0"},
                params={"select": "id"},
            )
        return {"configured": True, "reachable": resp.status_code < 500, "status": resp.status_code}
    except httpx.HTTPError as exc:
        return {"configured": True, "reachable": False, "error": str(exc)}


def _local_append(table: str, row: dict[str, Any]) -> None:
    _LOCAL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _LOCAL_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"table": table, "row": row}, default=str) + "\n")
