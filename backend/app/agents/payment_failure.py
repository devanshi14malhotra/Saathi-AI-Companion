"""PaymentFailureAgent: handles PAYMENT_FAILED_DEBITED, PAYMENT_PENDING, and DOUBLE_DEBIT."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.agents.runtime import AgentContext, AgentResult, format_date_short
from app.core.policy import ProposedAction
from app.mocks.ledger.db import ledger_db
from app.tools import ledger, notify, refunds


class PaymentFailureAgent:
    NAME = "payment_failure"
    ALLOWLIST = {
        "lookup_transaction",
        "search_transactions_by_amount",
        "list_recent_transactions",
        "get_bank_status",
        "get_refund_for_txn",
        "check_refund_eligibility",
        "initiate_refund",
        "schedule_followup",
    }

    async def decide(self, ctx: AgentContext) -> AgentResult:
        req_txn_id = ctx.selected_txn_id or ctx.entities.get("txn_id")
        req_amount = ctx.entities.get("amount")
        cp_hint = ctx.entities.get("counterparty_hint")

        # 1. Handle DOUBLE_DEBIT (e.g. S4)
        if ctx.intent == "DOUBLE_DEBIT":
            all_res = await ledger.list_recent_transactions(
                acting_user=ctx.persona_id, limit=20, case_id=ctx.case_id, actor=self.NAME
            )
            txns = all_res.data if (all_res.ok and isinstance(all_res.data, list)) else []
            if req_amount:
                txns = [t for t in txns if int(t.get("amount", 0)) == int(req_amount)]
            if cp_hint:
                cp_filtered = [t for t in txns if cp_hint.lower() in str(t.get("counterparty", "")).lower()]
                if cp_filtered:
                    txns = cp_filtered

            succ_txns = [t for t in txns if t.get("status") == "SUCCESS"]
            fail_txns = [t for t in txns if t.get("status") == "FAILED" and t.get("debit_status") == "DEBITED"]

            if succ_txns and fail_txns:
                failed_t = fail_txns[0]
                succ_t = succ_txns[0]
                try:
                    dt1 = datetime.fromisoformat(failed_t["created_at"])
                    dt2 = datetime.fromisoformat(succ_t["created_at"])
                    diff_min = abs((dt1 - dt2).total_seconds()) / 60.0
                except Exception:
                    diff_min = 3.0

                if diff_min <= 10.0:
                    el_res = await refunds.check_refund_eligibility(
                        acting_user=ctx.persona_id, txn_id=failed_t["id"], case_id=ctx.case_id, actor=self.NAME
                    )
                    rf_res = await refunds.get_refund_for_txn(
                        acting_user=ctx.persona_id, txn_id=failed_t["id"], case_id=ctx.case_id, actor=self.NAME
                    )
                    existing_rfs = rf_res.data if (rf_res.ok and isinstance(rf_res.data, list)) else []
                    eligible = bool((el_res.data or {}).get("eligible", True))
                    amt = int(failed_t["amount"])
                    return AgentResult(
                        agent_name=self.NAME,
                        diagnosis="DUPLICATE_DEBIT",
                        template_code="DUPLICATE_REFUND",
                        facts={
                            "case_id": ctx.case_id,
                            "txn_id": failed_t["id"],
                            "orig_txn_id": succ_t["id"],
                            "amount": amt,
                            "counterparty": failed_t["counterparty"],
                            "sla_hours": 72,
                            "eta": "72 hours",
                        },
                        verified_facts=[
                            f"Found {succ_t['id']} (SUCCESS) and duplicate {failed_t['id']} (FAILED, DEBITED) for ₹{amt} at {failed_t['counterparty']} within {diff_min:.1f} min.",
                            f"Refund eligibility for {failed_t['id']}: {eligible}.",
                        ],
                        proposed_action=ProposedAction(
                            name="initiate_refund",
                            args={"txn_id": failed_t["id"], "amount": amt},
                            is_money=True,
                            amount=amt,
                            target_txn=failed_t["id"],
                            target_user=failed_t["user_id"],
                        ),
                        txn=failed_t,
                        debit_matches_bank=True,
                        eligibility_consistent=eligible,
                        refund_state_consistent=(len(existing_rfs) == 0),
                    )

        # 2. Resolve single transaction
        txn: dict[str, Any] | None = None
        if req_txn_id:
            t_res = await ledger.lookup_transaction(
                acting_user=ctx.persona_id, txn_id=req_txn_id, case_id=ctx.case_id, actor=self.NAME
            )
            if t_res.ok and isinstance(t_res.data, dict):
                txn = t_res.data
            else:
                # Check if this transaction ID belongs to a different user (Rule 1 cross-user check, S14)
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
            candidates = s_res.data if (s_res.ok and isinstance(s_res.data, list)) else []
            if cp_hint and len(candidates) > 1:
                cp_m = [c for c in candidates if cp_hint.lower() in str(c.get("counterparty", "")).lower()]
                if cp_m:
                    candidates = cp_m
            if len(candidates) == 1:
                txn = candidates[0]
            elif len(candidates) > 1:
                if not ctx.clarification_used:
                    return AgentResult(
                        agent_name=self.NAME,
                        diagnosis="CLARIFY_TXN",
                        template_code="CLARIFY_TXN",
                        facts={"case_id": ctx.case_id},
                        needs_clarification=True,
                        clarify_candidates=candidates[:3],
                    )
                return AgentResult(
                    agent_name=self.NAME,
                    diagnosis="AMBIGUOUS_TXN",
                    template_code="ESCALATED",
                    facts={"case_id": ctx.case_id, "owner": "Our team"},
                    triggers=["T7"],
                )

        if not txn:
            recent_res = await ledger.list_recent_transactions(
                acting_user=ctx.persona_id, limit=5, case_id=ctx.case_id, actor=self.NAME
            )
            recent_list = recent_res.data if (recent_res.ok and isinstance(recent_res.data, list)) else []
            if cp_hint:
                cp_m = [c for c in recent_list if cp_hint.lower() in str(c.get("counterparty", "")).lower()]
                if len(cp_m) == 1:
                    txn = cp_m[0]

            if not txn:
                if not ctx.clarification_used and recent_list:
                    return AgentResult(
                        agent_name=self.NAME,
                        diagnosis="CLARIFY_TXN",
                        template_code="CLARIFY_TXN",
                        facts={"case_id": ctx.case_id},
                        needs_clarification=True,
                        clarify_candidates=recent_list[:3],
                    )
                return AgentResult(
                    agent_name=self.NAME,
                    diagnosis="AMBIGUOUS_TXN",
                    template_code="ESCALATED",
                    facts={"case_id": ctx.case_id, "owner": "Our team"},
                    triggers=["T7"],
                )

        # 3. Verify bank status and check for evidence conflict (T3, e.g. S7)
        txn_id = txn["id"]
        amt = int(txn["amount"])
        cp = txn.get("counterparty", "Merchant")
        status = txn.get("status", "FAILED")
        debit_status = txn.get("debit_status", "DEBITED")
        credit_to_merchant = int(txn.get("credit_to_merchant", 0))

        b_res = await ledger.get_bank_status(
            acting_user=ctx.persona_id, txn_id=txn_id, case_id=ctx.case_id, actor=self.NAME
        )
        bank_debit = (b_res.data or {}).get("bank_debit_status", debit_status) if b_res.ok else debit_status

        if debit_status != bank_debit:
            # Re-check once per SPEC §8.5 / T3
            b_res2 = await ledger.get_bank_status(
                acting_user=ctx.persona_id, txn_id=txn_id, case_id=ctx.case_id, actor=self.NAME
            )
            bank_debit = (b_res2.data or {}).get("bank_debit_status", debit_status) if b_res2.ok else debit_status
            if debit_status != bank_debit:
                return AgentResult(
                    agent_name=self.NAME,
                    diagnosis="EVIDENCE_CONFLICT",
                    template_code="ESCALATED",
                    facts={
                        "case_id": ctx.case_id,
                        "txn_id": txn_id,
                        "amount": amt,
                        "counterparty": cp,
                        "owner": "Our team",
                    },
                    verified_facts=[
                        f"Ledger shows debit_status={debit_status} for {txn_id} (₹{amt}), but bank gateway reports bank_debit_status={bank_debit} after re-check."
                    ],
                    triggers=["T3"],
                    txn=txn,
                    debit_matches_bank=False,
                )

        # 4. Transaction succeeded & merchant credited (S2)
        if status == "SUCCESS" and credit_to_merchant == 1:
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="TXN_SUCCEEDED",
                template_code="TXN_SUCCEEDED",
                facts={
                    "case_id": ctx.case_id,
                    "txn_id": txn_id,
                    "amount": amt,
                    "counterparty": cp,
                },
                verified_facts=[
                    f"Transaction {txn_id} for ₹{amt} to {cp} succeeded and merchant was credited."
                ],
                txn=txn,
                debit_matches_bank=True,
            )

        # 5. Failed with no bank debit (S20)
        if debit_status == "NOT_DEBITED" and bank_debit == "NOT_DEBITED":
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="NO_DEBIT",
                template_code="NO_DEBIT",
                facts={
                    "case_id": ctx.case_id,
                    "txn_id": txn_id,
                    "amount": amt,
                    "counterparty": cp,
                },
                verified_facts=[
                    f"Transaction {txn_id} (₹{amt} to {cp}) failed with no bank debit."
                ],
                txn=txn,
                debit_matches_bank=True,
            )

        # 6. Pending with scheduled auto-reversal (S3)
        if status == "PENDING" or txn.get("reversal_status") == "SCHEDULED":
            flw_res = await notify.schedule_followup(
                acting_user=ctx.persona_id,
                case_id=ctx.case_id,
                run_in_minutes=360,
                check_kind="REVERSAL_COMPLETED",
                actor=self.NAME,
            )
            eta_str = format_date_short(txn.get("reversal_eta"))
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="REVERSAL_PENDING",
                template_code="REVERSAL_PENDING",
                facts={
                    "case_id": ctx.case_id,
                    "txn_id": txn_id,
                    "amount": amt,
                    "counterparty": cp,
                    "sla_hours": 24,
                    "eta": eta_str,
                },
                verified_facts=[
                    f"Transaction {txn_id} (₹{amt} to {cp}) is PENDING with bank auto-reversal scheduled by {eta_str}."
                ],
                actions_taken=[
                    {"action": "schedule_followup", "id": (flw_res.data or {}).get("id", "FLW-1")}
                ],
                txn=txn,
                debit_matches_bank=True,
            )

        # 7. Failed after debit, merchant not credited -> check eligibility & existing refund
        el_res = await refunds.check_refund_eligibility(
            acting_user=ctx.persona_id, txn_id=txn_id, case_id=ctx.case_id, actor=self.NAME
        )
        rf_res = await refunds.get_refund_for_txn(
            acting_user=ctx.persona_id, txn_id=txn_id, case_id=ctx.case_id, actor=self.NAME
        )
        existing_rfs = rf_res.data if (rf_res.ok and isinstance(rf_res.data, list)) else []
        eligible = bool((el_res.data or {}).get("eligible", True))

        if existing_rfs:
            rf = existing_rfs[0]
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="REFUND_ETA",
                template_code="REFUND_ETA",
                facts={
                    "case_id": ctx.case_id,
                    "txn_id": txn_id,
                    "refund_id": rf["id"],
                    "amount": amt,
                    "counterparty": cp,
                    "sla_hours": 72,
                    "eta": format_date_short(rf.get("eta")),
                },
                verified_facts=[
                    f"Refund {rf['id']} for {txn_id} (₹{amt}) is already {rf['status']}."
                ],
                txn=txn,
                refund=rf,
                debit_matches_bank=True,
                eligibility_consistent=eligible,
                refund_state_consistent=True,
            )

        return AgentResult(
            agent_name=self.NAME,
            diagnosis="REFUND_DUE",
            template_code="REFUND_INITIATED",
            facts={
                "case_id": ctx.case_id,
                "txn_id": txn_id,
                "amount": amt,
                "counterparty": cp,
                "sla_hours": 72,
                "eta": "72 hours",
            },
            verified_facts=[
                f"Transaction {txn_id} (₹{amt} to {cp}) failed after bank debit; merchant was not credited.",
                f"Refund eligibility verified: {eligible}.",
            ],
            proposed_action=ProposedAction(
                name="initiate_refund",
                args={"txn_id": txn_id, "amount": amt},
                is_money=True,
                amount=amt,
                target_txn=txn_id,
                target_user=txn["user_id"],
            ),
            txn=txn,
            debit_matches_bank=True,
            eligibility_consistent=eligible,
            refund_state_consistent=True,
        )
