"""Shared runtime types and helpers for Saathi v6.0 specialist agents."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.policy import ProposedAction


def format_date_short(iso_str: str | None) -> str:
    if not iso_str:
        return "72 hours"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d %b %H:%M UTC")
    except Exception:
        return str(iso_str)[:16]


def compute_age_hours(iso_str: str | None) -> float:
    if not iso_str:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0.0, (now - dt).total_seconds() / 3600.0)
    except Exception:
        return 0.0


@dataclass
class AgentContext:
    case_id: str
    persona_id: str
    masked_text: str
    language: str
    intent: str
    intent_confidence: float
    entities: dict[str, Any]
    sentiment: str = "calm"
    mentions_human_request: bool = False
    fraud_signals: list[str] = field(default_factory=list)
    clarification_used: bool = False
    selected_txn_id: str | None = None
    customer_profile: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    agent_name: str
    diagnosis: str
    template_code: str
    facts: dict[str, Any] = field(default_factory=dict)
    verified_facts: list[str] = field(default_factory=list)
    actions_taken: list[dict[str, str]] = field(default_factory=list)
    proposed_action: ProposedAction | None = None
    triggers: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    clarify_candidates: list[dict[str, Any]] = field(default_factory=list)
    txn: dict[str, Any] | None = None
    refund: dict[str, Any] | None = None
    settlement: dict[str, Any] | None = None
    debit_matches_bank: bool | None = None
    eligibility_consistent: bool | None = None
    refund_state_consistent: bool | None = None
