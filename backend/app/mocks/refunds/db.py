from app.mocks.common import MockServiceDB

REFUNDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS refunds(
    id TEXT PRIMARY KEY,
    txn_id TEXT,
    user_id TEXT,
    amount INTEGER,
    status TEXT,
    reason TEXT,
    idem_key TEXT,
    initiated_at TEXT,
    eta TEXT,
    completed_at TEXT,
    updated_at TEXT,
    case_hint TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settlements(
    id TEXT PRIMARY KEY,
    merchant_id TEXT,
    expected_amount INTEGER,
    actual_amount INTEGER,
    status TEXT,
    hold_reason TEXT,
    due_date TEXT,
    updated_at TEXT,
    case_hint TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS reconciliations(
    id TEXT PRIMARY KEY,
    ref_type TEXT,
    ref_id TEXT,
    case_id TEXT,
    user_id TEXT,
    status TEXT,
    created_at TEXT,
    case_hint TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS bank_holidays(
    date_str TEXT PRIMARY KEY
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

refunds_db = MockServiceDB("refunds", REFUNDS_SCHEMA)

