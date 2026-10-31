import asyncio
import json
import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import parse_qs

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.events import sanitize_payload
from app.db.core import DATA_DIR, utc_now_iso


class MockServiceDB:
    def __init__(self, name: str, schema_sql: str) -> None:
        self.name = name
        self.db_path = DATA_DIR / f"{name}.db"
        self.lock = threading.RLock()
        self.schema_sql = schema_sql
        self._conn: sqlite3.Connection | None = None

    def get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA temp_store=MEMORY;")
            self._conn.executescript(self.schema_sql)
            self._conn.commit()
        return self._conn

    def init_db(self) -> None:
        with self.lock:
            conn = self.get_conn()
            conn.executescript(self.schema_sql)
            conn.commit()

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        with self.lock:
            conn = self.get_conn()
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid or 0

    def query_all(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self.lock:
            conn = self.get_conn()
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def query_one(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        with self.lock:
            conn = self.get_conn()
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None


class SimController:
    def __init__(self, name: str) -> None:
        self.name = name
        self.latency_min_ms: int = 20
        self.latency_max_ms: int = 60
        self.fail_rules: list[dict[str, Any]] = []
        self.phantom_rules: list[dict[str, Any]] = []
        self.stuck_refund_ids: set[str] = set()
        self.stuck_txn_ids: set[str] = set()

    def reset(self) -> None:
        self.latency_min_ms = 20
        self.latency_max_ms = 60
        self.fail_rules.clear()
        self.phantom_rules.clear()
        self.stuck_refund_ids.clear()
        self.stuck_txn_ids.clear()

    def pending_failures_count(self) -> int:
        return sum(r.get("count", 0) for r in self.fail_rules if r.get("count", 0) > 0)

    def pending_phantoms_count(self) -> int:
        return sum(r.get("count", 0) for r in self.phantom_rules if r.get("count", 0) > 0)

    def match_fail_rule(self, method: str, path: str) -> str | None:
        for rule in self.fail_rules:
            if rule.get("count", 0) <= 0:
                continue
            rule_method = rule.get("method")
            if rule_method and rule_method.upper() != "ANY" and rule_method.upper() != method.upper():
                continue
            rule["count"] -= 1
            return rule.get("mode", "timeout")
        return None

    def match_phantom_rule(self, method: str, path: str) -> bool:
        for rule in self.phantom_rules:
            if rule.get("count", 0) <= 0:
                continue
            rule_method = rule.get("method")
            if rule_method and rule_method.upper() != "ANY" and rule_method.upper() != method.upper():
                continue
            prefix = rule.get("path_prefix")
            if prefix and not path.startswith(prefix):
                continue
            rule["count"] -= 1
            return True
        return False


def shift_iso_ts(ts_str: str | None, hours: float) -> str | None:
    if not ts_str:
        return ts_str
    try:
        dt = datetime.fromisoformat(ts_str)
        return (dt - timedelta(hours=hours)).isoformat()
    except Exception:
        return ts_str


class PureASGISimMiddleware:
    """Pure ASGI middleware for latency, fault/phantom/lost-response injection, and request_log."""

    def __init__(self, app: Any, db: MockServiceDB, sim: SimController) -> None:
        self.app = app
        self.db = db
        self.sim = sim

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path.startswith("/_sim"):
            await self.app(scope, receive, send)
            return

        t0 = time.perf_counter()
        method: str = scope.get("method", "GET").upper()
        headers_dict = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in (scope.get("headers") or [])
        }
        acting_user = headers_dict.get("x-acting-user", "")
        actor = headers_dict.get("x-actor", "saathi")
        case_hint = headers_dict.get("x-case-id", "")

        qs_bytes: bytes = scope.get("query_string") or b""
        req_json_str = "{}"
        if qs_bytes:
            try:
                parsed_qs = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(qs_bytes.decode("utf-8")).items()}
                req_json_str = json.dumps(sanitize_payload(parsed_qs))
            except Exception:
                req_json_str = "{}"

        if not acting_user:
            ms = int((time.perf_counter() - t0) * 1000)
            resp_obj = {"error": "missing_acting_user"}
            self.db.execute(
                "INSERT INTO request_log(ts, method, path, acting_user, actor, status, latency_ms, request_json, response_json, case_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (utc_now_iso(), method, path, "", actor, 400, ms, req_json_str, json.dumps(resp_obj), case_hint),
            )
            resp = JSONResponse(status_code=400, content=resp_obj)
            await resp(scope, receive, send)
            return

        # Simulated latency
        sleep_ms = random.randint(self.sim.latency_min_ms, max(self.sim.latency_min_ms, self.sim.latency_max_ms))
        if sleep_ms > 0:
            await asyncio.sleep(sleep_ms / 1000.0)

        # Failure injection check
        fail_mode = self.sim.match_fail_rule(method, path)
        if fail_mode in ("timeout", "error"):
            if fail_mode == "timeout":
                await asyncio.sleep(0.02)
                status_code = 504
                resp_obj = {"error": "timeout"}
            else:
                status_code = 500
                resp_obj = {"error": "server_error"}
            ms = int((time.perf_counter() - t0) * 1000)
            self.db.execute(
                "INSERT INTO request_log(ts, method, path, acting_user, actor, status, latency_ms, request_json, response_json, case_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (utc_now_iso(), method, path, acting_user, actor, status_code, ms, req_json_str, json.dumps(resp_obj), case_hint),
            )
            resp = JSONResponse(status_code=status_code, content=resp_obj)
            await resp(scope, receive, send)
            return

        # Attach phantom flag to scope["state"] so request.state.is_phantom works
        scope.setdefault("state", {})
        scope["state"]["is_phantom"] = (
            self.sim.match_phantom_rule(method, path) if method in ("POST", "PATCH", "PUT") else False
        )

        # Capture request body and response body via non-blocking wrappers
        req_chunks: list[bytes] = []
        resp_status = 200
        resp_chunks: list[bytes] = []

        async def wrapped_receive() -> dict[str, Any]:
            msg = await receive()
            if msg.get("type") == "http.request" and msg.get("body"):
                req_chunks.append(msg["body"])
            return msg

        if fail_mode == "lost_response":
            # Execute the downstream route handler so the DB write actually commits, then return 504!
            async def swallow_send(msg: dict[str, Any]) -> None:
                pass

            await self.app(scope, wrapped_receive, swallow_send)
            await asyncio.sleep(0.02)
            status_code = 504
            resp_obj = {"error": "timeout", "lost_response": True}
            ms = int((time.perf_counter() - t0) * 1000)
            if req_chunks:
                try:
                    req_json_str = json.dumps(sanitize_payload(json.loads(b"".join(req_chunks).decode("utf-8"))))
                except Exception:
                    pass
            self.db.execute(
                "INSERT INTO request_log(ts, method, path, acting_user, actor, status, latency_ms, request_json, response_json, case_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (utc_now_iso(), method, path, acting_user, actor, status_code, ms, req_json_str, json.dumps(resp_obj), case_hint),
            )
            resp = JSONResponse(status_code=status_code, content=resp_obj)
            await resp(scope, receive, send)
            return

        async def wrapped_send(msg: dict[str, Any]) -> None:
            nonlocal resp_status
            if msg.get("type") == "http.response.start":
                resp_status = int(msg.get("status", 200))
            elif msg.get("type") == "http.response.body" and msg.get("body"):
                resp_chunks.append(msg["body"])
            await send(msg)

        await self.app(scope, wrapped_receive, wrapped_send)

        if req_chunks:
            try:
                req_json_str = json.dumps(sanitize_payload(json.loads(b"".join(req_chunks).decode("utf-8"))))
            except Exception:
                pass

        resp_json_str = "{}"
        if resp_chunks:
            try:
                resp_json_str = json.dumps(sanitize_payload(json.loads(b"".join(resp_chunks).decode("utf-8"))))
            except Exception:
                pass

        ms = int((time.perf_counter() - t0) * 1000)
        self.db.execute(
            "INSERT INTO request_log(ts, method, path, acting_user, actor, status, latency_ms, request_json, response_json, case_hint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (utc_now_iso(), method, path, acting_user, actor, resp_status, ms, req_json_str, resp_json_str, case_hint),
        )


def make_mock_app(
    name: str,
    db: MockServiceDB,
    get_domain_rows: Callable[[int], list[dict[str, Any]]],
    shift_time_fn: Callable[[float], None] | None = None,
) -> tuple[FastAPI, SimController]:
    app = FastAPI(title=f"Saathi Mock {name.upper()}")
    sim = SimController(name)
    app.add_middleware(PureASGISimMiddleware, db=db, sim=sim)

    @app.post("/_sim/fail-next")
    async def sim_fail_next(payload: dict[str, Any]):
        mode = payload.get("mode", "timeout")
        count = int(payload.get("count", 1))
        method = payload.get("method")
        if count > 0:
            sim.fail_rules.append({"mode": mode, "count": count, "method": method})
        return {"ok": True, "pending_failures": sim.pending_failures_count()}

    @app.post("/_sim/phantom")
    async def sim_phantom(payload: dict[str, Any]):
        count = int(payload.get("count", 1))
        method = payload.get("method", "POST")
        path_prefix = payload.get("path_prefix")
        if count > 0:
            sim.phantom_rules.append({"count": count, "method": method, "path_prefix": path_prefix})
        return {"ok": True, "pending_phantoms": sim.pending_phantoms_count()}

    @app.post("/_sim/stuck")
    async def sim_stuck(payload: dict[str, Any]):
        if payload.get("refund_id"):
            sim.stuck_refund_ids.add(str(payload["refund_id"]))
        if payload.get("txn_id"):
            sim.stuck_txn_ids.add(str(payload["txn_id"]))
        return {
            "ok": True,
            "stuck_refund_ids": list(sim.stuck_refund_ids),
            "stuck_txn_ids": list(sim.stuck_txn_ids),
        }

    @app.post("/_sim/shift-time")
    async def sim_shift_time(payload: dict[str, Any]):
        hours = float(payload.get("hours", 0))
        if shift_time_fn and hours:
            shift_time_fn(hours)
        return {"ok": True, "shifted_hours": hours}

    @app.post("/_sim/config")
    async def sim_config(payload: dict[str, Any]):
        if "latency_min_ms" in payload:
            sim.latency_min_ms = max(0, int(payload["latency_min_ms"]))
        if "latency_max_ms" in payload:
            sim.latency_max_ms = max(sim.latency_min_ms, int(payload["latency_max_ms"]))
        return {"ok": True, "latency_min_ms": sim.latency_min_ms, "latency_max_ms": sim.latency_max_ms}

    @app.get("/_sim/rows")
    async def sim_rows(limit: int = 8):
        return get_domain_rows(limit)

    @app.get("/_sim/state")
    async def sim_state():
        pending = sim.pending_failures_count()
        phantoms = sim.pending_phantoms_count()
        last_reqs = db.query_all(
            "SELECT id, ts, method, path, acting_user, actor, status, latency_ms, case_hint FROM request_log ORDER BY id DESC LIMIT 8"
        )
        return {
            "service": name,
            "health": "degraded" if (pending > 0 or phantoms > 0) else "healthy",
            "pending_failures": pending,
            "pending_phantoms": phantoms,
            "latency_min_ms": sim.latency_min_ms,
            "latency_max_ms": sim.latency_max_ms,
            "last_requests": last_reqs,
            "last_request": last_reqs[0] if last_reqs else None,
            "rows": get_domain_rows(8),
        }

    return app, sim
