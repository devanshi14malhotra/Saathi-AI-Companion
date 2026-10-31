from app.mocks.common import MockServiceDB

NOTIFY_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    channel TEXT,
    message TEXT,
    case_id TEXT,
    created_at TEXT,
    case_hint TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS followups(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    case_id TEXT,
    run_in_minutes INTEGER,
    check_kind TEXT,
    status TEXT,
    created_at TEXT,
    case_hint TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS request_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    method TEXT,
    path TEXT,
    acting_user TEXT,
    actor TEXT,
    status INTEGER,
    latency_ms INTEGER,
    request_json TEXT,
    response_json TEXT,
    case_hint TEXT
);
"""

notify_db = MockServiceDB("notify", NOTIFY_SCHEMA)

