"""Typed HTTP tool client with ASGITransport, status classification, bounded retry, and audit logging."""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import cfg_mgr, get_ablate_flags, is_eval_env
from app.core.events import bus, sanitize_payload
from app.db.core import execute, query_one, utc_now_iso
from app.mocks.crm.app import crm_app
from app.mocks.ledger.app import ledger_app
from app.mocks.notify.app import notify_app
from app.mocks.refunds.app import refunds_app

SERVICE_APPS = {
    "ledger": ledger_app,
    "refunds": refunds_app,
    "crm": crm_app,
    "notify": notify_app,
}


@dataclass
class ToolOutcome:
    ok: bool
    status: str  # "ok" | "not_found" | "rejected" | "exhausted"
    http_status: int
    data: Any = None
    error: str | None = None
    attempts: int = 1
    latency_ms: int = 0
    idempotency_key: str | None = None


def record_case_event(
    case_id: str | None,
    badge: str,
    evt_type: str,
    summary: str,
    payload: dict[str, Any],
    latency_ms: int = 0,
    status: str = "ok",
) -> int:
    if not case_id:
        return 0
    row = query_one("SELECT COALESCE(MAX(seq), 0) AS max_seq FROM case_events WHERE case_id = ?", (case_id,))
    seq = int(row["max_seq"] if row else 0) + 1
    ts = utc_now_iso()
    clean_payload = sanitize_payload(payload)
    eid = execute(
        """
        INSERT INTO case_events(case_id, seq, ts, badge, type, summary, payload_json, latency_ms, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (case_id, seq, ts, badge, evt_type, summary, json.dumps(clean_payload, default=str), latency_ms, status),
    )
    bus.publish_console(
        "trace_step",
        {
            "id": eid,
            "case_id": case_id,
            "seq": seq,
            "ts": ts,
            "badge": badge,
            "type": evt_type,
            "summary": summary,
            "payload": clean_payload,
            "latency_ms": latency_ms,
            "status": status,
        },
    )
    return eid


def record_audit(
    actor: str,
    action: str,
    params: dict[str, Any],
    result: dict[str, Any],
    idem_key: str | None,
    case_id: str | None,
) -> int:
    return execute(
        """
        INSERT INTO audit_log(ts, actor, action, params_json, result_json, idem_key, case_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            utc_now_iso(),
            actor,
            action,
            json.dumps(sanitize_payload(params), default=str),
            json.dumps(sanitize_payload(result), default=str),
            idem_key or "",
            case_id or "",
        ),
    )


async def call_service(
    *,
    service: str,
    tool_name: str,
    method: str,
    path: str,
    acting_user: str,
    case_id: str | None = None,
    actor: str = "saathi",
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    max_attempts: int = 3,
    emit_trace: bool = True,
) -> ToolOutcome:
    ablate = get_ablate_flags()
    effective_idem = None if ("no_idem" in ablate) else idempotency_key

    headers: dict[str, str] = {
        "X-Acting-User": acting_user,
        "X-Actor": actor,
    }
    if case_id:
        headers["X-Case-Id"] = case_id
    if effective_idem:
        headers["Idempotency-Key"] = effective_idem

    app_instance = SERVICE_APPS[service]
    transport = httpx.ASGITransport(app=app_instance)

    backoffs = [0.01, 0.02] if (is_eval_env() or os.environ.get("SAATHI_FAST_RETRY") == "1") else [0.15, 0.35]
    attempt = 0
    total_latency_ms = 0

    async with httpx.AsyncClient(transport=transport, base_url=f"http://{service}", timeout=5.0) as client:
        while attempt < max_attempts:
            attempt += 1
            t0 = time.perf_counter()
            try:
                resp = await client.request(
                    method=method.upper(),
                    url=path,
                    params=params,
                    json=json_body,
                    headers=headers,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                total_latency_ms += latency_ms
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                total_latency_ms += latency_ms
                is_last = attempt >= max_attempts
                record_audit(
                    actor=actor,
                    action=tool_name,
                    params=json_body or params or {"path": path},
                    result={"outcome": "exhausted" if is_last else "retry", "error": str(exc), "attempt": attempt},
                    idem_key=effective_idem,
                    case_id=case_id,
                )
                if emit_trace and case_id:
                    record_case_event(
                        case_id=case_id,
                        badge="[TOOL]",
                        evt_type="tool_call",
                        summary=f"{tool_name} ({service.upper()}) attempt {attempt} transport error",
                        payload={"tool": tool_name, "service": service, "attempt": attempt, "error": str(exc)},
                        latency_ms=latency_ms,
                        status="error" if is_last else "warn",
                    )
                if is_last:
                    return ToolOutcome(
                        ok=False,
                        status="exhausted",
                        http_status=504,
                        error=str(exc),
                        attempts=attempt,
                        latency_ms=total_latency_ms,
                        idempotency_key=effective_idem,
                    )
                await asyncio.sleep(backoffs[min(attempt - 1, len(backoffs) - 1)])
                continue

            status_code = resp.status_code
            try:
                resp_data = resp.json() if resp.content else {}
            except Exception:
                resp_data = {"raw": resp.text[:300]}

            # 2xx Success
            if 200 <= status_code < 300:
                record_audit(
                    actor=actor,
                    action=tool_name,
                    params=json_body or params or {"path": path},
                    result={"outcome": "success", "http_status": status_code, "body": resp_data, "attempt": attempt},
                    idem_key=effective_idem,
                    case_id=case_id,
                )
                if emit_trace and case_id:
                    record_case_event(
                        case_id=case_id,
                        badge="[TOOL]",
                        evt_type="tool_call",
                        summary=f"{tool_name} ({service.upper()}) → {status_code} OK" + (f" (attempt {attempt})" if attempt > 1 else ""),
                        payload={
                            "tool": tool_name,
                            "service": service,
                            "method": method,
                            "path": path,
                            "attempt": attempt,
                            "http_status": status_code,
                            "response": resp_data,
                        },
                        latency_ms=latency_ms,
                        status="ok",
                    )
                return ToolOutcome(
                    ok=True,
                    status="ok",
                    http_status=status_code,
                    data=resp_data,
                    attempts=attempt,
                    latency_ms=total_latency_ms,
                    idempotency_key=effective_idem,
                )

            # 404 NotFound -> Do NOT retry
            if status_code == 404:
                record_audit(
                    actor=actor,
                    action=tool_name,
                    params=json_body or params or {"path": path},
                    result={"outcome": "not_found", "http_status": 404, "body": resp_data, "attempt": attempt},
                    idem_key=effective_idem,
                    case_id=case_id,
                )
                if emit_trace and case_id:
                    record_case_event(
                        case_id=case_id,
                        badge="[TOOL]",
                        evt_type="tool_call",
                        summary=f"{tool_name} ({service.upper()}) → 404 Not Found",
                        payload={"tool": tool_name, "service": service, "http_status": 404, "response": resp_data},
                        latency_ms=latency_ms,
                        status="warn",
                    )
                return ToolOutcome(
                    ok=False,
                    status="not_found",
                    http_status=404,
                    data=resp_data,
                    error="not_found",
                    attempts=attempt,
                    latency_ms=total_latency_ms,
                    idempotency_key=effective_idem,
                )

            # Other 4xx (except 429) -> ToolRejected, Do NOT retry
            if 400 <= status_code < 500 and status_code != 429:
                err_str = resp_data.get("error", f"http_{status_code}") if isinstance(resp_data, dict) else f"http_{status_code}"
                record_audit(
                    actor=actor,
                    action=tool_name,
                    params=json_body or params or {"path": path},
                    result={"outcome": "rejected", "http_status": status_code, "body": resp_data, "attempt": attempt},
                    idem_key=effective_idem,
                    case_id=case_id,
                )
                if emit_trace and case_id:
                    record_case_event(
                        case_id=case_id,
                        badge="[TOOL]",
                        evt_type="tool_call",
                        summary=f"{tool_name} ({service.upper()}) → {status_code} Rejected ({err_str})",
                        payload={"tool": tool_name, "service": service, "http_status": status_code, "response": resp_data},
                        latency_ms=latency_ms,
                        status="error",
                    )
                return ToolOutcome(
                    ok=False,
                    status="rejected",
                    http_status=status_code,
                    data=resp_data,
                    error=str(err_str),
                    attempts=attempt,
                    latency_ms=total_latency_ms,
                    idempotency_key=effective_idem,
                )

            # 429 or 5xx -> Retryable
            err_str = resp_data.get("error", f"http_{status_code}") if isinstance(resp_data, dict) else f"http_{status_code}"
            is_last = attempt >= max_attempts
            record_audit(
                actor=actor,
                action=tool_name,
                params=json_body or params or {"path": path},
                result={"outcome": "exhausted" if is_last else "retry", "http_status": status_code, "body": resp_data, "attempt": attempt},
                idem_key=effective_idem,
                case_id=case_id,
            )
            if emit_trace and case_id:
                record_case_event(
                    case_id=case_id,
                    badge="[TOOL]",
                    evt_type="tool_call",
                    summary=f"{tool_name} ({service.upper()}) → {status_code} ({'exhausted' if is_last else f'retry {attempt}/{max_attempts}'})",
                    payload={
                        "tool": tool_name,
                        "service": service,
                        "attempt": attempt,
                        "http_status": status_code,
                        "response": resp_data,
                    },
                    latency_ms=latency_ms,
                    status="error" if is_last else "warn",
                )
            if is_last:
                return ToolOutcome(
                    ok=False,
                    status="exhausted",
                    http_status=status_code,
                    data=resp_data,
                    error=str(err_str),
                    attempts=attempt,
                    latency_ms=total_latency_ms,
                    idempotency_key=effective_idem,
                )
            await asyncio.sleep(backoffs[min(attempt - 1, len(backoffs) - 1)])

    return ToolOutcome(
        ok=False,
        status="exhausted",
        http_status=503,
        error="max_attempts_reached",
        attempts=attempt,
        latency_ms=total_latency_ms,
        idempotency_key=effective_idem,
    )
