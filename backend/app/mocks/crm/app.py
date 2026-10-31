import json
from typing import Any

from fastapi import Header, Request
from fastapi.responses import JSONResponse

from app.core.events import bus
from app.core.ids import next_id
from app.db.core import utc_now_iso
from app.mocks.common import make_mock_app, shift_iso_ts
from app.mocks.crm.db import crm_db


def get_crm_rows(limit: int = 8) -> list[dict[str, Any]]:
    cases = crm_db.query_all(
        "SELECT id, user_id, agent, state, owner_id, outcome, updated_at, case_hint FROM cases ORDER BY updated_at DESC LIMIT 6"
    )
    tickets = crm_db.query_all(
        "SELECT id, case_id, user_id, category, status, created_at as updated_at, case_hint FROM tickets ORDER BY created_at DESC LIMIT 4"
    )
    combined: list[dict[str, Any]] = []
    for c in cases:
        combined.append(
            {
                "id": c["id"],
                "case_id": c["id"],
                "customer": c["user_id"],
                "agent": c["agent"],
                "state": c["state"],
                "owner": c["owner_id"] or "saathi",
                "updated_at": c["updated_at"],
            }
        )
    for t in tickets:
        combined.append(
            {
                "id": t["id"],
                "case_id": t["case_id"],
                "customer": t["user_id"],
                "agent": f"TICKET:{t['category']}",
                "state": t["status"],
                "owner": "ops",
                "updated_at": t["updated_at"],
            }
        )
    combined.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return combined[:limit]


def shift_crm_time(hours: float) -> None:
    rows = crm_db.query_all("SELECT id, created_at, updated_at FROM cases")
    for r in rows:
        crm_db.execute(
            "UPDATE cases SET created_at = ?, updated_at = ? WHERE id = ?",
            (shift_iso_ts(r["created_at"], hours), shift_iso_ts(r["updated_at"], hours), r["id"]),
        )


crm_app, crm_sim = make_mock_app("crm", crm_db, get_crm_rows, shift_crm_time)


@crm_app.get("/customers/{customer_id}")
async def get_customer(
    customer_id: str,
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    if customer_id != x_acting_user:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    row = crm_db.query_one("SELECT * FROM customers WHERE id = ?", (customer_id,))
    if not row:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    out = dict(row)
    out["device_info"] = json.loads(out.pop("device_info_json", "{}") or "{}")
    return out


@crm_app.post("/cases")
async def create_crm_case(
    request: Request,
    payload: dict[str, Any],
    x_acting_user: str = Header(alias="X-Acting-User"),
    x_case_id: str | None = Header(default="", alias="X-Case-Id"),
):
    case_id = str(payload.get("id") or x_case_id or next_id("case"))
    agent = str(payload.get("agent", "triage"))
    state = str(payload.get("state", "OPEN"))
    owner_id = str(payload.get("owner_id", ""))
    outcome = str(payload.get("outcome", ""))
    now_iso = utc_now_iso()
    row = {
        "id": case_id,
        "user_id": x_acting_user,
        "agent": agent,
        "state": state,
        "owner_id": owner_id,
        "outcome": outcome,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    if getattr(request.state, "is_phantom", False):
        return JSONResponse(status_code=201, content=row)

    crm_db.execute(
        "INSERT OR REPLACE INTO cases(id, user_id, agent, state, owner_id, outcome, created_at, updated_at, case_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (case_id, x_acting_user, agent, state, owner_id, outcome, now_iso, now_iso, case_id),
    )
    bus.publish_system_change("crm", "cases", case_id, case_id)
    return JSONResponse(status_code=201, content=row)


@crm_app.patch("/cases/{case_id}")
async def update_crm_case(
    case_id: str,
    payload: dict[str, Any],
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    existing = crm_db.query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    now_iso = utc_now_iso()
    if not existing:
        crm_db.execute(
            "INSERT INTO cases(id, user_id, agent, state, owner_id, outcome, created_at, updated_at, case_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id,
                x_acting_user,
                payload.get("agent", "triage"),
                payload.get("state", "OPEN"),
                payload.get("owner_id", ""),
                payload.get("outcome", ""),
                now_iso,
                now_iso,
                case_id,
            ),
        )
    else:
        if existing["user_id"] != x_acting_user:
            return JSONResponse(status_code=404, content={"error": "not_found"})
        agent = payload.get("agent", existing["agent"])
        state = payload.get("state", existing["state"])
        owner_id = payload.get("owner_id", existing["owner_id"])
        outcome = payload.get("outcome", existing["outcome"])
        crm_db.execute(
            "UPDATE cases SET agent = ?, state = ?, owner_id = ?, outcome = ?, updated_at = ? WHERE id = ?",
            (agent, state, owner_id, outcome, now_iso, case_id),
        )
    bus.publish_system_change("crm", "cases", case_id, case_id)
    return crm_db.query_one("SELECT * FROM cases WHERE id = ?", (case_id,))


@crm_app.post("/tickets")
async def create_ticket(
    request: Request,
    payload: dict[str, Any],
    x_acting_user: str = Header(alias="X-Acting-User"),
    x_case_id: str | None = Header(default="", alias="X-Case-Id"),
):
    while True:
        ticket_id = next_id("ticket")
        if not crm_db.query_one("SELECT id FROM tickets WHERE id = ?", (ticket_id,)):
            break
    case_id = str(payload.get("case_id") or x_case_id or "")
    category = str(payload.get("category", "GENERAL"))
    details = payload.get("details", {})
    now_iso = utc_now_iso()
    row = {
        "id": ticket_id,
        "case_id": case_id,
        "user_id": x_acting_user,
        "category": category,
        "details": details if isinstance(details, dict) else {"info": str(details)},
        "status": "OPEN",
        "created_at": now_iso,
    }
    if getattr(request.state, "is_phantom", False):
        return JSONResponse(status_code=201, content=row)

    crm_db.execute(
        "INSERT INTO tickets(id, case_id, user_id, category, details_json, status, created_at, case_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ticket_id, case_id, x_acting_user, category, json.dumps(row["details"]), "OPEN", now_iso, case_id),
    )
    bus.publish_system_change("crm", "tickets", ticket_id, case_id)
    return JSONResponse(status_code=201, content=row)


@crm_app.get("/tickets/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    row = crm_db.query_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
    if not row or row["user_id"] != x_acting_user:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return row


@crm_app.post("/notes")
async def add_note(
    payload: dict[str, Any],
    x_acting_user: str = Header(alias="X-Acting-User"),
    x_case_id: str | None = Header(default="", alias="X-Case-Id"),
):
    case_id = str(payload.get("case_id") or x_case_id or "")
    author = str(payload.get("author", "saathi"))
    text = str(payload.get("text", ""))
    now_iso = utc_now_iso()
    nid = crm_db.execute(
        "INSERT INTO notes(case_id, user_id, author, text, created_at, case_hint) VALUES (?, ?, ?, ?, ?, ?)",
        (case_id, x_acting_user, author, text, now_iso, case_id),
    )
    bus.publish_system_change("crm", "notes", str(nid), case_id)
    return JSONResponse(status_code=201, content={"id": nid, "case_id": case_id, "author": author, "text": text, "created_at": now_iso})


@crm_app.post("/handoffs")
async def post_handoff(
    payload: dict[str, Any],
    x_acting_user: str = Header(alias="X-Acting-User"),
    x_case_id: str | None = Header(default="", alias="X-Case-Id"),
):
    case_id = str(payload.get("case_id") or x_case_id or "")
    packet = payload.get("packet", payload)
    now_iso = utc_now_iso()
    hid = crm_db.execute(
        "INSERT INTO handoffs(case_id, user_id, packet_json, created_at, case_hint) VALUES (?, ?, ?, ?, ?)",
        (case_id, x_acting_user, json.dumps(packet), now_iso, case_id),
    )
    bus.publish_system_change("crm", "handoffs", case_id or str(hid), case_id)
    return JSONResponse(status_code=201, content={"id": hid, "case_id": case_id, "status": "STORED", "created_at": now_iso})

