from app.mocks.common import MockServiceDB

CRM_SCHEMA = """
CREATE TABLE IF NOT EXISTS customers(
    id TEXT PRIMARY KEY,
    name TEXT,
    first_name TEXT,
    role TEXT,
    language TEXT,
    upi_id TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    kyc_status TEXT,
    device_info_json TEXT
);

CREATE TABLE IF NOT EXISTS cases(
    id TEXT PRIMARY KEY,
    user_id TEXT,
    agent TEXT,
    state TEXT,
    owner_id TEXT,
    outcome TEXT,
    created_at TEXT,
    updated_at TEXT,
    case_hint TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tickets(
    id TEXT PRIMARY KEY,
    case_id TEXT,
    user_id TEXT,
    category TEXT,
    details_json TEXT,
    status TEXT,
    created_at TEXT,
    case_hint TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS notes(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    user_id TEXT,
    author TEXT,
    text TEXT,
    created_at TEXT,
    case_hint TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS handoffs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    user_id TEXT,
    packet_json TEXT,
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

crm_db = MockServiceDB("crm", CRM_SCHEMA)

