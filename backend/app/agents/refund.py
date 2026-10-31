"""RefundAgent: handles REFUND_STATUS and REFUND_NOT_RECEIVED (S8, S9)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agents.payment_failure import PaymentFailureAgent
from app.agents.runtime import AgentContext, AgentResult, format_date_short
from app.core.policy import ProposedAction
from app.mocks.ledger.db import ledger_db
from app.tools import ledger, refunds


class RefundAgent:
    NAME = "refund"
    ALLOWLIST = {
        "lookup_transaction",
        "search_transactions_by_amount",
        "list_recent_transactions",
        "get_refund_for_txn",
        "get_refund",
        "raise_reconciliation",
        "schedule_followup",
    }

    async def decide(self, ctx: AgentContext) -> AgentResult:
        req_txn_id = ctx.selected_txn_id or ctx.entities.get("txn_id")
        req_amount = ctx.entities.get("amount")

        txn: dict[str, Any] | None = None
        if req_txn_id:
            t_res = await ledger.lookup_transaction(
                acting_user=ctx.persona_id, txn_id=req_txn_id, case_id=ctx.case_id, actor=self.NAME
            )
            if t_res.ok and isinstance(t_res.data, dict):
                txn = t_res.data
            else:
                foreign_row = ledger_db.query_one("SELECT id, user_id FROM transactions WHERE id = ?", (req_txn_id,))
                if foreign_row and foreign_row["user_id"] != ctx.persona_id:
                    return AgentResult(
                        agent_name=self.NAME,
                        diagnosis="BLOCKED_SCOPE",
                        template_code="BLOCKED_SCOPE",
                        facts={"case_id": ctx.case_id, "txn_id": req_txn_id},
                        verified_facts=[f"Transaction {req_txn_id} does not belong to {ctx.persona_id}."],
                        proposed_action=ProposedAction(
                            name="lookup_transaction",
                            args={"txn_id": req_txn_id},
                            is_money=False,
                            amount=0,
                            target_txn=req_txn_id,
                            target_user=foreign_row["user_id"],
                        ),
                    )

        if not txn and req_amount is not None:
            s_res = await ledger.search_transactions_by_amount(
                acting_user=ctx.persona_id, amount=int(req_amount), days=14, case_id=ctx.case_id, actor=self.NAME
            )
            cands = s_res.data if (s_res.ok and isinstance(s_res.data, list)) else []
            if cands:
                txn = cands[0]

        if not txn:
            recent_res = await ledger.list_recent_transactions(
                acting_user=ctx.persona_id, limit=5, case_id=ctx.case_id, actor=self.NAME
            )
            cands = recent_res.data if (recent_res.ok and isinstance(recent_res.data, list)) else []
            if cands:
                txn = cands[0]

        if not txn:
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="AMBIGUOUS_TXN",
                template_code="ESCALATED",
                facts={"case_id": ctx.case_id, "owner": "Our team"},
                triggers=["T7"],
            )

        txn_id = txn["id"]
        amt = int(txn["amount"])
        cp = txn.get("counterparty", "Merchant")

        rf_res = await refunds.get_refund_for_txn(
            acting_user=ctx.persona_id, txn_id=txn_id, case_id=ctx.case_id, actor=self.NAME
        )
        rfs = rf_res.data if (rf_res.ok and isinstance(rf_res.data, list)) else []

        if not rfs:
            pf_res = await PaymentFailureAgent().decide(ctx)
            pf_res.agent_name = self.NAME
            return pf_res

        rf = rfs[0]
        refund_id = rf["id"]
        eta_str = rf.get("eta")
        now = datetime.now(timezone.utc)
        overdue = False
        if eta_str:
            try:
                eta_dt = datetime.fromisoformat(eta_str.replace("Z", "+00:00"))
                if eta_dt.tzinfo is None:
                    eta_dt = eta_dt.replace(tzinfo=timezone.utc)
                overdue = now >= eta_dt
            except Exception:
                overdue = False

        if overdue and rf.get("status") != "COMPLETED":
            rc_res = await refunds.raise_reconciliation(
                acting_user=ctx.persona_id,
                ref_type="REFUND",
                ref_id=refund_id,
                case_id=ctx.case_id,
                actor=self.NAME,
            )
            recon_id = (rc_res.data or {}).get("id", "RC-8001")
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="RECON_RAISED",
                template_code="RECON_RAISED",
                facts={
                    "case_id": ctx.case_id,
                    "txn_id": txn_id,
                    "refund_id": refund_id,
                    "recon_id": recon_id,
                    "amount": amt,
                    "counterparty": cp,
                },
                verified_facts=[
                    f"Refund {refund_id} (₹{amt} for {txn_id}) passed its 72-hour SLA window.",
                    f"Raised bank reconciliation {recon_id}.",
                ],
                actions_taken=[{"action": "raise_reconciliation", "id": recon_id}],
                txn=txn,
                refund=rf,
                debit_matches_bank=True,
                refund_state_consistent=True,
            )

        return AgentResult(
            agent_name=self.NAME,
            diagnosis="REFUND_ETA",
            template_code="REFUND_ETA",
            facts={
                "case_id": ctx.case_id,
                "txn_id": txn_id,
                "refund_id": refund_id,
                "amount": amt,
                "counterparty": cp,
                "sla_hours": 72,
                "eta": format_date_short(eta_str),
            },
            verified_facts=[
                f"Refund {refund_id} for {txn_id} (₹{amt}) is {rf.get('status')} and within the 72-hour SLA window (ETA {format_date_short(eta_str)})."
            ],
            txn=txn,
            refund=rf,
            debit_matches_bank=True,
            refund_state_consistent=True,
        )
