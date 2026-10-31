from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import cfg_mgr
from app.mocks.refunds.db import refunds_db


def seed_refunds(extra_ops: list[dict[str, Any]] | None = None) -> None:
    refunds_db.init_db()
    with refunds_db.lock:
        conn = refunds_db.get_conn()
        for tbl in ("refunds", "settlements", "reconciliations", "bank_holidays", "request_log"):
            conn.execute(f"DELETE FROM {tbl}")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tbl,))
        conn.commit()

    now = datetime.now(timezone.utc)
    # D15: bank_holidays = yesterday and today
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    refunds_db.execute("INSERT OR REPLACE INTO bank_holidays(date_str) VALUES (?)", (yesterday,))
    refunds_db.execute("INSERT OR REPLACE INTO bank_holidays(date_str) VALUES (?)", (today,))

    for rf in cfg_mgr.base_seeds.get("refunds", []):
        _insert_refund(rf, now)

    for st in cfg_mgr.base_seeds.get("settlements", []):
        _insert_settlement(st, now)

    if extra_ops:
        apply_refunds_ops(extra_ops)


def _insert_refund(rf: dict[str, Any], now: datetime | None = None) -> None:
    if now is None:
        now = datetime.now(timezone.utc)
    init_age = float(rf.get("initiated_age_hours", 24))
    eta_hours = float(rf.get("eta_hours_from_init", 72))
    initiated_at = now - timedelta(hours=init_age)
    eta = initiated_at + timedelta(hours=eta_hours)
    refunds_db.execute(
        """
        INSERT OR REPLACE INTO refunds(
            id, txn_id, user_id, amount, status, reason, idem_key, initiated_at, eta, completed_at, updated_at, case_hint
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rf["id"],
            rf["txn_id"],
            rf["user"],
            int(rf["amount"]),
            rf.get("status", "PROCESSING"),
            rf.get("reason", "REFUND_DUE"),
            f"seed|{rf['id']}",
            initiated_at.isoformat(),
            eta.isoformat(),
            rf.get("completed_at"),
            initiated_at.isoformat(),
            "",
        ),
    )


def _insert_settlement(st: dict[str, Any], now: datetime | None = None) -> None:
    if now is None:
        now = datetime.now(timezone.utc)
    due_age = float(st.get("due_age_hours", 24))
    due_dt = now - timedelta(hours=due_age)
    refunds_db.execute(
        """
        INSERT OR REPLACE INTO settlements(
            id, merchant_id, expected_amount, actual_amount, status, hold_reason, due_date, updated_at, case_hint
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            st["id"],
            st["merchant_id"],
            int(st["expected_amount"]),
            int(st.get("actual_amount", st["expected_amount"])),
            st.get("status", "PENDING"),
            st.get("hold_reason", "NONE"),
            due_dt.isoformat(),
            due_dt.isoformat(),
            "",
        ),
    )


def apply_refunds_ops(ops: list[dict[str, Any]]) -> None:
    now = datetime.now(timezone.utc)
    for op in ops:
        kind = op.get("op")
        if kind == "add_refund":
            _insert_refund(op, now)
        elif kind == "add_settlement":
            _insert_settlement(op, now)

