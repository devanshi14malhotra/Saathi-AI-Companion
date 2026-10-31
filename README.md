# Saathi v6.0 — Autonomous AI Customer-Service Teammate

**Problem Statement**: *3. Autonomous AI Teammates — Build AI teammates that don't just respond; they get the job done.*

Saathi v6.0 is an end-to-end autonomous AI customer-service teammate for digital payments and merchant operations. Rather than acting as a read-only FAQ chatbot, Saathi investigates across isolated transactional systems (`LEDGER`, `REFUNDS`, `CRM`, `NOTIFY`), enforces a deterministic 7-rule policy engine, executes real state-mutating financial actions with idempotency and post-write verification, schedules closed-loop T+24h/T+72h follow-ups, detects fleet-wide bank outages across cases, and collaborates bi-directionally with human operators.

---

## Core Architectural Invariants

1. **LLM Never Decides Money or Policy (Rule 4)**:
   - The language model (`stub` offline deterministic extractor/rewriter or `sarvam` live API) is restricted strictly to:
     1. Structured intent/entity extraction from PII-masked text.
     2. Natural-language phrasing of verified templates, checked by `post_check_rewrite` so zero fabricated amounts, IDs, or dates can ever reach the customer.
   - All routing, eligibility checks, refund amounts, and policy outcomes (`AUTO`, `APPROVE`, `ESCALATE`, `BLOCK`) are computed in deterministic Python code from verified `LEDGER` records.
2. **5 Isolated SQLite Databases (WAL Mode)**:
   - `data/core.db`: Orchestrator cases, state transitions, execution traces, approvals, audit logs, follow-up checks, incidents, confidence calibration logs, override regression tests, and stored evaluation runs.
   - `data/ledger.db`: Downstream `LEDGER` microservice (`:8001`) storing UPI transactions, bank statuses, and merchant settlements.
   - `data/refunds.db`: Downstream `REFUNDS` microservice (`:8002`) handling idempotent refund writes, RRN generation, and bank reconciliations.
   - `data/crm.db`: Downstream `CRM` microservice (`:8003`) storing customer profiles, KYC holds, escalated tickets, and structured handoff packets.
   - `data/notify.db`: Downstream `NOTIFY` microservice (`:8004`) dispatching customer receipts and outage resolution notifications.
3. **Closed-Loop Outcome Verification (`[VERIFY] ✓`)**:
   - Every write tool call (`initiate_refund`, `raise_reconciliation`, `lock_payment_instrument`, `create_bug_ticket`) is followed by an independent read-back verification against the downstream service.
   - Catches **phantom 200/201 responses** (where a service returns HTTP 201 without persisting a row) and **dropped HTTP responses** (recovering via idempotency key without double-refunding).

---

## Quickstart Commands (Windows PowerShell & Unix Make)

### 1. Start the Backend Server (`http://127.0.0.1:8000`)
```powershell
.\make.ps1 backend
```

### 2. Start the Frontend Web UI (`http://127.0.0.1:5173`)
```powershell
.\make.ps1 frontend
```

### 3. Run Unit & Integration Tests (`pytest`)
```powershell
.\make.ps1 test
```

### 4. Run Canonical Scenarios (`S1`–`S35`)
```powershell
.\make.ps1 scenarios
```

### 5. Run Full Trust Evaluation Harvest (`/trust` Proof Suite)
```powershell
.\make.ps1 trust
```

### 6. Reset All 5 SQLite Databases to Canonical Seed
```powershell
.\make.ps1 reset
```

---

## Key Views in the Web Application

- **Workspace Split View (`/showcase`)**:
  - Top **Guided Verification Path** bar with **90s Judge Path (5 Beats)** and **Full Story (8 Steps)**.
  - Left pane: **Customer Support Channel** with persona switcher (`U-101` Aarav Sharma, `U-102` Priya Nair, `U-103` Meera Krishnan, `M-201` Ramesh Kirana Store, `M-202` QuickBite Cafe), proactive scan (`F1`), voice fixtures (`F16`), clarify chips (`S16`), and customer-verifiable audit receipts (`F14`).
  - Right pane: **Execution Trace** (step-by-step `[MASK]`, `[GUARD]`, `[READ]`, `[POLICY]`, `[WRITE]`, `[VERIFY] ✓` timeline + 4-signal confidence breakdown), **12-Second Decision Card & Approvals** (`Why you?` line, 1-click Approve / Edit & Approve / Reject with reason code, Take Ownership, Hand Back to AI `RECHECK` / `CLOSE_WITH_REPLY`, Mark Wrong `Rule 15`), and **Live Systems Grid** (live SQLite rows across all 4 downstream services).
- **Ops Console & Fleet Command Center (`/console`)**:
  - 4 Traffic-Light Decision Lanes (`ACT_NOW`, `WAIT_AND_VERIFY`, `APPROVAL_QUEUE`, `HUMAN_ONLY`).
  - Cross-Case Bank Outage Detection (`F4`) with Dry-Run Impact Preview, Public Deflection Banner publishing, and 1-click Bulk Resolution.
  - Closed-Loop Follow-Up Scheduler (`F2`) and Earned Autonomy Graduation (`F7`) + Emergency Money-Action Kill-Switch.
- **Empirical Trust & Proof Report (`/trust`)**:
  - Renders 100% live metrics from stored evaluation runs in `core.db` (Rule 17): 95% Wilson confidence intervals, 3-Arm comparison (`Arm A FAQ Bot`, `Arm B Human Baseline`, `Arm C Saathi`), Safety-by-Construction Ablation table (`no_verify`, `no_policy`, `no_guard`, `no_idem`, `no_gate`), interactive Counterfactual Policy What-If Simulator, 4-Signal Confidence Reliability Diagram (`ECE`), Multilingual Parity (`EN` / `Hinglish` / `HI`), and 96-run Adversarial Red-Team Matrix (32 base attacks × 3 mutators).

