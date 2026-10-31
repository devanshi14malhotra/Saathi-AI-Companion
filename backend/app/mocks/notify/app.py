from typing import Any

from fastapi import Header
from fastapi.responses import JSONResponse

from app.core.events import bus
from app.db.core import utc_now_iso
from app.mocks.common import make_mock_app, shift_iso_ts
from app.mocks.notify.db import notify_db


def get_notify_rows(limit: int = 8) -> list[dict[str, Any]]:
    msgs = notify_db.query_all(
        "SELECT id, user_id, channel, message, case_id, created_at, case_hint FROM outbox ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    out = []
    for m in msgs:
        out.append(
            {
                "id": f"MSG-{m['id']}",
                "time": m["created_at"],
                "channel": m["channel"],
                "to": m["user_id"],
                "message": (m["message"] or "")[:90],
                "case_id": m["case_id"] or m["case_hint"],
            }
        )
    return out


def shift_notify_time(hours: float) -> None:
    rows = notify_db.query_all("SELECT id, created_at FROM outbox")
    for r in rows:
        notify_db.execute(
            "UPDATE outbox SET created_at = ? WHERE id = ?",
            (shift_iso_ts(r["created_at"], hours), r["id"]),
        )


notify_app, notify_sim = make_mock_app("notify", notify_db, get_notify_rows, shift_notify_time)


@notify_app.post("/messages")
async def send_message(
    payload: dict[str, Any],
    x_acting_user: str = Header(alias="X-Acting-User"),
    x_case_id: str | None = Header(default="", alias="X-Case-Id"),
):
    channel = str(payload.get("channel", "in_app"))
    message = str(payload.get("message", ""))
    case_id = str(payload.get("case_id") or x_case_id or "")
    now_iso = utc_now_iso()
    mid = notify_db.execute(
        "INSERT INTO outbox(user_id, channel, message, case_id, created_at, case_hint) VALUES (?, ?, ?, ?, ?, ?)",
        (x_acting_user, channel, message, case_id, now_iso, case_id),
    )
    row_id = f"MSG-{mid}"
    bus.publish_system_change("notify", "outbox", row_id, case_id)
    return JSONResponse(
        status_code=201,
        content={"id": row_id, "user_id": x_acting_user, "channel": channel, "case_id": case_id, "status": "SENT", "created_at": now_iso},
    )


@notify_app.post("/followups")
async def schedule_followup(
    payload: dict[str, Any],
    x_acting_user: str = Header(alias="X-Acting-User"),
    x_case_id: str | None = Header(default="", alias="X-Case-Id"),
):
    case_id = str(payload.get("case_id") or x_case_id or "")
    run_in_minutes = int(payload.get("run_in_minutes", 360))
    check_kind = str(payload.get("check", "REFUND_COMPLETED"))
    now_iso = utc_now_iso()
    fid = notify_db.execute(
        "INSERT INTO followups(user_id, case_id, run_in_minutes, check_kind, status, created_at, case_hint) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (x_acting_user, case_id, run_in_minutes, check_kind, "SCHEDULED", now_iso, case_id),
    )
    bus.publish_system_change("notify", "followups", f"FLW-{fid}", case_id)
    return JSONResponse(
        status_code=201,
        content={
            "id": f"FLW-{fid}",
            "user_id": x_acting_user,
            "case_id": case_id,
            "run_in_minutes": run_in_minutes,
            "check": check_kind,
            "status": "SCHEDULED",
            "created_at": now_iso,
        },
    )


@notify_app.get("/outbox")
async def get_outbox(
    x_acting_user: str = Header(alias="X-Acting-User"),
):
    rows = notify_db.query_all(
        "SELECT id, user_id, channel, message, case_id, created_at FROM outbox WHERE user_id = ? ORDER BY id DESC",
        (x_acting_user,),
    )
    return rows

