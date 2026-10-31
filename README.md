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

## Quickstart Commands (Windows PowerShell & Unix / Mac)

### 1. Start the Backend API Server (`http://127.0.0.1:8000`)
```bash
# Unix / Mac:
PYTHONPATH=backend python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Windows PowerShell:
.\make.ps1 backend
```

### 2. Start the Interactive Streamlit Workspace (`http://127.0.0.1:8501`)
```bash
# Unix / Mac:
PYTHONPATH=backend streamlit run streamlit_app/app.py

# Windows PowerShell:
.\make.ps1 streamlit
# or:
.\make.ps1 frontend
```

### 3. Run Unit & Integration Tests (`pytest`)
```bash
# Unix / Mac:
PYTHONPATH=backend python3 -m pytest backend/tests -v

# Windows PowerShell:
.\make.ps1 test
```

### 4. Run Canonical Scenarios (`S1`–`S35`, 66 Cases)
```bash
# Unix / Mac:
PYTHONPATH=backend LLM_PROVIDER=stub SAATHI_ENV=eval python3 -m app.eval.harness --cmd scenarios

# Windows PowerShell:
.\make.ps1 scenarios
```

### 5. Run Full Trust Evaluation Harvest (`/trust` Proof Suite)
```bash
# Unix / Mac:
PYTHONPATH=backend LLM_PROVIDER=stub SAATHI_ENV=eval python3 -m app.eval.harness --cmd trust

# Windows PowerShell:
.\make.ps1 trust
```

### 6. Reset All 5 SQLite Databases to Canonical Seed
```bash
# Unix / Mac:
PYTHONPATH=backend python3 -m app.eval.harness --cmd reset

# Windows PowerShell:
.\make.ps1 reset
```

---

## Key Views in the Streamlit Web Application (`http://127.0.0.1:8501`)

1. **💬 1. Customer Helpdesk & Voice Assistant**:
   - Live customer dispute resolution supporting English, Hindi, and Hinglish.
   - Live Microphone Voice STT (`saaras:v1`) and Speech Synthesis TTS (`bulbul:v3`) via Sarvam AI API.
   - Dynamic 3-Part Resolution Cards (What Saathi Found / What Saathi Did / What Happens Next).
   - Customer-safe action receipt timeline (F14) and deep technical orchestrator traces.

2. **🛡️ 2. Human Agent Co-Pilot (Supervisor Inbox)**:
   - Amber-lane high-value financial approval queue (>₹5,000 cap, velocity holds).
   - Structured Handoff Packets with verified facts, diagnosis, and policy reasoning.
   - 1-Click Authorize & Execute routed through the authoritative orchestrator with read-after-write verification (`[VERIFY] ✓`) and idempotency.

3. **💳 3. Live Transactions & Ledger**:
   - Real-time explorer across UPI, BillPay, and Merchant rails in `ledger.db`.
   - Real-time active refund records in `refunds.db`.
   - Interactive transaction entry form to test dispute resolution against new banking records.

4. **⚡ 4. Operations War-Room & Teammate Superpowers**:
   - Partner Bank Outage Monitor with canonical `bank_code|rail` signatures.
   - **Dry-Run Impact Preview** (Beat 3 · It Acts Before Complaints): inspects affected users and financial exposure without mutating state.
   - **1-Click Proactive Outage Resolution**: issues verified bulk refunds across affected cohorts automatically.
   - **Time-Travel Machine (+24h / +73h)**: triggers RBI TAT delayed reversal compensations (₹100/day).
   - **Controlled Chaos Injection**: arms phantom 201 writes and 504 timeouts to demonstrate closed-loop read-after-write verification recovery live.
   - **Autonomy Dials & Emergency Kill-Switches**: live persistence to `config_state` with full audit logs.

5. **📊 5. Empirical Trust, Proof Suite & Telemetry**:
   - **3-Arm Comparative Benchmark**: Arm A (FAQ Bot) vs Arm B (Human Baseline) vs Arm C (Saathi Autonomous Teammate, 100% pass rate, 95% Wilson CI [0.9286, 1.0]).
   - **Safety-by-Construction Ablations**: `no_verify`, `no_policy`, `no_guard`, `no_idem`, `no_gate`.
   - **96-Run Adversarial Red-Team Matrix**: Protected (96/96 passed, 0 critical failures) vs Unprotected (58.3% Attack Success Rate).
   - **Language Parity & ECE Calibration**: English, Hinglish, Hindi parity comparisons and Expected Calibration Error (<0.03).
   - **Live Case Decision & Microservice Verification Logs**.

6. **⚙️ 6. System & Model Health**:
   - Environment credentials, dual-account Sarvam AI credit pooling, live ping latency tests, and provider switcher (Sarvam-105B LLM vs local offline deterministic stub).

