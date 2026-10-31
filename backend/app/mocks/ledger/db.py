from app.mocks.common import MockServiceDB

LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id TEXT PRIMARY KEY,
    profile_name TEXT,
    profile_first TEXT,
    upi_id TEXT,
    phone TEXT,
    email TEXT,
    role TEXT
);

CREATE TABLE IF NOT EXISTS transactions(
    id TEXT PRIMARY KEY,
    user_id TEXT,
    amount INTEGER,
    counterparty TEXT,
    status TEXT,
    debit_status TEXT,
    bank_debit_status TEXT,
    credit_to_merchant INTEGER,
    bank_code TEXT,
    reversal_status TEXT,
    reversal_eta TEXT,
    rail TEXT DEFAULT 'BILL_PAY',
    remark TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT,
    case_hint TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS locks(
    id TEXT PRIMARY KEY,
    user_id TEXT,
    instrument TEXT,
    hours INTEGER,
    reason TEXT,
    status TEXT,
    idem_key TEXT,
    created_at TEXT,
    expires_at TEXT,
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

ledger_db = MockServiceDB("ledger", LEDGER_SCHEMA)

