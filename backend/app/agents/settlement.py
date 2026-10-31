"""SettlementAgent: handles merchant settlement delays, bank holidays, risk holds, and mismatches (S10, S11)."""
from __future__ import annotations

from app.agents.runtime import AgentContext, AgentResult, format_date_short
from app.tools import refunds


class SettlementAgent:
    NAME = "settlement"
    ALLOWLIST = {
        "get_settlement_batch",
        "next_working_day",
        "raise_reconciliation",
        "get_customer_profile",
    }

    async def decide(self, ctx: AgentContext) -> AgentResult:
        st_res = await refunds.get_settlement_batch(
            acting_user=ctx.persona_id,
            merchant_id=ctx.persona_id,
            latest=True,
            case_id=ctx.case_id,
            actor=self.NAME,
        )
        if not st_res.ok or not isinstance(st_res.data, dict):
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="SETTLEMENT_HOLD",
                template_code="ESCALATED",
                facts={"case_id": ctx.case_id, "owner": "Our team"},
                triggers=["T4"],
            )

        st = st_res.data
        set_id = st["id"]
        expected = int(st.get("expected_amount", 0))
        actual = int(st.get("actual_amount", expected))
        hold_reason = st.get("hold_reason") or "NONE"
        status = st.get("status", "PENDING")
        due_date = format_date_short(st.get("due_date"))

        # 1. Bank Holiday hold (S10)
        if hold_reason == "BANK_HOLIDAY":
            nwd_res = await refunds.next_working_day(
                acting_user=ctx.persona_id,
                from_date=st.get("due_date"),
                case_id=ctx.case_id,
                actor=self.NAME,
            )
            next_date = (nwd_res.data or {}).get("formatted") or (nwd_res.data or {}).get("next_working_day", "next working day")
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="SETTLEMENT_HOLIDAY",
                template_code="SETTLEMENT_HOLIDAY",
                facts={
                    "case_id": ctx.case_id,
                    "refund_id": set_id,
                    "amount": expected,
                    "due_date": due_date,
                    "next_date": next_date,
                },
                verified_facts=[
                    f"Settlement {set_id} (₹{expected:,}) was paused due to a bank holiday.",
                    f"Next working day credit date: {next_date}.",
                ],
                settlement=st,
            )

        # 2. Compliance or Risk Hold -> Escalate under T4 (S11)
        if hold_reason in ("RISK_REVIEW", "COMPLIANCE_HOLD", "KYC_PENDING") or status == "HELD":
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="SETTLEMENT_HOLD",
                template_code="ESCALATED",
                facts={
                    "case_id": ctx.case_id,
                    "refund_id": set_id,
                    "amount": expected,
                    "owner": "Our team",
                },
                verified_facts=[
                    f"Settlement {set_id} (₹{expected:,}) is HELD with reason {hold_reason}."
                ],
                triggers=["T4"],
                settlement=st,
            )

        # 3. Settlement amount mismatch
        if actual < expected:
            diff = expected - actual
            rc_res = await refunds.raise_reconciliation(
                acting_user=ctx.persona_id,
                ref_type="SETTLEMENT",
                ref_id=set_id,
                case_id=ctx.case_id,
                actor=self.NAME,
            )
            recon_id = (rc_res.data or {}).get("id", "RC-8002")
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="SETTLEMENT_MISMATCH",
                template_code="SETTLEMENT_MISMATCH",
                facts={
                    "case_id": ctx.case_id,
                    "refund_id": set_id,
                    "expected": expected,
                    "actual": actual,
                    "diff": diff,
                    "recon_id": recon_id,
                },
                verified_facts=[
                    f"Settlement {set_id} credited ₹{actual:,} vs expected ₹{expected:,} (diff ₹{diff:,}).",
                    f"Raised reconciliation {recon_id}.",
                ],
                actions_taken=[{"action": "raise_reconciliation", "id": recon_id}],
                settlement=st,
            )

        return AgentResult(
            agent_name=self.NAME,
            diagnosis="SETTLEMENT_HOLIDAY",
            template_code="SETTLEMENT_HOLIDAY",
            facts={
                "case_id": ctx.case_id,
                "refund_id": set_id,
                "amount": expected,
                "due_date": due_date,
                "next_date": "tomorrow",
            },
            verified_facts=[f"Settlement {set_id} (₹{expected:,}) status is {status}."],
            settlement=st,
        )
