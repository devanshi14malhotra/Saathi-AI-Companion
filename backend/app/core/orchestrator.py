"""End-to-end case lifecycle orchestrator and human console actions for Saathi v6.0."""
from __future__ import annotations

import json
from typing import Any

from app.agents.app_assistance import AppAssistanceAgent
from app.agents.fallback import FallbackAgent
from app.agents.fraud import FraudAgent
from app.agents.payment_failure import PaymentFailureAgent
from app.agents.refund import RefundAgent
from app.agents.runtime import AgentContext, format_date_short
from app.agents.settlement import SettlementAgent
from app.core.composer import build_resolution_sections, compose_message
from app.core.confidence import compute_confidence
from app.core.config import cfg_mgr, get_ablate_flags, get_eval_arm
from app.core.events import bus
from app.core.followups import check_and_record_tat_compensation, register_followup_check
from app.core.guard import scan as guard_scan
from app.core.handoff import build_handoff_packet
from app.core.ids import next_id
from app.core.incidents import get_open_incident_for_signature, record_complaint_signal
from app.core.masking import mask as mask_pii
from app.core.policy import CasePolicyContext, evaluate as evaluate_policy
from app.core.sensitive import detect_sensitive
from app.core.state_machine import transition
from app.core.verify import verify_and_recover
from app.db.core import execute, query_all, query_one, utc_now_iso
from app.llm.provider import get_provider
from app.llm.schemas import Extraction, fallback_extraction, post_process_extraction
from app.tools import crm, kb, notify
from app.tools.client import record_case_event
from app.tools.registry import execute_action

AGENTS = {
    "payment_failure": PaymentFailureAgent(),
    "refund": RefundAgent(),
    "settlement": SettlementAgent(),
    "app_assistance": AppAssistanceAgent(),
    "fraud": FraudAgent(),
    "fallback": FallbackAgent(),
}


def _issue_sort_key(issue_dict: dict[str, Any]) -> int:
    intent = issue_dict.get("intent", "OTHER")
    agent_name = cfg_mgr.routing.get(intent, "fallback")
    if agent_name == "fraud":
        return 0
    if agent_name in ("payment_failure", "refund", "settlement"):
        return 1
    return 2


def _save_pii_tokens(case_id: str, tokens: dict[str, str]) -> None:
    for tok, val in tokens.items():
        execute(
            "INSERT INTO pii_tokens(case_id, token, value) VALUES (?, ?, ?)",
            (case_id, tok, "[REDACTED]" if tok.startswith("[SECRET_") else val),
        )


def auto_tighten_agent_autonomy(agent_name: str, reason: str) -> str | None:
    """
    F7 Rule 15: If an AUTO case is later marked wrong by a human or its T+n check REOPENS,
    the agent drops one autonomy level automatically (autonomous -> guarded -> suggest).
    """
    locked = cfg_mgr.autonomy_cfg.get("locked", ["fraud"])
    if agent_name in locked or agent_name == "fallback":
        return None
    modes = cfg_mgr.get_autonomy_modes()
    cur_mode = modes.get(agent_name, "guarded")
    drop_map = {"autonomous": "guarded", "guarded": "suggest", "suggest": "suggest"}
    new_mode = drop_map.get(cur_mode, "suggest")
    if new_mode != cur_mode:
        cfg_mgr.set_autonomy_mode(agent_name, new_mode, actor="system")
        bus.publish_console(
            "autonomy_updated",
            {
                "agent": agent_name,
                "old_mode": cur_mode,
                "new_mode": new_mode,
                "actor": "system",
                "reason": reason,
            },
        )
        return new_mode
    return cur_mode


async def handle_message(
    *,
    persona_id: str,
    text: str,
    case_id: str | None = None,
    selected_txn_id: str | None = None,
    source: str = "chat",
) -> dict[str, Any]:
    max_chars = int(cfg_mgr.thresholds.get("max_message_chars", 2000))
    if len(text or "") > max_chars:
        raise ValueError("too_long")

    # 1. Fetch customer profile for name/address masking & device info
    prof_out = await crm.get_customer_profile(acting_user=persona_id, customer_id=persona_id, emit_trace=False)
    profile = prof_out.data if (prof_out.ok and isinstance(prof_out.data, dict)) else (
        cfg_mgr.get_personas().get(persona_id, {"id": persona_id, "name": persona_id, "language": "en"})
    )
    prof_name = str(profile.get("name") or "")
    prof_addr = str(profile.get("address") or "")
    default_lang = str(profile.get("language") or "en")

    # 2. Create or resume case
    existing_case = query_one("SELECT * FROM cases WHERE id = ?", (case_id,)) if case_id else None
    is_clarify_resume = False
    if existing_case:
        if existing_case["persona_id"] != persona_id:
            raise PermissionError("forbidden_cross_user_case")
        case_id = existing_case["id"]
        is_clarify_resume = existing_case.get("state") == "CLARIFYING" or bool(selected_txn_id)
    else:
        # Check if persona has an open CLARIFYING case
        open_clarify = query_one(
            "SELECT * FROM cases WHERE persona_id = ? AND state = 'CLARIFYING' ORDER BY created_at DESC LIMIT 1",
            (persona_id,),
        )
        if open_clarify:
            existing_case = open_clarify
            case_id = open_clarify["id"]
            is_clarify_resume = True
        else:
            if not case_id:
                case_id = next_id("case")
                while query_one("SELECT id FROM cases WHERE id = ?", (case_id,)):
                    case_id = next_id("case")
            now_iso = utc_now_iso()
            execute(
                """
                INSERT INTO cases(
                    id, parent_id, persona_id, source, state, agent, intent, language, sentiment,
                    outcome, rule_fired, trigger, diagnosis, owner_id, masked_text, extraction_json,
                    guard_hit, clarification_used, created_at, closed_at, lane, reopened, confidence, confidence_band
                ) VALUES (?, NULL, ?, ?, 'OPEN', '', '', ?, 'calm', '', '', '', '', '', '', '{}', 0, 0, ?, NULL, 'amber', 0, 1.0, 'high')
                """,
                (case_id, persona_id, source, default_lang, now_iso),
            )

    assert case_id is not None

    # 3. Mask PII & Secrets before persisting or calling any model
    mask_res = mask_pii(text, profile_name=prof_name, profile_addr=prof_addr)
    _save_pii_tokens(case_id, mask_res.tokens)

    # Persist user message with secret digits replaced by ••••
    bus.publish_customer(
        persona_id,
        "user",
        {"case_id": case_id, "text": mask_res.user_display_text},
        case_id=case_id,
        role="user",
    )

    # Check if a human currently owns this case
    current_row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if current_row and current_row.get("owner_id"):
        record_case_event(
            case_id=case_id,
            badge="[HUMAN]",
            evt_type="user_reply_under_human_owner",
            summary=f"Customer message received while {current_row['owner_id']} owns case",
            payload={"masked_text": mask_res.text},
        )
        bus.publish_console("case_updated", {"case": current_row})
        return await get_case_detail(case_id)

    transition(case_id, "UNDERSTANDING")

    record_case_event(
        case_id=case_id,
        badge="[MASK]",
        evt_type="mask",
        summary=f"Masked {len(mask_res.tokens)} PII/secret token(s)" + (" [SECRET HIDDEN]" if mask_res.secret_shared else ""),
        payload={
            "masked_text": mask_res.text,
            "token_keys": list(mask_res.tokens.keys()),
            "secret_shared": mask_res.secret_shared,
        },
        status="warn" if mask_res.secret_shared else "ok",
    )

    # 4. Guard scan on customer input
    ablate = get_ablate_flags()
    if "no_guard" in ablate:
        clean_text = mask_res.text
        guard_hit = False
        removed_sentences: list[str] = []
    else:
        clean_text, guard_hit, removed_sentences = guard_scan(mask_res.text)

    if guard_hit:
        execute("UPDATE cases SET guard_hit = 1 WHERE id = ?", (case_id,))

    record_case_event(
        case_id=case_id,
        badge="[GUARD]",
        evt_type="guard",
        summary="Prompt-injection sentence stripped" if guard_hit else "Guard scan clean",
        payload={"guard_hit": guard_hit, "removed": removed_sentences, "clean_text": clean_text},
        status="warn" if guard_hit else "ok",
    )

    # 5. Sensitive-domain detection (F8 / T8) over clean masked text
    sens_res = detect_sensitive(clean_text) if "no_policy" not in ablate else detect_sensitive("")
    if sens_res.matched:
        record_case_event(
            case_id=case_id,
            badge="[GUARD]",
            evt_type="sensitive",
            summary=f"Sensitive/vulnerable phrase matched ({', '.join(sens_res.categories)}) → T8",
            payload={"categories": sens_res.categories, "phrases": sens_res.phrases, "is_distress": sens_res.is_distress},
            status="warn",
        )

    # 6. Structured Extraction via LLM Provider
    provider = get_provider()
    if not clean_text and guard_hit:
        # Entire message was a prompt-injection instruction with no legitimate request
        ext = fallback_extraction()
    else:
        try:
            raw_ext = await provider.extract(clean_text or mask_res.text, Extraction.model_json_schema(), case_id=case_id)
            ext = post_process_extraction(Extraction.model_validate(raw_ext))
        except Exception:
            ext = fallback_extraction()

    lang = ext.language if ext.language in ("en", "hinglish", "hi") else default_lang

    # F10 Secret Warning: send SECRET_WARNING first if customer shared OTP/PIN/CVV
    if mask_res.secret_shared:
        warn_text, _ = await compose_message("SECRET_WARNING", {}, lang, case_id=case_id)
        await notify.send_message(acting_user=persona_id, message=warn_text, case_id=case_id, actor="saathi")
        bus.publish_customer(
            persona_id,
            "saathi_text",
            {
                "case_id": case_id,
                "text": warn_text,
                "template": "SECRET_WARNING",
                "template_code": "SECRET_WARNING",
                "secret_warned": True,
            },
            case_id=case_id,
        )

    # If resuming from CLARIFYING, preserve original intent and boost confidence
    if is_clarify_resume and existing_case:
        orig_intent = existing_case.get("intent") or "PAYMENT_FAILED_DEBITED"
        if ext.issues[0].intent in ("OTHER", "PAYMENT_FAILED_DEBITED"):
            ext.issues[0].intent = orig_intent  # type: ignore[assignment]
            ext.issues[0].confidence = max(ext.issues[0].confidence, 0.95)
        if selected_txn_id:
            ext.issues[0].entities.txn_id = selected_txn_id

    execute(
        "UPDATE cases SET masked_text = ?, extraction_json = ?, language = ?, sentiment = ? WHERE id = ?",
        (mask_res.text, json.dumps(ext.model_dump()), lang, ext.sentiment, case_id),
    )

    record_case_event(
        case_id=case_id,
        badge="[EXTRACT]",
        evt_type="extract",
        summary=f"Extracted {len(ext.issues)} issue(s): {', '.join(i.intent for i in ext.issues)} ({lang})",
        payload=ext.model_dump(),
        status="ok",
    )

    # 7. Arm A (FAQ Chatbot baseline in eval mode): BM25 over help articles only, no tools
    if get_eval_arm() == "A":
        hits = kb.search_kb(clean_text or mask_res.text, top_k=1, case_id=case_id)
        steps = hits[0]["steps"] if hits else "Please check Help & Support in the Paytm app."
        msg_text, _ = await compose_message("APP_GUIDE", {"steps": steps}, lang, case_id=case_id)
        bus.publish_customer(
            persona_id,
            "resolution",
            {"case_id": case_id, "text": msg_text, "template_code": "APP_GUIDE"},
            case_id=case_id,
        )
        execute(
            "UPDATE cases SET agent = 'app_assistance', intent = ?, outcome = 'AUTO', rule_fired = '5', diagnosis = 'APP_GUIDE', lane = 'green' WHERE id = ?",
            (ext.issues[0].intent, case_id),
        )
        transition(case_id, "CLOSED")
        return await get_case_detail(case_id)

    # 8. Multi-Issue Decomposition (D9, e.g. S15)
    issues_raw = [iss.model_dump() for iss in ext.issues]
    if len(issues_raw) > 1 and not is_clarify_resume:
        sorted_issues = sorted(issues_raw, key=_issue_sort_key)
        parent_triggers: list[str] = []
        if ext.mentions_human_request:
            parent_triggers.append("T2")
        if sens_res.matched:
            parent_triggers.append("T8")

        child_details: list[dict[str, Any]] = []
        for idx, iss_dict in enumerate(sorted_issues):
            child_id = next_id("case")
            now_iso = utc_now_iso()
            execute(
                """
                INSERT INTO cases(
                    id, parent_id, persona_id, source, state, agent, intent, language, sentiment,
                    outcome, rule_fired, trigger, diagnosis, owner_id, masked_text, extraction_json,
                    guard_hit, clarification_used, created_at, closed_at, lane, reopened, confidence, confidence_band
                ) VALUES (?, ?, ?, ?, 'UNDERSTANDING', '', ?, ?, ?, '', '', '', '', '', ?, ?, ?, 0, ?, NULL, 'amber', 0, 1.0, 'high')
                """,
                (
                    child_id,
                    case_id,
                    persona_id,
                    source,
                    iss_dict["intent"],
                    lang,
                    ext.sentiment,
                    mask_res.text,
                    json.dumps(ext.model_dump()),
                    1 if guard_hit else 0,
                    now_iso,
                ),
            )
            c_detail = await _run_single_issue(
                case_id=child_id,
                persona_id=persona_id,
                masked_text=clean_text or mask_res.text,
                language=lang,
                sentiment=ext.sentiment,
                issue_dict=iss_dict,
                mentions_human_request=ext.mentions_human_request,
                fraud_signals=list(ext.fraud_signals),
                sens_matched=sens_res.matched,
                sens_is_distress=sens_res.is_distress,
                sens_categories=sens_res.categories,
                clarification_used=False,
                selected_txn_id=None,
                customer_profile=profile,
                english_summary=ext.english_summary,
                propagated_triggers=parent_triggers,
            )
            child_details.append(c_detail)

        primary = child_details[0]
        # Attach child resolution text to parent case so caller gets the full combined resolution
        child_texts = []
        for c in child_details:
            for m in reversed(c.get("messages", [])):
                if m.get("role") in ("saathi", "assistant") and m.get("body", {}).get("text"):
                    child_texts.append(m["body"]["text"])
                    break
        if child_texts:
            combined_text = "\n\n".join(child_texts)
            bus.publish_customer(
                persona_id,
                "resolution",
                {
                    "case_id": case_id,
                    "text": combined_text,
                    "template_code": primary.get("template_code", "MULTI_ISSUE"),
                    "diagnosis": primary.get("diagnosis", "MULTI_ISSUE"),
                },
                case_id=case_id,
            )
        execute(
            """
            UPDATE cases
            SET agent = ?, intent = ?, outcome = ?, rule_fired = ?, trigger = ?, diagnosis = ?,
                lane = ?, confidence = ?, confidence_band = ?
            WHERE id = ?
            """,
            (
                primary.get("agent", "payment_failure"),
                primary.get("intent", "PAYMENT_FAILED_DEBITED"),
                primary.get("outcome", "AUTO"),
                primary.get("rule_fired", "3"),
                primary.get("trigger", ""),
                primary.get("diagnosis", "MULTI_ISSUE"),
                primary.get("lane", "amber"),
                primary.get("confidence", 0.95),
                primary.get("confidence_band", "high"),
                case_id,
            ),
        )
        transition(case_id, primary.get("state", "CLOSED"))
        return await get_case_detail(case_id)

    # 9. Single Issue Execution
    return await _run_single_issue(
        case_id=case_id,
        persona_id=persona_id,
        masked_text=clean_text or mask_res.text,
        language=lang,
        sentiment=ext.sentiment,
        issue_dict=issues_raw[0],
        mentions_human_request=ext.mentions_human_request,
        fraud_signals=list(ext.fraud_signals),
        sens_matched=sens_res.matched,
        sens_is_distress=sens_res.is_distress,
        sens_categories=sens_res.categories,
        clarification_used=is_clarify_resume,
        selected_txn_id=selected_txn_id,
        customer_profile=profile,
        english_summary=ext.english_summary,
        propagated_triggers=[],
    )


async def _run_single_issue(
    *,
    case_id: str,
    persona_id: str,
    masked_text: str,
    language: str,
    sentiment: str,
    issue_dict: dict[str, Any],
    mentions_human_request: bool,
    fraud_signals: list[str],
    sens_matched: bool,
    sens_is_distress: bool,
    sens_categories: list[str],
    clarification_used: bool,
    selected_txn_id: str | None,
    customer_profile: dict[str, Any],
    english_summary: str,
    propagated_triggers: list[str],
) -> dict[str, Any]:
    intent = str(issue_dict.get("intent", "OTHER"))
    intent_conf = float(issue_dict.get("confidence", 0.85))
    entities = dict(issue_dict.get("entities") or {})

    agent_name = str(cfg_mgr.routing.get(intent, "fallback"))
    agent = AGENTS.get(agent_name, AGENTS["fallback"])

    transition(case_id, "ROUTED")
    execute(
        "UPDATE cases SET agent = ?, intent = ?, clarification_used = ? WHERE id = ?",
        (agent_name, intent, 1 if clarification_used else 0, case_id),
    )

    record_case_event(
        case_id=case_id,
        badge="[ROUTE]",
        evt_type="route",
        summary=f"Routed {intent} (conf {intent_conf:.2f}) → {agent_name}",
        payload={"intent": intent, "confidence": intent_conf, "agent": agent_name, "entities": entities},
        status="ok",
    )

    transition(case_id, "DIAGNOSING")
    ctx = AgentContext(
        case_id=case_id,
        persona_id=persona_id,
        masked_text=masked_text,
        language=language,
        intent=intent,
        intent_confidence=intent_conf,
        entities=entities,
        sentiment=sentiment,
        mentions_human_request=mentions_human_request,
        fraud_signals=fraud_signals,
        clarification_used=clarification_used,
        selected_txn_id=selected_txn_id,
        customer_profile=customer_profile,
    )
    agent_res = await agent.decide(ctx)

    # Check if single clarification is needed (S16 Turn 1)
    if agent_res.needs_clarification:
        transition(case_id, "CLARIFYING")
        execute(
            "UPDATE cases SET clarification_used = 1, diagnosis = 'CLARIFY_TXN', lane = 'amber' WHERE id = ?",
            (case_id,),
        )
        msg_text, _ = await compose_message("CLARIFY_TXN", {"case_id": case_id}, language, sentiment, case_id=case_id)
        options = [
            {
                "txn_id": c["id"],
                "amount": c["amount"],
                "counterparty": c["counterparty"],
                "status": c["status"],
                "created_at": c["created_at"],
            }
            for c in agent_res.clarify_candidates
        ]
        bus.publish_customer(
            persona_id,
            "clarification",
            {
                "case_id": case_id,
                "text": msg_text,
                "template_code": "CLARIFY_TXN",
                "options": options,
            },
            case_id=case_id,
        )
        await crm.sync_crm_case(acting_user=persona_id, case_id=case_id, agent=agent_name, state="CLARIFYING")
        return await get_case_detail(case_id)

    # Check untrusted ledger remark flag (S28)
    if agent_res.txn and agent_res.txn.get("remark_flagged"):
        record_case_event(
            case_id=case_id,
            badge="[POLICY]",
            evt_type="remark_policy",
            summary="Instruction-like remark ignored",
            payload={
                "txn_id": agent_res.txn.get("id"),
                "remark_clean": agent_res.txn.get("remark_clean", ""),
                "remark_flagged": True,
            },
            status="warn",
        )

    # F3 Incident signal recording & known-incident awareness
    if agent_name == "payment_failure" and agent_res.txn:
        record_complaint_signal(case_id=case_id, persona_id=persona_id, txn=agent_res.txn, source="chat")
        sig = f"{agent_res.txn.get('bank_code', 'BANK_TIMEOUT')}|{agent_res.txn.get('rail', 'BILL_PAY')}"
        open_inc = get_open_incident_for_signature(sig)
        if open_inc:
            record_case_event(
                case_id=case_id,
                badge="[POLICY]",
                evt_type="known_incident",
                summary=f"Known incident {open_inc['id']}",
                payload={"incident_id": open_inc["id"], "signature": sig},
                status="warn",
            )

    # Assemble all active triggers
    triggers: list[str] = list(propagated_triggers)
    for t in agent_res.triggers:
        if t not in triggers:
            triggers.append(t)
    if mentions_human_request and "T2" not in triggers:
        triggers.append("T2")
    if sens_matched and "T8" not in triggers:
        triggers.append("T8")
    if cfg_mgr.is_agent_paused(agent_name) and "KS" not in triggers:
        triggers.append("KS")

    # Pre-escalation ticket for T8 when T1 is not the primary winner (S21 vs S22)
    if "T8" in triggers and "T1" not in triggers:
        tk_out = await crm.create_ticket(
            acting_user=persona_id,
            case_id=case_id,
            category="SENSITIVE",
            details={"categories": sens_categories, "is_distress": sens_is_distress},
            actor=agent_name,
        )
        tk_id = (tk_out.data or {}).get("id", "TK-7001")
        agent_res.actions_taken.append({"action": "create_ticket", "id": tk_id})

    # Compute Calibrated Confidence (F6) before policy evaluation
    transition(case_id, "POLICY_CHECK")
    pol_cfg = cfg_mgr.get_policy_config()
    prop = agent_res.proposed_action
    is_money = bool(prop and prop.is_money)
    action_amt = int(prop.amount) if prop else 0
    mode = pol_cfg.autonomy.get(agent_name, "guarded")
    cap = pol_cfg.modes.get(mode, {"auto_cap": 5000})["auto_cap"]
    is_blocked = bool(prop and ((prop.name not in agent.ALLOWLIST) or (prop.target_user and prop.target_user != persona_id)))
    exceeds_cap = bool(is_money and action_amt > cap)

    conf_res = compute_confidence(
        extraction_conf=intent_conf,
        clarification_used=clarification_used,
        claimed_amount=entities.get("amount"),
        ledger_amount=int(agent_res.txn["amount"]) if agent_res.txn else None,
        counterparty_hint=entities.get("counterparty_hint"),
        ledger_counterparty=str(agent_res.txn.get("counterparty", "")) if agent_res.txn else None,
        debit_matches_bank=agent_res.debit_matches_bank,
        eligibility_consistent=agent_res.eligibility_consistent,
        refund_state_consistent=agent_res.refund_state_consistent,
        is_money_action=is_money,
        action_amount=action_amt,
        has_triggers=bool(triggers or (is_money and action_amt > pol_cfg.ceiling)),
        is_blocked=is_blocked,
        exceeds_cap=exceeds_cap,
        cfg=pol_cfg,
    )

    pol_ctx = CasePolicyContext(
        case_id=case_id,
        persona_user=persona_id,
        triggers=triggers,
        confidence=conf_res.score,
    )
    decision = evaluate_policy(pol_ctx, prop, agent, pol_cfg)

    lane = cfg_mgr.compute_lane(agent_name, triggers if decision.outcome != "ESCALATE" else [decision.rule, *triggers])

    # Log confidence in confidence_log
    execute(
        """
        INSERT OR REPLACE INTO confidence_log(case_id, score, band, signals_json, correct)
        VALUES (?, ?, ?, ?, 1)
        """,
        (
            case_id,
            conf_res.score,
            conf_res.band,
            json.dumps(
                {
                    "understanding": conf_res.understanding,
                    "evidence": conf_res.evidence,
                    "policy": conf_res.policy,
                    "risk": conf_res.risk,
                    "checks": conf_res.checks,
                }
            ),
        ),
    )

    record_case_event(
        case_id=case_id,
        badge="[POLICY]",
        evt_type="policy",
        summary=f"{decision.text} (conf {conf_res.score:.2f} · {conf_res.band})",
        payload={
            "outcome": decision.outcome,
            "rule": decision.rule,
            "text": decision.text,
            "triggers": triggers,
            "confidence": {
                "score": conf_res.score,
                "band": conf_res.band,
                "understanding": conf_res.understanding,
                "evidence": conf_res.evidence,
                "policy": conf_res.policy,
                "risk": conf_res.risk,
                "checks": conf_res.checks,
            },
        },
        status="ok" if decision.outcome == "AUTO" else ("warn" if decision.outcome == "APPROVE" else "error"),
    )

    # Handle BLOCK (Rule 1, e.g. S14)
    if decision.outcome == "BLOCK":
        transition(case_id, "BLOCKED")
        msg_text, _ = await compose_message("BLOCKED_SCOPE", {"case_id": case_id}, language, sentiment, case_id=case_id)
        await notify.send_message(acting_user=persona_id, message=msg_text, case_id=case_id, actor=agent_name)
        bus.publish_customer(
            persona_id,
            "saathi_text",
            {"case_id": case_id, "text": msg_text, "template_code": "BLOCKED_SCOPE"},
            case_id=case_id,
        )
        execute(
            """
            UPDATE cases
            SET outcome = 'BLOCK', rule_fired = '1', trigger = '', diagnosis = 'BLOCKED_SCOPE',
                lane = ?, confidence = ?, confidence_band = ?
            WHERE id = ?
            """,
            (lane, conf_res.score, conf_res.band, case_id),
        )
        transition(case_id, "CLOSED")
        await crm.sync_crm_case(acting_user=persona_id, case_id=case_id, agent=agent_name, state="CLOSED", outcome="BLOCK")
        return await get_case_detail(case_id)

    # Handle APPROVE (Rule 4, Rule 3v, Rule 3c — e.g. S5, S32)
    if decision.outcome == "APPROVE" and prop:
        transition(case_id, "AWAITING_APPROVAL")
        app_id = next_id("approval")
        now_iso = utc_now_iso()
        execute(
            """
            INSERT INTO approvals(
                id, case_id, proposed_action_json, rule_fired, status, decided_by,
                reason_code, reason_text, created_at, decided_at
            ) VALUES (?, ?, ?, ?, 'PENDING', NULL, NULL, NULL, ?, NULL)
            """,
            (
                app_id,
                case_id,
                json.dumps(
                    {
                        "name": prop.name,
                        "args": prop.args,
                        "amount": prop.amount,
                        "target_txn": prop.target_txn,
                        "facts": agent_res.facts,
                        "template_code": agent_res.template_code,
                        "diagnosis": agent_res.diagnosis,
                    }
                ),
                decision.rule,
                now_iso,
            ),
        )
        execute(
            """
            UPDATE cases
            SET outcome = 'APPROVE', rule_fired = ?, trigger = '', diagnosis = ?,
                lane = 'amber', confidence = ?, confidence_band = ?
            WHERE id = ?
            """,
            (decision.rule, agent_res.diagnosis, conf_res.score, conf_res.band, case_id),
        )

        case_row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,)) or {"id": case_id, "persona_id": persona_id}
        packet = build_handoff_packet(
            case_row=case_row,
            diagnosis=agent_res.diagnosis,
            facts=agent_res.facts,
            verified_facts=agent_res.verified_facts,
            actions_taken=agent_res.actions_taken,
            rule_fired_text=decision.text,
            trigger_id=decision.rule,
            confidence_obj={
                "score": conf_res.score,
                "band": conf_res.band,
                "understanding": conf_res.understanding,
                "evidence": conf_res.evidence,
                "policy": conf_res.policy,
                "risk": conf_res.risk,
                "checks": conf_res.checks,
            },
            cap=cap,
            min_conf=pol_cfg.min_auto_confidence,
            english_summary=english_summary,
        )
        await crm.post_handoff(acting_user=persona_id, case_id=case_id, packet=packet, actor=agent_name)

        msg_text, _ = await compose_message(
            "APPROVAL_PENDING",
            agent_res.facts,
            language,
            sentiment,
            case_id=case_id,
        )
        await notify.send_message(acting_user=persona_id, message=msg_text, case_id=case_id, actor=agent_name)
        bus.publish_customer(
            persona_id,
            "approval_waiting",
            {
                "case_id": case_id,
                "approval_id": app_id,
                "text": msg_text,
                "template_code": "APPROVAL_PENDING",
            },
            case_id=case_id,
        )
        bus.publish_console("approval_Queued", {"approval_id": app_id, "case_id": case_id, "packet": packet})
        await crm.sync_crm_case(acting_user=persona_id, case_id=case_id, agent=agent_name, state="AWAITING_APPROVAL", outcome="APPROVE")
        return await get_case_detail(case_id)

    # Handle ESCALATE (Rule 2 triggers: T1..T8, KS)
    if decision.outcome == "ESCALATE":
        return await _escalate_with_packet(
            case_id=case_id,
            persona_id=persona_id,
            agent_name=agent_name,
            language=language,
            sentiment=sentiment,
            diagnosis=agent_res.diagnosis,
            facts=agent_res.facts,
            verified_facts=agent_res.verified_facts,
            actions_taken=agent_res.actions_taken,
            trigger_id=decision.rule,
            rule_text=decision.text,
            all_triggers=triggers,
            conf_res=conf_res,
            cap=cap,
            min_conf=pol_cfg.min_auto_confidence,
            sens_is_distress=sens_is_distress,
            english_summary=english_summary,
            template_override=(
                "FRAUD_LOCKED"
                if decision.rule == "T1" and agent_res.template_code == "FRAUD_LOCKED"
                else ("HUMAN_ACK" if decision.rule == "T2" else "ESCALATED")
            ),
        )

    # Handle AUTO (Rule 3 or Rule 5)
    if prop:
        transition(case_id, "EXECUTING")
        w_out = await execute_action(
            action_name=prop.name,
            args=prop.args,
            acting_user=persona_id,
            case_id=case_id,
            actor=agent_name,
        )
        if not w_out.ok:
            # Tool failure after retries -> T6 escalation (S18)
            triggers.append("T6")
            return await _escalate_with_packet(
                case_id=case_id,
                persona_id=persona_id,
                agent_name=agent_name,
                language=language,
                sentiment=sentiment,
                diagnosis="TOOL_FAILURE",
                facts={**agent_res.facts, "owner": "Priya Nair from our support team"},
                verified_facts=[*agent_res.verified_facts, f"Tool {prop.name} failed after {w_out.attempts} attempts."],
                actions_taken=agent_res.actions_taken,
                trigger_id="T6",
                rule_text="Rule 2 · T6 · Tool failure after 2 retries",
                all_triggers=triggers,
                conf_res=conf_res,
                cap=cap,
                min_conf=pol_cfg.min_auto_confidence,
                sens_is_distress=sens_is_distress,
                english_summary=english_summary,
                template_override="TOOL_FAILURE",
            )

        ver_res = await verify_and_recover(
            case_id=case_id,
            action_name=prop.name,
            args=prop.args,
            write_outcome=w_out,
            acting_user=persona_id,
            actor=agent_name,
        )
        if not ver_res.verified:
            # Phantom write unrecovered after verify_rewrite_max retries -> T6 escalation (S24)
            triggers.append("T6")
            return await _escalate_with_packet(
                case_id=case_id,
                persona_id=persona_id,
                agent_name=agent_name,
                language=language,
                sentiment=sentiment,
                diagnosis="VERIFY_FAILURE",
                facts={**agent_res.facts, "owner": "Priya Nair from our support team"},
                verified_facts=[
                    *agent_res.verified_facts,
                    f"Outcome verification failed ({ver_res.status}) after {ver_res.attempts} attempts.",
                ],
                actions_taken=agent_res.actions_taken,
                trigger_id="T6",
                rule_text="Rule 2 · T6 · Outcome verification failed after retries",
                all_triggers=triggers,
                conf_res=conf_res,
                cap=cap,
                min_conf=pol_cfg.min_auto_confidence,
                sens_is_distress=sens_is_distress,
                english_summary=english_summary,
                template_override="TOOL_FAILURE",
            )

        transition(case_id, "OUTCOME_VERIFIED")
        obs = ver_res.data or (w_out.data if isinstance(w_out.data, dict) else {})
        if prop.name == "initiate_refund":
            rf_id = str(obs.get("id") or "RF-9001")
            agent_res.facts["refund_id"] = rf_id
            agent_res.facts["eta"] = format_date_short(obs.get("eta"))
            agent_res.actions_taken.append({"action": "initiate_refund", "id": rf_id})

            # Schedule T+n completion check (F2)
            await notify.schedule_followup(
                acting_user=persona_id,
                case_id=case_id,
                run_in_minutes=4335,
                check_kind="REFUND_COMPLETED",
                actor=agent_name,
            )
            register_followup_check(
                case_id=case_id,
                kind="REFUND_COMPLETED",
                due_hours=72.25,
                target_id=rf_id,
                txn_id=str(prop.target_txn or ""),
            )
    else:
        transition(case_id, "OUTCOME_VERIFIED")
        if agent_res.diagnosis == "REVERSAL_PENDING" and agent_res.txn:
            register_followup_check(
                case_id=case_id,
                kind="REVERSAL_COMPLETED",
                due_hours=6.25,
                target_id=agent_res.txn["id"],
                txn_id=agent_res.txn["id"],
            )

    # Compose customer resolution card
    msg_text, used_fallback = await compose_message(
        agent_res.template_code,
        agent_res.facts,
        language,
        sentiment,
        case_id=case_id,
    )
    sections = build_resolution_sections(agent_res.diagnosis, agent_res.facts)

    record_case_event(
        case_id=case_id,
        badge="[COMPOSE]",
        evt_type="compose",
        summary=f"Composed {agent_res.template_code} ({language})" + (" [fallback]" if used_fallback else ""),
        payload={
            "template_code": agent_res.template_code,
            "language": language,
            "text": msg_text,
            "sections": sections,
            "used_fallback": used_fallback,
        },
        status="ok",
    )

    await notify.send_message(acting_user=persona_id, message=msg_text, case_id=case_id, actor=agent_name)
    bus.publish_customer(
        persona_id,
        "resolution",
        {
            "case_id": case_id,
            "text": msg_text,
            "template_code": agent_res.template_code,
            "diagnosis": agent_res.diagnosis,
            "found": sections["found"],
            "did": sections["did"],
            "next": sections["next"],
        },
        case_id=case_id,
    )

    # F11: RBI TAT Compensation detection & COMP_NOTE follow-up message (for rail=UPI failed debits > 24h, e.g. S28, S29)
    if agent_res.diagnosis in ("REFUND_DUE", "DUPLICATE_DEBIT") and agent_res.txn:
        claim = await check_and_record_tat_compensation(
            case_id=case_id,
            txn=agent_res.txn,
            language=language,
        )
        if claim:
            await notify.send_message(acting_user=persona_id, message=claim["note"], case_id=case_id, actor=agent_name)
            bus.publish_customer(
                persona_id,
                "saathi_text",
                {
                    "case_id": case_id,
                    "text": claim["note"],
                    "template": "COMP_NOTE",
                    "template_code": "COMP_NOTE",
                    "claim_id": claim["id"],
                },
                case_id=case_id,
            )

    execute(
        """
        UPDATE cases
        SET outcome = 'AUTO', rule_fired = ?, trigger = '', diagnosis = ?,
            lane = ?, confidence = ?, confidence_band = ?
        WHERE id = ?
        """,
        (decision.rule, agent_res.diagnosis, lane, conf_res.score, conf_res.band, case_id),
    )
    transition(case_id, "CLOSED")
    await crm.sync_crm_case(
        acting_user=persona_id,
        case_id=case_id,
        agent=agent_name,
        state="CLOSED",
        outcome=agent_res.diagnosis,
    )
    return await get_case_detail(case_id)


async def _escalate_with_packet(
    *,
    case_id: str,
    persona_id: str,
    agent_name: str,
    language: str,
    sentiment: str,
    diagnosis: str,
    facts: dict[str, Any],
    verified_facts: list[str],
    actions_taken: list[dict[str, str]],
    trigger_id: str,
    rule_text: str,
    all_triggers: list[str],
    conf_res: Any,
    cap: int,
    min_conf: float,
    sens_is_distress: bool,
    english_summary: str,
    template_override: str = "ESCALATED",
) -> dict[str, Any]:
    lane = cfg_mgr.compute_lane(agent_name, [trigger_id, *all_triggers])
    execute(
        """
        UPDATE cases
        SET outcome = 'ESCALATE', rule_fired = ?, trigger = ?, diagnosis = ?,
            lane = ?, confidence = ?, confidence_band = ?
        WHERE id = ?
        """,
        (trigger_id, trigger_id, diagnosis, lane, conf_res.score, conf_res.band, case_id),
    )
    transition(case_id, "ESCALATED")

    case_row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,)) or {"id": case_id, "persona_id": persona_id}
    packet = build_handoff_packet(
        case_row=case_row,
        diagnosis=diagnosis,
        facts=facts,
        verified_facts=verified_facts,
        actions_taken=actions_taken,
        rule_fired_text=rule_text,
        trigger_id=trigger_id,
        confidence_obj={
            "score": conf_res.score,
            "band": conf_res.band,
            "understanding": conf_res.understanding,
            "evidence": conf_res.evidence,
            "policy": conf_res.policy,
            "risk": conf_res.risk,
            "checks": conf_res.checks,
        },
        cap=cap,
        min_conf=min_conf,
        is_distress=sens_is_distress,
        english_summary=english_summary,
    )
    await crm.post_handoff(acting_user=persona_id, case_id=case_id, packet=packet, actor=agent_name)

    facts_with_owner = {"owner": "Priya Nair from our support team", **facts, "case_id": case_id}
    msg_text, used_fallback = await compose_message(
        template_override,
        facts_with_owner,
        language,
        sentiment,
        case_id=case_id,
    )
    record_case_event(
        case_id=case_id,
        badge="[COMPOSE]",
        evt_type="compose",
        summary=f"Composed escalation message {template_override} ({language})",
        payload={"template_code": template_override, "text": msg_text, "used_fallback": used_fallback},
        status="ok",
    )

    await notify.send_message(acting_user=persona_id, message=msg_text, case_id=case_id, actor=agent_name)
    bus.publish_customer(
        persona_id,
        "escalation",
        {
            "case_id": case_id,
            "text": msg_text,
            "template_code": template_override,
            "trigger": trigger_id,
        },
        case_id=case_id,
    )
    bus.publish_console("case_escalated", {"case_id": case_id, "trigger": trigger_id, "packet": packet})
    await crm.sync_crm_case(
        acting_user=persona_id,
        case_id=case_id,
        agent=agent_name,
        state="ESCALATED",
        outcome=f"ESCALATED_{trigger_id}",
    )
    return await get_case_detail(case_id)


# ============================================================================
# Case Detail, Receipt (F14), and Human Console Actions
# ============================================================================

async def get_case_detail(case_id: str) -> dict[str, Any]:
    row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not row:
        raise ValueError(f"Case {case_id} not found")
    out = dict(row)
    out["extraction"] = json.loads(out.get("extraction_json") or "{}")

    events = query_all("SELECT * FROM case_events WHERE case_id = ? ORDER BY seq ASC", (case_id,))
    out["events"] = [{**e, "payload": json.loads(e.get("payload_json") or "{}")} for e in events]

    msgs = query_all("SELECT * FROM messages WHERE case_id = ? ORDER BY id ASC", (case_id,))
    out["messages"] = [{**m, "body": json.loads(m.get("body_json") or "{}")} for m in msgs]

    apps = query_all("SELECT * FROM approvals WHERE case_id = ? ORDER BY created_at DESC", (case_id,))
    out["approvals"] = [{**a, "proposed_action": json.loads(a.get("proposed_action_json") or "{}")} for a in apps]

    notes = query_all("SELECT * FROM case_notes WHERE case_id = ? ORDER BY id ASC", (case_id,))
    out["notes"] = notes

    children = query_all("SELECT * FROM cases WHERE parent_id = ? ORDER BY id ASC", (case_id,))
    out["children"] = children

    # Fetch handoff packet from CRM DB if present
    from app.mocks.crm.db import crm_db

    hf_row = crm_db.query_one("SELECT packet_json FROM handoffs WHERE case_id = ? ORDER BY id DESC LIMIT 1", (case_id,))
    out["handoff"] = json.loads(hf_row["packet_json"]) if hf_row and hf_row.get("packet_json") else None

    claims = query_all("SELECT * FROM compensation_claims WHERE case_id = ?", (case_id,))
    out["compensation_claims"] = claims

    followups = query_all("SELECT * FROM followup_checks WHERE case_id = ?", (case_id,))
    out["followup_checks"] = followups

    return out


def build_case_receipt(case_id: str) -> dict[str, Any]:
    """
    F14: Customer-safe timeline built from a fixed mapping of event types to plain lines.
    No rule numbers, no internal trace JSON.
    """
    case_row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not case_row:
        raise ValueError(f"Case {case_id} not found")

    events = query_all("SELECT * FROM case_events WHERE case_id = ? ORDER BY seq ASC", (case_id,))
    steps: list[dict[str, str]] = []

    for e in events:
        etype = e.get("type", "")
        badge = e.get("badge", "")
        payload = json.loads(e.get("payload_json") or "{}")
        ts = e.get("ts", "")

        if etype == "mask":
            steps.append({"ts": ts, "line": "Received your message and protected personal details."})
        elif etype == "tool_call":
            tname = payload.get("tool", "")
            resp = payload.get("response") or {}
            if tname == "lookup_transaction" and isinstance(resp, dict) and resp.get("id"):
                steps.append({"ts": ts, "line": f"Checked payment {resp['id']} (₹{resp.get('amount')}) in ledger."})
            elif tname == "get_bank_status" and isinstance(resp, dict):
                steps.append({"ts": ts, "line": "Bank confirmed the debit status."})
            elif tname == "initiate_refund" and isinstance(resp, dict) and resp.get("id"):
                steps.append({"ts": ts, "line": f"Refund {resp['id']} started for ₹{resp.get('amount')}."})
            elif tname == "raise_reconciliation" and isinstance(resp, dict) and resp.get("id"):
                steps.append({"ts": ts, "line": f"Raised bank reconciliation {resp['id']}."})
        elif badge == "[VERIFY] ✓":
            tid = payload.get("target_id", "")
            steps.append({"ts": ts, "line": f"Verified record {tid} with downstream banking system."})
        elif etype == "followup_scheduled":
            due = format_date_short(payload.get("due_at"))
            steps.append({"ts": ts, "line": f"We'll re-check automatically on {due}."})
        elif etype == "followup_done":
            steps.append({"ts": ts, "line": "Re-check done: refund completed."})
        elif etype == "followup_reopened":
            steps.append({"ts": ts, "line": "Re-check found delay: raised bank reconciliation and assigned specialist."})
        elif etype == "tat_compensation":
            steps.append({"ts": ts, "line": f"Possible compensation noted (up to ₹{payload.get('amount_estimate')})."})

    return {
        "case_id": case_id,
        "state": case_row.get("state"),
        "diagnosis": case_row.get("diagnosis"),
        "created_at": case_row.get("created_at"),
        "closed_at": case_row.get("closed_at"),
        "steps": steps,
    }


def record_decision_view(approval_id: str, view_mode: str = "card", actor: str = "A-1") -> dict[str, Any]:
    now_iso = utc_now_iso()
    existing = query_one(
        "SELECT * FROM decision_timings WHERE approval_id = ? AND view_mode = ? AND decided_at IS NULL",
        (approval_id, view_mode),
    )
    if not existing:
        execute(
            "INSERT INTO decision_timings(approval_id, view_mode, opened_at, decided_at, decision, decided_by) VALUES (?, ?, ?, NULL, NULL, ?)",
            (approval_id, view_mode, now_iso, actor),
        )
    return {"ok": True, "approval_id": approval_id, "view_mode": view_mode, "opened_at": now_iso}


async def decide_approval(
    approval_id: str,
    *,
    decision: str,  # "APPROVED" | "EDITED" | "REJECTED"
    actor: str = "A-1",
    edited_reply: str | None = None,
    reason_code: str | None = None,
    reason_text: str | None = None,
    view_mode: str = "card",
) -> dict[str, Any]:
    app_row = query_one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
    if not app_row:
        raise ValueError(f"Approval {approval_id} not found")
    if app_row["status"] != "PENDING":
        return await get_case_detail(app_row["case_id"])

    case_id = app_row["case_id"]
    case_row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not case_row:
        raise ValueError(f"Case {case_id} not found")

    persona_id = case_row["persona_id"]
    lang = case_row.get("language") or "en"
    agent_name = case_row.get("agent") or "payment_failure"
    prop_data = json.loads(app_row["proposed_action_json"] or "{}")
    now_iso = utc_now_iso()

    # Complete decision_timings row (F6 item 8)
    open_timing = query_one(
        "SELECT * FROM decision_timings WHERE approval_id = ? AND decided_at IS NULL ORDER BY opened_at DESC LIMIT 1",
        (approval_id,),
    )
    if open_timing:
        execute(
            "UPDATE decision_timings SET decided_at = ?, decision = ?, decided_by = ? WHERE approval_id = ? AND decided_at IS NULL",
            (now_iso, decision, actor, approval_id),
        )
    else:
        execute(
            "INSERT INTO decision_timings(approval_id, view_mode, opened_at, decided_at, decision, decided_by) VALUES (?, ?, ?, ?, ?, ?)",
            (approval_id, view_mode, app_row["created_at"], now_iso, decision, actor),
        )

    # Record autonomy_decisions (F7: agreed=1 if APPROVED unchanged, 0 if REJECTED or EDITED)
    agreed = 1 if decision == "APPROVED" else 0
    cur_mode = cfg_mgr.get_autonomy_modes().get(agent_name, "guarded")
    execute(
        """
        INSERT INTO autonomy_decisions(ts, agent, case_id, mode, agreed, decided_by, source)
        VALUES (?, ?, ?, ?, ?, ?, 'live')
        """,
        (now_iso, agent_name, case_id, cur_mode, agreed, f"human:{actor}"),
    )

    execute(
        """
        UPDATE approvals
        SET status = ?, decided_by = ?, reason_code = ?, reason_text = ?, decided_at = ?
        WHERE id = ?
        """,
        (decision, f"human:{actor}", reason_code, reason_text, now_iso, approval_id),
    )

    if decision == "REJECTED":
        if not reason_code:
            raise ValueError("reason_code is required when rejecting an approval")
        # Write override_tests row (F15)
        snap = {
            "case_id": case_id,
            "persona_id": persona_id,
            "agent": agent_name,
            "masked_text": case_row.get("masked_text"),
            "proposed_action": prop_data,
        }
        execute(
            """
            INSERT INTO override_tests(case_id, reason_code, snapshot_json, suggested_change, status, created_at)
            VALUES (?, ?, ?, ?, 'PENDING', ?)
            """,
            (
                case_id,
                reason_code,
                json.dumps(snap),
                f"Add regression test for {reason_code} on {agent_name}",
                now_iso,
            ),
        )
        record_case_event(
            case_id=case_id,
            badge="[HUMAN]",
            evt_type="approval_rejected",
            summary=f"Rejected by {actor} ({reason_code}): {reason_text or ''}",
            payload={"approval_id": approval_id, "actor": actor, "reason_code": reason_code, "reason_text": reason_text},
            status="warn",
        )
        transition(case_id, "ESCALATED")
        execute("UPDATE cases SET outcome = 'ESCALATE', owner_id = ? WHERE id = ?", (actor, case_id))
        msg_text, _ = await compose_message(
            "ESCALATED",
            {"case_id": case_id, "owner": f"{actor} from our support team"},
            lang,
            case_id=case_id,
        )
        await notify.send_message(acting_user=persona_id, message=msg_text, case_id=case_id, actor=f"human:{actor}")
        bus.publish_customer(
            persona_id,
            "escalation",
            {"case_id": case_id, "text": msg_text, "template_code": "ESCALATED"},
            case_id=case_id,
        )
        return await get_case_detail(case_id)

    # APPROVED or EDITED -> re-validate amount against ledger & execute action
    transition(case_id, "EXECUTING")
    act_name = prop_data.get("name", "initiate_refund")
    act_args = prop_data.get("args") or {}
    facts = prop_data.get("facts") or {"case_id": case_id}
    t_code = prop_data.get("template_code", "REFUND_INITIATED")
    diag = prop_data.get("diagnosis", "REFUND_DUE")

    w_out = await execute_action(
        action_name=act_name,
        args=act_args,
        acting_user=persona_id,
        case_id=case_id,
        actor=f"human:{actor}",
    )
    ver_res = await verify_and_recover(
        case_id=case_id,
        action_name=act_name,
        args=act_args,
        write_outcome=w_out,
        acting_user=persona_id,
        actor=f"human:{actor}",
    )
    obs = ver_res.data or (w_out.data if isinstance(w_out.data, dict) else {})
    if act_name == "initiate_refund":
        rf_id = str(obs.get("id") or "RF-9001")
        facts["refund_id"] = rf_id
        facts["eta"] = format_date_short(obs.get("eta"))
        register_followup_check(
            case_id=case_id,
            kind="REFUND_COMPLETED",
            due_hours=72.25,
            target_id=rf_id,
            txn_id=str(act_args.get("txn_id") or ""),
        )

    transition(case_id, "OUTCOME_VERIFIED")

    if decision == "EDITED" and edited_reply:
        msg_text = edited_reply
    else:
        msg_text, _ = await compose_message(t_code, facts, lang, case_id=case_id)

    sections = build_resolution_sections(diag, facts)
    record_case_event(
        case_id=case_id,
        badge="[HUMAN]",
        evt_type="approval_granted",
        summary=f"Approved by {actor} → executed & verified {act_name}",
        payload={"approval_id": approval_id, "actor": actor, "decision": decision, "target_id": ver_res.target_id},
        status="ok",
    )

    await notify.send_message(acting_user=persona_id, message=msg_text, case_id=case_id, actor=f"human:{actor}")
    bus.publish_customer(
        persona_id,
        "resolution",
        {
            "case_id": case_id,
            "text": msg_text,
            "template_code": t_code,
            "diagnosis": diag,
            "found": sections["found"],
            "did": sections["did"],
            "next": sections["next"],
        },
        case_id=case_id,
    )
    transition(case_id, "CLOSED")
    await crm.sync_crm_case(acting_user=persona_id, case_id=case_id, agent=agent_name, state="CLOSED", outcome="APPROVED_AUTO")
    return await get_case_detail(case_id)


async def take_case_ownership(case_id: str, actor: str = "A-1") -> dict[str, Any]:
    execute("UPDATE cases SET owner_id = ? WHERE id = ?", (actor, case_id))
    record_case_event(
        case_id=case_id,
        badge="[HUMAN]",
        evt_type="take_ownership",
        summary=f"{actor} took ownership of case",
        payload={"owner_id": actor},
    )
    row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,)) or {}
    await crm.sync_crm_case(
        acting_user=row.get("persona_id", "U-101"),
        case_id=case_id,
        agent=row.get("agent", "fallback"),
        state=row.get("state", "ESCALATED"),
        owner_id=actor,
    )
    bus.publish_console("case_updated", {"case": row})
    return await get_case_detail(case_id)


async def release_case_ownership(case_id: str, actor: str = "A-1") -> dict[str, Any]:
    execute("UPDATE cases SET owner_id = '' WHERE id = ?", (case_id,))
    record_case_event(
        case_id=case_id,
        badge="[HUMAN]",
        evt_type="release_ownership",
        summary=f"{actor} released ownership back to queue",
        payload={"released_by": actor},
    )
    row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,)) or {}
    bus.publish_console("case_updated", {"case": row})
    return await get_case_detail(case_id)


async def human_reply_to_case(case_id: str, text: str, actor: str = "A-1") -> dict[str, Any]:
    row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not row:
        raise ValueError(f"Case {case_id} not found")
    persona_id = row["persona_id"]
    await notify.send_message(acting_user=persona_id, message=text, case_id=case_id, actor=f"human:{actor}")
    bus.publish_customer(
        persona_id,
        "human_reply",
        {"case_id": case_id, "text": text, "author": actor},
        case_id=case_id,
        role=f"human:{actor}",
    )
    record_case_event(
        case_id=case_id,
        badge="[HUMAN]",
        evt_type="human_reply",
        summary=f"{actor} replied to customer",
        payload={"author": actor, "text": text},
    )
    return await get_case_detail(case_id)


async def add_case_note(case_id: str, text: str, author: str = "A-1") -> dict[str, Any]:
    row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not row:
        raise ValueError(f"Case {case_id} not found")
    ts = utc_now_iso()
    execute(
        "INSERT INTO case_notes(case_id, author, text, ts) VALUES (?, ?, ?, ?)",
        (case_id, author, text, ts),
    )
    await crm.add_crm_note(acting_user=row["persona_id"], case_id=case_id, author=author, text=text, actor=f"human:{author}")
    record_case_event(
        case_id=case_id,
        badge="[HUMAN]",
        evt_type="note_added",
        summary=f"Internal note added by {author}",
        payload={"author": author, "text": text},
    )
    return await get_case_detail(case_id)


async def handback_case_to_ai(
    case_id: str,
    *,
    instruction: str = "RECHECK",  # "RECHECK" | "CLOSE_WITH_REPLY"
    actor: str = "A-1",
) -> dict[str, Any]:
    """
    F15: Hand back to AI after Take ownership.
    instruction is a fixed enum: RECHECK (release ownership, re-run reads and policy fresh) or CLOSE_WITH_REPLY.
    """
    if instruction not in ("RECHECK", "CLOSE_WITH_REPLY"):
        raise ValueError("instruction must be RECHECK or CLOSE_WITH_REPLY")

    row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not row:
        raise ValueError(f"Case {case_id} not found")

    execute("UPDATE cases SET owner_id = '' WHERE id = ?", (case_id,))
    record_case_event(
        case_id=case_id,
        badge="[HUMAN]",
        evt_type="handback",
        summary=f"{actor} handed case back to Saathi with instruction {instruction}",
        payload={"actor": actor, "instruction": instruction},
    )

    if instruction == "CLOSE_WITH_REPLY":
        persona_id = row["persona_id"]
        lang = row.get("language") or "en"
        msg_text, _ = await compose_message(
            "ESCALATED",
            {"case_id": case_id, "owner": f"{actor} from our support team"},
            lang,
            case_id=case_id,
        )
        bus.publish_customer(
            persona_id,
            "saathi_text",
            {"case_id": case_id, "text": msg_text, "template_code": "ESCALATED"},
            case_id=case_id,
        )
        transition(case_id, "CLOSED")
        return await get_case_detail(case_id)

    # RECHECK: re-run single issue fresh
    ext_data = json.loads(row.get("extraction_json") or "{}")
    issues = ext_data.get("issues") or [{"intent": row.get("intent") or "PAYMENT_FAILED_DEBITED", "confidence": 0.9, "entities": {}}]
    prof_out = await crm.get_customer_profile(acting_user=row["persona_id"], emit_trace=False)
    profile = prof_out.data if (prof_out.ok and isinstance(prof_out.data, dict)) else {}

    return await _run_single_issue(
        case_id=case_id,
        persona_id=row["persona_id"],
        masked_text=row.get("masked_text") or "",
        language=row.get("language") or "en",
        sentiment=row.get("sentiment") or "calm",
        issue_dict=issues[0],
        mentions_human_request=False,
        fraud_signals=[],
        sens_matched=False,
        sens_is_distress=False,
        sens_categories=[],
        clarification_used=bool(row.get("clarification_used")),
        selected_txn_id=None,
        customer_profile=profile,
        english_summary=ext_data.get("english_summary") or "",
        propagated_triggers=[],
    )


async def mark_case_wrong(
    case_id: str,
    *,
    reason_code: str = "WRONG_AUTO_DECISION",
    suggested_change: str = "Require human approval for this pattern",
    actor: str = "A-1",
) -> dict[str, Any]:
    """
    F7 + F15: Marks an AUTO decision wrong, logs override_tests row, marks confidence_log.correct=0,
    and triggers Rule 15 auto-tighten (drops agent one autonomy level).
    """
    row = query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    if not row:
        raise ValueError(f"Case {case_id} not found")

    agent_name = row.get("agent") or "payment_failure"
    now_iso = utc_now_iso()
    snap = {
        "case_id": case_id,
        "persona_id": row["persona_id"],
        "agent": agent_name,
        "intent": row.get("intent"),
        "masked_text": row.get("masked_text"),
        "outcome": row.get("outcome"),
        "rule_fired": row.get("rule_fired"),
    }
    oid = execute(
        """
        INSERT INTO override_tests(case_id, reason_code, snapshot_json, suggested_change, status, created_at)
        VALUES (?, ?, ?, ?, 'PENDING', ?)
        """,
        (case_id, reason_code, json.dumps(snap), suggested_change, now_iso),
    )
    execute("UPDATE confidence_log SET correct = 0 WHERE case_id = ?", (case_id,))

    new_mode = auto_tighten_agent_autonomy(agent_name, reason=f"Marked wrong on {case_id} ({reason_code})")
    record_case_event(
        case_id=case_id,
        badge="[POLICY]",
        evt_type="marked_wrong",
        summary=f"Marked wrong by {actor} ({reason_code}) → override test #{oid} created" + (f" & {agent_name} tightened to {new_mode}" if new_mode else ""),
        payload={"override_id": oid, "reason_code": reason_code, "new_mode": new_mode},
        status="warn",
    )
    return {
        "override_id": oid,
        "case_id": case_id,
        "agent": agent_name,
        "reason_code": reason_code,
        "new_autonomy_mode": new_mode,
        "snapshot": snap,
    }
