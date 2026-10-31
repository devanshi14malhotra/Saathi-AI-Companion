"""FallbackAgent: handles HUMAN_REQUEST (S19) and OTHER / low-confidence intents."""
from __future__ import annotations

from app.agents.runtime import AgentContext, AgentResult


class FallbackAgent:
    NAME = "fallback"
    ALLOWLIST = {
        "search_kb",
        "create_ticket",
        "post_handoff",
    }

    async def decide(self, ctx: AgentContext) -> AgentResult:
        if ctx.intent == "HUMAN_REQUEST" or ctx.mentions_human_request:
            return AgentResult(
                agent_name=self.NAME,
                diagnosis="HUMAN_REQUEST",
                template_code="HUMAN_ACK",
                facts={
                    "case_id": ctx.case_id,
                    "owner": "Priya Nair from our support team",
                },
                verified_facts=["Customer explicitly requested a human support specialist."],
                triggers=["T2"],
            )

        return AgentResult(
            agent_name=self.NAME,
            diagnosis="OUT_OF_SCOPE",
            template_code="OUT_OF_SCOPE",
            facts={
                "case_id": ctx.case_id,
                "owner": "Our team",
            },
            verified_facts=["Request did not match a supported payment, refund, settlement, or app issue."],
        )
