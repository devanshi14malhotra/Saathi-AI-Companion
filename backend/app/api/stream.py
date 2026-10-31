"""SSE Customer & Console Real-Time Streams with Last-Event-ID Replay (SPEC §19.7 & SPEC_V6 §9)."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.core.auth import resolve_persona_from_query, resolve_persona_from_token
from app.core.events import bus

router = APIRouter(prefix="/api/stream", tags=["stream"])


def _resolve_stream_persona(
    persona_query: str | None,
    authorization: str | None,
    x_persona: str | None,
) -> dict[str, Any]:
    if authorization or x_persona:
        return resolve_persona_from_token(authorization, x_persona)
    return resolve_persona_from_query(persona_query)


@router.get("/customer/{persona_id}")
async def stream_customer(
    request: Request,
    persona_id: str,
    persona: str | None = Query(default=None),
    last_event_id_query: int | None = Query(default=None, alias="lastEventId"),
    last_event_id_hdr: str | None = Header(default=None, alias="Last-Event-ID"),
    authorization: str | None = Header(default=None),
    x_persona: str | None = Header(default=None, alias="X-Persona"),
):
    caller = _resolve_stream_persona(persona or persona_id, authorization, x_persona)
    if caller["id"] != persona_id and caller.get("role") not in ("agent", "ops_lead"):
        raise HTTPException(status_code=403, detail={"error": "forbidden"})

    last_id: int | None = last_event_id_query
    if last_id is None and last_event_id_hdr and last_event_id_hdr.isdigit():
        last_id = int(last_event_id_hdr)

    replay_items = bus.get_customer_replay(persona_id, last_id) if last_id is not None else []
    q = bus.subscribe_customer(persona_id)

    async def event_generator():
        try:
            for item in replay_items:
                yield {
                    "id": str(item.get("id") or ""),
                    "event": item.get("event", "message"),
                    "data": json.dumps(item.get("data", {})),
                }
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield {
                        "id": str(item.get("id") or ""),
                        "event": item.get("event", "message"),
                        "data": json.dumps(item.get("data", {})),
                    }
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            bus.unsubscribe_customer(persona_id, q)

    return EventSourceResponse(event_generator())


@router.get("/console")
async def stream_console(
    request: Request,
    persona: str | None = Query(default=None),
    last_event_id_query: int | None = Query(default=None, alias="lastEventId"),
    last_event_id_hdr: str | None = Header(default=None, alias="Last-Event-ID"),
    authorization: str | None = Header(default=None),
    x_persona: str | None = Header(default=None, alias="X-Persona"),
):
    caller = _resolve_stream_persona(persona or "A-1", authorization, x_persona)
    if caller.get("role") not in ("agent", "ops_lead"):
        raise HTTPException(status_code=403, detail={"error": "forbidden"})

    last_id: int | None = last_event_id_query
    if last_id is None and last_event_id_hdr and last_event_id_hdr.isdigit():
        last_id = int(last_event_id_hdr)

    replay_items = bus.get_console_replay(last_id) if last_id is not None else []
    q = bus.subscribe_console()

    async def event_generator():
        try:
            for item in replay_items:
                yield {
                    "id": str(item.get("id") or ""),
                    "event": item.get("event", "console_event"),
                    "data": json.dumps(item.get("data", {})),
                }
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield {
                        "id": str(item.get("id") or ""),
                        "event": item.get("event", "console_event"),
                        "data": json.dumps(item.get("data", {})),
                    }
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}
        finally:
            bus.unsubscribe_console(q)

    return EventSourceResponse(event_generator())

