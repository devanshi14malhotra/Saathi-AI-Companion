import json
from typing import Any

from app.core.config import cfg_mgr
from app.mocks.crm.db import crm_db


def seed_crm(extra_ops: list[dict[str, Any]] | None = None) -> None:
    crm_db.init_db()
    with crm_db.lock:
        conn = crm_db.get_conn()
        for tbl in ("customers", "cases", "tickets", "notes", "handoffs", "request_log"):
            conn.execute(f"DELETE FROM {tbl}")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tbl,))
        conn.commit()

    personas = cfg_mgr.get_personas()
    for pid, p in personas.items():
        crm_db.execute(
            """
            INSERT OR REPLACE INTO customers(
                id, name, first_name, role, language, upi_id, phone, email, address, kyc_status, device_info_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pid,
                p.get("name", pid),
                p.get("first_name", pid),
                p.get("role", "consumer"),
                p.get("language", "en"),
                p.get("upi_id", ""),
                p.get("phone", ""),
                p.get("email", ""),
                p.get("address", ""),
                p.get("kyc_status", "FULL_KYC"),
                json.dumps(p.get("device_info", {})),
            ),
        )

