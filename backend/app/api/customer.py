"""Customer Chat, History, Receipt (F14), and Voice (F16) API Routes."""
from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.core.auth import get_current_persona
from app.core.config import ROOT_DIR, cfg_mgr
from app.core.orchestrator import build_case_receipt, handle_message
from app.db.core import query_all, query_one

router = APIRouter(prefix="/api/chat", tags=["customer"])


@router.post("/message")
async def post_chat_message(
    payload: dict[str, Any],
    persona: dict[str, Any] = Depends(get_current_persona),
):
    persona_id = persona["id"]
    body_persona = payload.get("persona_id") or payload.get("persona")
    if body_persona and body_persona != persona_id:
        if persona.get("role") not in ("agent", "ops_lead"):
            return JSONResponse(status_code=403, content={"error": "forbidden_cross_persona"})
        persona_id = str(body_persona)

    text = str(payload.get("text") or "")
    max_chars = int(cfg_mgr.thresholds.get("max_message_chars", 2000))
    if len(text) > max_chars:
        return JSONResponse(status_code=413, content={"error": "too_long", "max_chars": max_chars})

    case_id = payload.get("case_id")
    selected_txn_id = payload.get("selected_txn_id")
    source = str(payload.get("source") or "chat")

    try:
        detail = await handle_message(
            persona_id=persona_id,
            text=text,
            case_id=case_id,
            selected_txn_id=selected_txn_id,
            source=source,
        )
        return detail
    except PermissionError:
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    except ValueError as e:
        if "too_long" in str(e):
            return JSONResponse(status_code=413, content={"error": "too_long"})
        raise HTTPException(status_code=400, detail={"error": str(e)})


@router.get("/history/{persona_id}")
async def get_chat_history(
    persona_id: str,
    persona: dict[str, Any] = Depends(get_current_persona),
):
    if persona["id"] != persona_id and persona.get("role") not in ("agent", "ops_lead"):
        return JSONResponse(status_code=403, content={"error": "forbidden"})

    rows = query_all(
        "SELECT id, persona_id, case_id, role, kind, body_json, ts FROM messages WHERE persona_id = ? ORDER BY id ASC",
        (persona_id,),
    )
    messages = []
    for r in rows:
        body = json.loads(r["body_json"]) if r.get("body_json") else {}
        messages.append(
            {
                "id": r["id"],
                "persona_id": r["persona_id"],
                "case_id": r["case_id"],
                "role": r["role"],
                "kind": r["kind"],
                "ts": r["ts"],
                **body,
            }
        )

    cases = query_all(
        "SELECT * FROM cases WHERE persona_id = ? ORDER BY created_at DESC",
        (persona_id,),
    )
    open_incidents = query_all(
        "SELECT id, bank_code, merchant, notice_text, detected_at FROM incidents WHERE status = 'OPEN' AND public_status = 1 ORDER BY detected_at DESC"
    )
    return {
        "persona_id": persona_id,
        "messages": messages,
        "cases": cases,
        "public_incidents": open_incidents,
    }


@router.get("/cases/{case_id}/receipt")
async def get_case_receipt_route(
    case_id: str,
    persona: dict[str, Any] = Depends(get_current_persona),
):
    row = query_one("SELECT id, persona_id FROM cases WHERE id = ?", (case_id,))
    if not row:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    if row["persona_id"] != persona["id"] and persona.get("role") not in ("agent", "ops_lead"):
        return JSONResponse(status_code=403, content={"error": "forbidden"})
    return build_case_receipt(case_id)


@router.post("/voice")
async def post_chat_voice(
    request: Request,
    lang: str = Query(default="hinglish"),
    fixture: str | None = Query(default=None),
    persona: dict[str, Any] = Depends(get_current_persona),
):
    """
    F16: Voice-to-Resolution channel with explicit trust-boundary warning.
    Transcript is treated as untrusted customer input and routed through handle_message (Mask + Guard + Policy).
    """
    voice_enabled = os.environ.get("VOICE_ENABLED", "true").lower() in ("1", "true", "yes")
    if not voice_enabled:
        return JSONResponse(status_code=404, content={"error": "voice_disabled"})

    persona_id = persona["id"]
    body_bytes = await request.body()
    transcript = ""
    lang_code = lang if lang in ("hinglish", "en", "hi") else "hinglish"

    if body_bytes:
        try:
            parsed = json.loads(body_bytes.decode("utf-8"))
            if isinstance(parsed, dict):
                if parsed.get("persona_id") and persona.get("role") in ("agent", "ops_lead"):
                    persona_id = str(parsed["persona_id"])
                if parsed.get("lang") in ("hinglish", "en", "hi"):
                    lang_code = str(parsed["lang"])
                if parsed.get("fixture"):
                    fixture = str(parsed["fixture"])
                if parsed.get("transcript"):
                    transcript = str(parsed["transcript"])
        except Exception:
            pass

    if not transcript:
        fname = fixture or f"sample_{lang_code}.json"
        if not fname.endswith(".json"):
            fname = f"sample_{fname}.json"
        fpath = ROOT_DIR / "fixtures" / "voice" / fname
        if not fpath.exists():
            fpath = ROOT_DIR / "fixtures" / "voice" / "sample_hinglish.json"
        if fpath.exists():
            fdata = json.loads(fpath.read_text(encoding="utf-8"))
            transcript = str(fdata.get("transcript") or "")
            lang_code = str(fdata.get("language") or lang_code)
        else:
            transcript = "mera 500 ka bijli bill payment fail ho gaya par paisa kat gaya"

    max_chars = int(cfg_mgr.thresholds.get("max_message_chars", 2000))
    if len(transcript) > max_chars:
        return JSONResponse(status_code=413, content={"error": "too_long"})

    detail = await handle_message(
        persona_id=persona_id,
        text=transcript,
        source="voice",
    )
    return {
        "ok": True,
        "source": "voice",
        "language": lang_code,
        "transcript_untrusted": transcript,
        "masked_text": detail.get("masked_text"),
        "guard_hit": bool(detail.get("guard_hit")),
        "boundary_warning": "ASR voice transcript is untrusted customer input — scanned by PII Masker & Prompt-Injection Guard before extraction.",
        "case": detail,
    }

