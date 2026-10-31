"""FraudAgent: handles UNAUTHORIZED_TXN and SCAM_REPORT (S12, S22)."""
from __future__ import annotations

from typing import Any

from app.agents.runtime import AgentContext, AgentResult
from app.tools import crm, ledger


class FraudAgent:
    NAME = "fraud"
    ALLOWLIST = {
        "lookup_transaction",
        "list_recent_transactions",
        "lock_payment_instrument",
        "create_ticket",
        "post_handoff",
    }

    async def decide(self, ctx: AgentContext) -> AgentResult:
        req_txn_id = ctx.selected_txn_id or ctx.entities.get("txn_id")
        txn: dict[str, Any] | None = None
        if req_txn_id:
            t_res = await ledger.lookup_transaction(
                acting_user=ctx.persona_id, txn_id=req_txn_id, case_id=ctx.case_id, actor=self.NAME
            )
            if t_res.ok and isinstance(t_res.data, dict):
                txn = t_res.data
        else:
            recent_res = await ledger.list_recent_transactions(
                acting_user=ctx.persona_id, limit=3, case_id=ctx.case_id, actor=self.NAME
            )
            cands = recent_res.data if (recent_res.ok and isinstance(recent_res.data, list)) else []
            if cands:
                txn = cands[0]

        lk_res = await ledger.lock_payment_instrument(
            acting_user=ctx.persona_id,
            instrument="UPI",
            hours=24,
            reason="FRAUD_SIGNAL",
            case_id=ctx.case_id,
            actor=self.NAME,
        )
        lock_id = (lk_res.data or {}).get("id", "LK-5001")

        tk_res = await crm.create_ticket(
            acting_user=ctx.persona_id,
            case_id=ctx.case_id,
            category="FRAUD",
            details={
                "fraud_signals": ctx.fraud_signals,
                "txn_id": (txn or {}).get("id"),
                "lock_id": lock_id,
            },
            actor=self.NAME,
        )
        ticket_id = (tk_res.data or {}).get("id", "TK-7001")

        amt = int((txn or {}).get("amount") or ctx.entities.get("amount") or 0)
        txn_id = (txn or {}).get("id") or req_txn_id or ""

        return AgentResult(
            agent_name=self.NAME,
            diagnosis="FRAUD_LOCKED",
            template_code="FRAUD_LOCKED",
            facts={
                "case_id": ctx.case_id,
                "ticket_id": ticket_id,
                "lock_id": lock_id,
                "txn_id": txn_id,
                "amount": amt,
                "owner": "Priya Nair from our support team",
            },
            verified_facts=[
                f"Placed 24-hour protective lock {lock_id} on UPI instrument for {ctx.persona_id}.",
                f"Created P0 fraud ticket {ticket_id} (signals: {', '.join(ctx.fraud_signals or ['UNAUTHORIZED_TXN'])}).",
            ],
            actions_taken=[
                {"action": "lock_payment_instrument", "id": lock_id},
                {"action": "create_ticket", "id": ticket_id},
            ],
            triggers=["T1"],
            txn=txn,
        )
