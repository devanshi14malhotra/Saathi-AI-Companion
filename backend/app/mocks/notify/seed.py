from typing import Any

from app.mocks.notify.db import notify_db


def seed_notify(extra_ops: list[dict[str, Any]] | None = None) -> None:
    notify_db.init_db()
    with notify_db.lock:
        conn = notify_db.get_conn()
        for tbl in ("outbox", "followups", "request_log"):
            conn.execute(f"DELETE FROM {tbl}")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tbl,))
        conn.commit()

