import asyncio
import json
from typing import Any

from app.db.core import execute, query_all, utc_now_iso

_SECRET_PATTERNS = ("sk_", "Bearer ", "api-subscription-key")


def sanitize_payload(obj: Any) -> Any:
    """Ensure no credentials or raw secret strings leak into persisted events."""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if k.lower() in ("authorization", "api-subscription-key", "secret", "password"):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = sanitize_payload(v)
        return cleaned
    if isinstance(obj, list):
        return [sanitize_payload(item) for item in obj]
    if isinstance(obj, str):
        for pat in _SECRET_PATTERNS:
            if pat in obj:
                return "[REDACTED]"
        return obj
    return obj


class EventBus:
    def __init__(self) -> None:
        self._customer_queues: dict[str, set[asyncio.Queue]] = {}
        self._console_queues: set[asyncio.Queue] = set()

    def reset(self) -> None:
        pass

    def subscribe_customer(self, persona_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._customer_queues.setdefault(persona_id, set()).add(q)
        return q

    def unsubscribe_customer(self, persona_id: str, q: asyncio.Queue) -> None:
        if persona_id in self._customer_queues:
            self._customer_queues[persona_id].discard(q)

    def subscribe_console(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._console_queues.add(q)
        return q

    def unsubscribe_console(self, q: asyncio.Queue) -> None:
        self._console_queues.discard(q)

    def publish_customer(
        self,
        persona_id: str,
        kind: str,
        payload: dict[str, Any],
        case_id: str | None = None,
        role: str = "saathi",
        persist: bool = True,
    ) -> int | None:
        clean_payload = sanitize_payload(payload)
        ts = utc_now_iso()
        msg_id: int | None = None
        if persist and kind != "status":
            msg_id = execute(
                "INSERT INTO messages(persona_id, case_id, role, kind, body_json, ts) VALUES (?, ?, ?, ?, ?, ?)",
                (persona_id, case_id or clean_payload.get("case_id"), role, kind, json.dumps(clean_payload), ts),
            )
        event_item = {
            "id": msg_id,
            "event": kind,
            "data": {**clean_payload, "id": msg_id, "kind": kind, "role": role, "ts": ts},
        }
        for q in list(self._customer_queues.get(persona_id, set())):
            try:
                q.put_nowait(event_item)
            except Exception:
                pass
        return msg_id

    def publish_console(self, event_name: str, payload: dict[str, Any], persona_id: str = "ALL") -> int:
        clean_payload = sanitize_payload(payload)
        ts = utc_now_iso()
        evt_id = execute(
            "INSERT INTO console_events(persona_id, event, payload_json, ts) VALUES (?, ?, ?, ?)",
            (persona_id, event_name, json.dumps(clean_payload), ts),
        )
        event_item = {
            "id": evt_id,
            "event": event_name,
            "data": clean_payload,
            "ts": ts,
        }
        for q in list(self._console_queues):
            try:
                q.put_nowait(event_item)
            except Exception:
                pass
        return evt_id

    def publish_system_change(self, service: str, table: str, row_id: str, case_hint: str | None = None) -> int:
        return self.publish_console(
            "system_row_changed",
            {
                "service": service,
                "table": table,
                "row_id": row_id,
                "case_id": case_hint,
            },
        )

    def get_customer_replay(self, persona_id: str, last_event_id: int) -> list[dict[str, Any]]:
        rows = query_all(
            "SELECT id, persona_id, case_id, role, kind, body_json, ts FROM messages WHERE persona_id = ? AND id > ? ORDER BY id ASC",
            (persona_id, last_event_id),
        )
        out = []
        for r in rows:
            body = json.loads(r["body_json"]) if r["body_json"] else {}
            out.append(
                {
                    "id": r["id"],
                    "event": r["kind"],
                    "data": {**body, "id": r["id"], "kind": r["kind"], "role": r["role"], "ts": r["ts"]},
                }
            )
        return out

    def get_console_replay(self, last_event_id: int) -> list[dict[str, Any]]:
        rows = query_all(
            "SELECT id, persona_id, event, payload_json, ts FROM console_events WHERE id > ? ORDER BY id ASC",
            (last_event_id,),
        )
        out = []
        for r in rows:
            payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
            out.append(
                {
                    "id": r["id"],
                    "event": r["event"],
                    "data": payload,
                    "ts": r["ts"],
                }
            )
        return out


bus = EventBus()

