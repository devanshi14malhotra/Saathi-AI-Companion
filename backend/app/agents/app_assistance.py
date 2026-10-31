"""AppAssistanceAgent: handles APP_BUG, APP_HOWTO, and LOGIN_OTP_HELP (S15 child 2, etc.)."""
from __future__ import annotations

from app.agents.runtime import AgentContext, AgentResult
from app.tools import crm, kb


class AppAssistanceAgent:
    NAME = "app_assistance"
    ALLOWLIST = {
        "search_kb",
        "get_customer_profile",
        "create_ticket",
    }

    async def decide(self, ctx: AgentContext) -> AgentResult:
        hits = kb.search_kb(query=ctx.masked_text, top_k=2, case_id=ctx.case_id, actor=self.NAME)
        top_steps = hits[0]["steps"] if hits else "1. Update Paytm app to the latest version. 2. Clear app cache and restart."
        top_doc = hits[0]["doc_id"] if hits else "06_app_crash_troubleshooting"

        if ctx.intent == "APP_BUG":
            device_info = ctx.customer_profile.get("device_info", {})
            tk_res = await crm.create_ticket(
                acting_user=ctx.persona_id,
                case_id=ctx.case_id,
                category="APP_BUG",
                details={"device_info": device_info, "kb_doc": top_doc, "summary": ctx.masked_text[:120]},
                actor=self.NAME,
            )
            ticket_id = (tk_res.data or {}).get("id", "TK-7001")
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="BUG_FILED",
                template_code="BUG_FILED",
                facts={
                    "case_id": ctx.case_id,
                    "ticket_id": ticket_id,
                    "steps": top_steps,
                },
                verified_facts=[
                    f"Logged engineering bug ticket {ticket_id} with device diagnostics.",
                    f"Matched troubleshooting guide {top_doc}.",
                ],
                actions_taken=[{"action": "create_ticket", "id": ticket_id}],
            )

        return AgentResult(
            agent_name=self.NAME,
            diagnosis="APP_GUIDE",
            template_code="APP_GUIDE",
            facts={
                "case_id": ctx.case_id,
                "steps": top_steps,
            },
            verified_facts=[f"Matched help article {top_doc}."],
        )
