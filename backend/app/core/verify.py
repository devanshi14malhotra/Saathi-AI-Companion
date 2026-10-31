"""Read-after-write outcome verification (F1 in SPEC_V6 §4)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import cfg_mgr, get_ablate_flags
from app.tools import crm, ledger, refunds
from app.tools.client import ToolOutcome, record_case_event
from app.tools.registry import execute_action


@dataclass
class VerificationResult:
    verified: bool
    status: str  # "VERIFIED" | "MISSING" | "MISMATCH"
    action_name: str
    target_id: str
    attempts: int
    data: dict[str, Any] | None = None
    had_initial_mismatch: bool = False


async def _probe_single(
    *,
    action_name: str,
    args: dict[str, Any],
    write_data: dict[str, Any],
    acting_user: str,
    case_id: str,
) -> tuple[bool, str, str, dict[str, Any] | None]:
    """Returns (ok, status_str, target_id, observed_dict)."""
    if action_name == "initiate_refund":
        refund_id = str(write_data.get("id") or "")
        txn_id = str(args.get("txn_id") or write_data.get("txn_id") or "")
        expected_amt = int(args.get("amount") or write_data.get("amount") or 0)

        res = await refunds.get_refund(
            acting_user=acting_user, refund_id=refund_id, case_id=case_id, emit_trace=False
        )
        if res.ok and isinstance(res.data, dict):
            d = res.data
            if int(d.get("amount", 0)) == expected_amt and d.get("status") in ("INITIATED", "PROCESSING", "COMPLETED"):
                return True, "VERIFIED", refund_id, d
            return False, "MISMATCH", refund_id, d

        # Authoritative check by txn_id before re-writing
        by_txn = await refunds.get_refund_for_txn(
            acting_user=acting_user, txn_id=txn_id, case_id=case_id, emit_trace=False
        )
        if by_txn.ok and isinstance(by_txn.data, list) and by_txn.data:
            d = by_txn.data[0]
            if int(d.get("amount", 0)) == expected_amt and d.get("status") in ("INITIATED", "PROCESSING", "COMPLETED"):
                return True, "VERIFIED", str(d["id"]), d
            return False, "MISMATCH", str(d["id"]), d

        return False, "MISSING", refund_id or txn_id, None

    if action_name == "raise_reconciliation":
        recon_id = str(write_data.get("id") or "")
        res = await refunds.get_reconciliation(
            acting_user=acting_user, recon_id=recon_id, case_id=case_id, emit_trace=False
        )
        if res.ok and isinstance(res.data, dict) and res.data.get("status") == "OPEN":
            return True, "VERIFIED", recon_id, res.data
        return False, "MISSING", recon_id, None

    if action_name == "lock_payment_instrument":
        lock_id = str(write_data.get("id") or "")
        res = await ledger.get_locks(acting_user=acting_user, case_id=case_id, emit_trace=False)
        if res.ok and isinstance(res.data, list):
            for lk in res.data:
                if lk.get("id") == lock_id and lk.get("status") == "ACTIVE":
                    return True, "VERIFIED", lock_id, lk
        return False, "MISSING", lock_id, None

    if action_name == "create_ticket":
        ticket_id = str(write_data.get("id") or "")
        res = await crm.get_ticket(acting_user=acting_user, ticket_id=ticket_id, case_id=case_id, emit_trace=False)
        if res.ok and isinstance(res.data, dict) and res.data.get("status") == "OPEN":
            return True, "VERIFIED", ticket_id, res.data
        return False, "MISSING", ticket_id, None

    return True, "VERIFIED", str(write_data.get("id") or "ok"), write_data


async def verify_and_recover(
    *,
    case_id: str,
    action_name: str,
    args: dict[str, Any],
    write_outcome: ToolOutcome,
    acting_user: str,
    actor: str = "saathi",
) -> VerificationResult:
    write_data = write_outcome.data if isinstance(write_outcome.data, dict) else {}
    ablate = get_ablate_flags()

    if "no_verify" in ablate:
        target_id = str(write_data.get("id") or args.get("txn_id") or "")
        record_case_event(
            case_id=case_id,
            badge="[VERIFY] ✓",
            evt_type="verify",
            summary=f"Outcome verification skipped (no_verify ablation) for {action_name} ({target_id})",
            payload={"action": action_name, "target_id": target_id, "status": "SKIPPED_ABLATION"},
            status="ok",
        )
        return VerificationResult(
            verified=True,
            status="VERIFIED",
            action_name=action_name,
            target_id=target_id,
            attempts=1,
            data=write_data,
        )

    rewrite_max = int(cfg_mgr.thresholds.get("verify_rewrite_max", 2))
    attempts = 1

    ok, status_str, target_id, obs_data = await _probe_single(
        action_name=action_name,
        args=args,
        write_data=write_data,
        acting_user=acting_user,
        case_id=case_id,
    )
    if ok:
        record_case_event(
            case_id=case_id,
            badge="[VERIFY] ✓",
            evt_type="verify",
            summary=f"Read-after-write verified {action_name} → {target_id}",
            payload={"action": action_name, "target_id": target_id, "status": "VERIFIED", "attempts": attempts, "observed": obs_data},
            status="ok",
        )
        return VerificationResult(
            verified=True,
            status="VERIFIED",
            action_name=action_name,
            target_id=target_id,
            attempts=attempts,
            data=obs_data or write_data,
        )

    # First probe failed -> emit red [VERIFY] ✗
    record_case_event(
        case_id=case_id,
        badge="[VERIFY] ✗",
        evt_type="verify",
        summary=f"Outcome verification {status_str} on {action_name} ({target_id}) — initiating recovery",
        payload={"action": action_name, "target_id": target_id, "status": status_str, "attempt": attempts},
        status="error",
    )

    for _ in range(rewrite_max):
        attempts += 1
        rw_out = await execute_action(
            action_name=action_name,
            args=args,
            acting_user=acting_user,
            case_id=case_id,
            actor=actor,
            idempotency_key=write_outcome.idempotency_key,
        )
        if rw_out.ok and isinstance(rw_out.data, dict):
            write_data = rw_out.data

        ok, status_str, target_id, obs_data = await _probe_single(
            action_name=action_name,
            args=args,
            write_data=write_data,
            acting_user=acting_user,
            case_id=case_id,
        )
        if ok:
            record_case_event(
                case_id=case_id,
                badge="[VERIFY] ✓",
                evt_type="verify",
                summary=f"Recovered & verified {action_name} → {target_id} on attempt {attempts}",
                payload={"action": action_name, "target_id": target_id, "status": "VERIFIED", "attempts": attempts, "observed": obs_data},
                status="ok",
            )
            return VerificationResult(
                verified=True,
                status="VERIFIED",
                action_name=action_name,
                target_id=target_id,
                attempts=attempts,
                data=obs_data or write_data,
                had_initial_mismatch=True,
            )

        record_case_event(
            case_id=case_id,
            badge="[VERIFY] ✗",
            evt_type="verify",
            summary=f"Outcome verification still {status_str} on {action_name} ({target_id}) (attempt {attempts})",
            payload={"action": action_name, "target_id": target_id, "status": status_str, "attempt": attempts},
            status="error",
        )

    return VerificationResult(
        verified=False,
        status=status_str,
        action_name=action_name,
        target_id=target_id,
        attempts=attempts,
        data=obs_data,
        had_initial_mismatch=True,
    )
