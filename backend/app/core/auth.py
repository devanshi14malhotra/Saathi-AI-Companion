from typing import Any

from fastapi import Header, HTTPException

from app.core.config import cfg_mgr


def resolve_persona_from_token(authorization: str | None, x_persona: str | None = None) -> dict[str, Any]:
    persona_id: str | None = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if not token.startswith("demo."):
            raise HTTPException(status_code=401, detail={"error": "unauthorized"})
        persona_id = token.split("demo.", 1)[1].strip()
    elif x_persona:
        persona_id = x_persona.strip()
    else:
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})

    personas = cfg_mgr.get_personas()
    if persona_id not in personas:
        raise HTTPException(status_code=401, detail={"error": "unknown_persona"})
    return personas[persona_id]


def resolve_persona_from_query(persona: str | None) -> dict[str, Any]:
    if not persona:
        raise HTTPException(status_code=401, detail={"error": "unauthorized"})
    personas = cfg_mgr.get_personas()
    if persona not in personas:
        raise HTTPException(status_code=401, detail={"error": "unknown_persona"})
    return personas[persona]


async def get_current_persona(
    authorization: str | None = Header(default=None),
    x_persona: str | None = Header(default=None, alias="X-Persona"),
) -> dict[str, Any]:
    return resolve_persona_from_token(authorization, x_persona)


async def get_console_persona(
    authorization: str | None = Header(default=None),
    x_persona: str | None = Header(default=None, alias="X-Persona"),
) -> dict[str, Any]:
    p = resolve_persona_from_token(authorization, x_persona)
    if p.get("role") not in ("agent", "ops_lead"):
        raise HTTPException(status_code=403, detail={"error": "forbidden"})
    return p


async def get_ops_lead_persona(
    authorization: str | None = Header(default=None),
    x_persona: str | None = Header(default=None, alias="X-Persona"),
) -> dict[str, Any]:
    p = resolve_persona_from_token(authorization, x_persona)
    if p.get("role") != "ops_lead":
        raise HTTPException(status_code=403, detail={"error": "ops_lead_required"})
    return p
