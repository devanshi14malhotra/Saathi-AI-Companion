from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import cfg_mgr
from app.mocks.ledger.db import ledger_db


def seed_ledger(extra_ops: list[dict[str, Any]] | None = None) -> None:
    ledger_db.init_db()
    with ledger_db.lock:
        conn = ledger_db.get_conn()
        for tbl in ("users", "transactions", "locks", "request_log"):
            conn.execute(f"DELETE FROM {tbl}")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tbl,))
        conn.commit()

    now = datetime.now(timezone.utc)
    personas = cfg_mgr.get_personas()
    for pid, p in personas.items():
        ledger_db.execute(
            "INSERT OR REPLACE INTO users(id, profile_name, profile_first, upi_id, phone, email, role) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                pid,
                p.get("name", pid),
                p.get("first_name", pid),
                p.get("upi_id", ""),
                p.get("phone", ""),
                p.get("email", ""),
                p.get("role", "consumer"),
            ),
        )

    for txn in cfg_mgr.base_seeds.get("transactions", []):
        _insert_txn(txn, now)

    if extra_ops:
        apply_ledger_ops(extra_ops)


def _insert_txn(txn: dict[str, Any], now: datetime | None = None) -> None:
    if now is None:
        now = datetime.now(timezone.utc)
    age_hours = float(txn.get("age_hours", 28))
    created_at = (now - timedelta(hours=age_hours)).isoformat()
    rev_eta_hours = txn.get("reversal_eta_hours")
    rev_eta = (now + timedelta(hours=float(rev_eta_hours))).isoformat() if rev_eta_hours is not None else (
        (datetime.fromisoformat(created_at) + timedelta(hours=24)).isoformat()
    )
    remark = str(txn.get("remark", ""))[:80]
    rail = str(txn.get("rail", "BILL_PAY"))
    ledger_db.execute(
        """
        INSERT OR REPLACE INTO transactions(
            id, user_id, amount, counterparty, status, debit_status, bank_debit_status,
            credit_to_merchant, bank_code, reversal_status, reversal_eta, rail, remark, created_at, updated_at, case_hint
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            txn["id"],
            txn["user"],
            int(txn["amount"]),
            txn.get("counterparty", "Merchant"),
            txn.get("status", "FAILED"),
            txn.get("debit_status", "DEBITED"),
            txn.get("bank_debit_status", txn.get("debit_status", "DEBITED")),
            int(txn.get("credit_to_merchant", 0)),
            txn.get("bank_code", "BANK_TIMEOUT"),
            txn.get("reversal_status", "NONE"),
            rev_eta,
            rail,
            remark,
            created_at,
            created_at,
            "",
        ),
    )


def apply_ledger_ops(ops: list[dict[str, Any]]) -> None:
    now = datetime.now(timezone.utc)
    for op in ops:
        if op.get("op") == "add_txn":
            _insert_txn(op, now)

