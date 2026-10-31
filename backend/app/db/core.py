import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.ids import set_min_counter

ROOT_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT_DIR / "backend" / ".data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CORE_DB_PATH = DATA_DIR / "core.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cases(
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    persona_id TEXT,
    source TEXT,
    state TEXT,
    agent TEXT,
    intent TEXT,
    language TEXT,
    sentiment TEXT,
    outcome TEXT,
    rule_fired TEXT,
    trigger TEXT,
    diagnosis TEXT,
    owner_id TEXT,
    masked_text TEXT,
    extraction_json TEXT,
    guard_hit INTEGER DEFAULT 0,
    clarification_used INTEGER DEFAULT 0,
    created_at TEXT,
    closed_at TEXT,
    lane TEXT,
    reopened INTEGER DEFAULT 0,
    confidence REAL,
    confidence_band TEXT
);

CREATE TABLE IF NOT EXISTS case_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    seq INTEGER,
    ts TEXT,
    badge TEXT,
    type TEXT,
    summary TEXT,
    payload_json TEXT,
    latency_ms INTEGER,
    status TEXT DEFAULT 'ok'
);

CREATE TABLE IF NOT EXISTS messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT,
    case_id TEXT,
    role TEXT,
    kind TEXT,
    body_json TEXT,
    ts TEXT
);

CREATE TABLE IF NOT EXISTS approvals(
    id TEXT PRIMARY KEY,
    case_id TEXT,
    proposed_action_json TEXT,
    rule_fired TEXT,
    status TEXT,
    decided_by TEXT,
    reason_code TEXT,
    reason_text TEXT,
    created_at TEXT,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    actor TEXT,
    action TEXT,
    params_json TEXT,
    result_json TEXT,
    idem_key TEXT,
    case_id TEXT
);

CREATE TABLE IF NOT EXISTS pii_tokens(
    case_id TEXT,
    token TEXT,
    value TEXT
);

CREATE TABLE IF NOT EXISTS config_audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    actor TEXT,
    key TEXT,
    old TEXT,
    new TEXT
);

CREATE TABLE IF NOT EXISTS config_state(
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS eval_runs(
    id TEXT PRIMARY KEY,
    ts TEXT,
    split TEXT,
    status TEXT,
    progress TEXT,
    results_json TEXT
);

CREATE TABLE IF NOT EXISTS case_notes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    author TEXT,
    text TEXT,
    ts TEXT
);

CREATE TABLE IF NOT EXISTS console_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT,
    event TEXT,
    payload_json TEXT,
    ts TEXT
);

CREATE TABLE IF NOT EXISTS complaint_signals(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    persona_id TEXT,
    case_id TEXT,
    signature TEXT,
    bank_code TEXT,
    merchant TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS incidents(
    id TEXT PRIMARY KEY,
    signature TEXT,
    bank_code TEXT,
    merchant TEXT,
    signal_count INTEGER,
    user_count INTEGER,
    first_signal_at TEXT,
    detected_at TEXT,
    status TEXT,
    notice_text TEXT,
    public_status INTEGER DEFAULT 0,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS incident_actions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT,
    persona_id TEXT,
    case_id TEXT,
    action TEXT,
    outcome TEXT,
    ts TEXT
);

CREATE TABLE IF NOT EXISTS followup_checks(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    kind TEXT,
    due_at TEXT,
    status TEXT,
    result_json TEXT,
    checked_at TEXT
);

CREATE TABLE IF NOT EXISTS compensation_claims(
    id TEXT PRIMARY KEY,
    case_id TEXT,
    txn_id TEXT,
    rule_id TEXT,
    days_late INTEGER,
    amount_estimate INTEGER,
    status TEXT,
    note TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS decision_timings(
    approval_id TEXT,
    view_mode TEXT,
    opened_at TEXT,
    decided_at TEXT,
    decision TEXT,
    decided_by TEXT
);

CREATE TABLE IF NOT EXISTS confidence_log(
    case_id TEXT PRIMARY KEY,
    score REAL,
    band TEXT,
    signals_json TEXT,
    correct INTEGER
);

CREATE TABLE IF NOT EXISTS llm_usage(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    case_id TEXT,
    kind TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    latency_ms INTEGER
);

CREATE TABLE IF NOT EXISTS override_tests(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    reason_code TEXT,
    snapshot_json TEXT,
    suggested_change TEXT,
    status TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS autonomy_decisions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    agent TEXT,
    case_id TEXT,
    mode TEXT,
    agreed INTEGER,
    decided_by TEXT,
    source TEXT
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sync_id_counters(conn: sqlite3.Connection | None = None) -> None:
    """Sync all in-memory ID counters with max existing records in tables."""
    sync_targets = [
        ("cases", "case", "C-"),
        ("approvals", "approval", "AP-"),
        ("incidents", "incident", "INC-"),
        ("compensation_claims", "claim", "CMP-"),
        ("eval_runs", "eval", "EV-"),
    ]
    if conn is not None:
        for table, kind, prefix in sync_targets:
            try:
                rows = conn.execute(f"SELECT id FROM {table}").fetchall()
                for r in rows:
                    item_id = r["id"]
                    if isinstance(item_id, str) and item_id.startswith(prefix):
                        try:
                            num = int(item_id[len(prefix):])
                            set_min_counter(kind, num)
                        except ValueError:
                            pass
            except Exception:
                pass

    # Also scan external mock service databases to guarantee zero collisions across restarts
    mock_targets = [
        (DATA_DIR / "crm.db", "tickets", "ticket", "TK-"),
        (DATA_DIR / "ledger.db", "locks", "lock", "LK-"),
        (DATA_DIR / "refunds.db", "refunds", "refund", "RF-"),
        (DATA_DIR / "refunds.db", "reconciliations", "recon", "RC-"),
    ]
    for db_path, table, kind, prefix in mock_targets:
        if db_path.exists():
            try:
                mconn = sqlite3.connect(str(db_path))
                mrows = mconn.execute(f"SELECT id FROM {table}").fetchall()
                for mr in mrows:
                    item_id = mr[0]
                    if isinstance(item_id, str) and item_id.startswith(prefix):
                        try:
                            num = int(item_id[len(prefix):])
                            set_min_counter(kind, num)
                        except ValueError:
                            pass
                mconn.close()
            except Exception:
                pass


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(CORE_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
        _conn.execute("PRAGMA synchronous=NORMAL;")
        _conn.execute("PRAGMA temp_store=MEMORY;")
        _conn.executescript(SCHEMA_SQL)
        _conn.commit()
        sync_id_counters(_conn)
    return _conn


def init_core_db(default_autonomy: dict[str, str] | None = None) -> None:
    with _lock:
        conn = get_conn()
        conn.executescript(SCHEMA_SQL)
        if default_autonomy:
            for agent_name, mode in default_autonomy.items():
                cur = conn.execute("SELECT value FROM config_state WHERE key = ?", (f"autonomy:{agent_name}",)).fetchone()
                if not cur:
                    conn.execute(
                        "INSERT OR REPLACE INTO config_state(key, value) VALUES (?, ?)",
                        (f"autonomy:{agent_name}", mode),
                    )
        sync_id_counters(conn)
        conn.commit()


def reset_core_db(default_autonomy: dict[str, str], preserve_eval_runs: bool = True, preserve_confidence_log: bool = True) -> None:
    with _lock:
        conn = get_conn()
        tables_to_clear = [
            "cases",
            "case_events",
            "messages",
            "approvals",
            "audit_log",
            "pii_tokens",
            "config_audit",
            "config_state",
            "case_notes",
            "console_events",
            "complaint_signals",
            "incidents",
            "incident_actions",
            "followup_checks",
            "compensation_claims",
            "override_tests",
            "autonomy_decisions",
        ]
        if not preserve_eval_runs:
            tables_to_clear.append("eval_runs")
            tables_to_clear.append("decision_timings")
            tables_to_clear.append("llm_usage")
        if not preserve_confidence_log:
            tables_to_clear.append("confidence_log")

        for tbl in tables_to_clear:
            conn.execute(f"DELETE FROM {tbl}")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (tbl,))

        for agent_name, mode in default_autonomy.items():
            conn.execute(
                "INSERT OR REPLACE INTO config_state(key, value) VALUES (?, ?)",
                (f"autonomy:{agent_name}", mode),
            )
        conn.commit()


def execute(sql: str, params: tuple | list = ()) -> int:
    with _lock:
        conn = get_conn()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid or 0


def query_all(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with _lock:
        conn = get_conn()
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def query_one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    with _lock:
        conn = get_conn()
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
