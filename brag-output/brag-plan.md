# Brag Plan: Saathi — Autonomous AI Customer-Service Teammate

## What is this app?
Saathi is an autonomous AI customer-service teammate for high-velocity digital payments (UPI, Wallets, Soundbox) that doesn't just generate text answers—it investigates isolated microservice databases, verifies NPCI switch states, executes idempotent financial actions across systems, and collaborates alongside human supervisors with zero financial hallucination.

## The angle
**"Chatbots give excuses. AI Teammates resolve the ledger."**
When a distressed customer writes *"Mera ₹1,200 kat gaya par dukandaar ko nahi mila!"*, standard LLMs reply with polite boilerplate: *"I understand your frustration, please wait 3-5 days."* Saathi investigates the core banking ledger, checks the switch status, evaluates statutory RBI reversal policies, initiates an idempotent ₹1,200 refund, verifies read-after-write integrity, and replies in natural, reassuring Hinglish in 400ms.

## Hook (first 2-3 seconds)
A stark, relatable customer crisis in messy Hinglish: *"Mera ₹1,200 kat gaya!"* contrasted against the frustrating generic chatbot response *"Please contact support"*. A pulsing red alert: `[STUCK: 0 ACTIONS TAKEN]`. Then a clean, high-tech cut on beat 3.70s as Saathi's 7-layer defense shield takes over.

## Key moments (the middle)
- **Multi-System Ledger Investigation**: Simultaneous verification across `ledger.db`, NPCI bank switch, and refunds database.
- **Pure Deterministic Python Decisions**: The LLM extracts intents and rewords templates, but Python code decides amounts and actions. Zero chance of hallucinated money.
- **Amber Lane Co-Pilot Collaboration**: When high-value cases (e.g. ₹8,400 > ₹5,000 cap) exceed autonomy thresholds, Saathi doesn't dump raw transcripts—it presents human supervisors with pre-investigated, structured handoff packets for 1-click authorization.
- **Verifiable Proof**: 35/35 adversarial scenarios passed, 100% policy compliance, 0 financial leaks.

## Outro / punchline
"Don't just answer questions. Get the job done."
Final lockup: **Saathi — The Autonomous FinTech Teammate**. Built for Paytm • Powered by Sarvam AI.

## User flow worth showing
1. **Entry**: Customer voice/text complaint in Hinglish with PII/secret masking.
2. **Key Action**: Autonomous cross-system investigation & idempotent refund execution in 400ms.
3. **Co-Pilot Escalation**: High-value supervisor review with 1-click approval.

## Tone
- Preset: `polished`
- Creative direction: `premium fintech launch film`
- Interpretation: Confident, fast-paced, high visual contrast, crisp typographic motion, and zero corporate fluff.

## Format: landscape — 1920x1080
## Duration: 20.0 seconds (600 frames @ 30fps)

## Visual identity (from the project)
- Background: `#0B0F19` (Deep Obsidian Navy)
- Surface Cards: `#151D2F` with border `#24324D`
- Primary Brand Accent: `#00BAF2` (Paytm Cyan) & `#0F4A8A` (Paytm Deep Blue)
- Success Green: `#00C48C` / `#10B981`
- Warning Amber: `#F59E0B`
- Text Primary: `#FFFFFF`
- Text Secondary: `#94A3B8`
- Display Font: `Segoe UI, Inter, system-ui, sans-serif`

## Share copy (draft)
Chatbots give excuses. AI Teammates resolve the ledger. Meet Saathi: the autonomous fintech teammate that investigates, refunds, and co-pilots in 400ms.

## Audio direction
- Role: Rhythmic electronic corporate drive with tactile UI sound effects.
- Music: `happy-beats-business-moves-vol-11-by-ende-dot-app.mp3` (114.84 BPM)
- Music treatment: Starts at 0.0s, ducks slightly during multi-system ledger scan, swells into final proof, fades smoothly at 19.5s.
- SFX posture: Motion-matched UI clicks, card slide on ledger query, crisp glass ping on verified refund completion.

## Storyboard

### Scene 1 — The Problem: Excuses vs Reality — 3.7s (0.0s - 3.7s)
- **Visual**: Dark screen. Customer chat bubble in messy Hinglish: *"Mera ₹1,200 kat gaya par dukandaar ko nahi mila! Emergency hai!"*
- **Action**: Conventional bot replies: *"I understand your frustration. Please wait 3-5 business days."* Red badge pulses: `[STATUS: PENDING • NO RESOLUTION]`.
- **Audio**: Low intro bed. Soft typewriter/click SFX. Hard beat drop at 3.70s.
- **Transition**: Fast snap zoom & dark wipe.

### Scene 2 — The Solution: Multi-System Execution — 4.2s (3.7s - 7.9s)
- **Visual**: Saathi logo & title: *"AI Teammates don't just respond. They take action."*
- **Action**: 3 backend telemetry cards animate into view:
  1. `[LEDGER.DB] Found TXN-1004b: ₹1,200 FAILED (DEBITED)`
  2. `[NPCI SWITCH] Bank Gateway: Confirmed Debit (HDFC)`
  3. `[POLICY ENGINE] Auto-Cap ₹5,000 → Green Lane AUTO-REFUND`
- **Audio**: Driving 114 BPM rhythm kicks in. Distinct UI tactile clicks for each card reveal.

### Scene 3 — Instant Resolution & Verification — 4.7s (7.9s - 12.6s)
- **Visual**: Verified Action Card locks in:
  - `Refund Issued: RF-3004 (₹1,200)`
  - `Bank Reference: RRN-482019924`
  - `Read-After-Write: [VERIFIED ✓] Idempotency Key Locked`
  - Reassurance in natural Hinglish: *"Aapka ₹1,200 refund initiate ho chuka hai. Paisa 24 ghante mein aapke account mein aa jayega."*
- **Audio**: Satisfying high-clarity success chime. Music continues upbeat drive.

### Scene 4 — Human Co-Pilot Collaboration — 4.2s (12.6s - 16.8s)
- **Visual**: *"What about high-value edge cases?"*
- **Action**: Split view into **Agent Co-Pilot Workspace**.
  - Case `C-4091` (₹8,400 Sharma Furnitures > ₹5,000 cap).
  - Amber Lane structured handoff packet appears with pre-extracted evidence:
    `[Evidence: Valid Debit ✓ • Zero Fraud Signals ✓ • Confidence: 0.94]`
  - Supervisor clicks **[1-Click Approve]** → Instant closed-loop execution.
- **Audio**: Card slide SFX + confirmation switch click.

### Scene 5 — The Proof & Outro — 3.2s (16.8s - 20.0s)
- **Visual**: 3 hero metrics animate in:
  - `35 / 35 Benchmark Scenarios (100% Pass)`
  - `400ms Average Resolution Latency`
  - `₹0 Hallucinated Money (Deterministic Python)`
- **Punchline**:
  **Saathi**
  *The Autonomous AI Teammate for FinTech*
  `Built for Paytm • Powered by Sarvam AI`
- **Audio**: Final musical resolution with gentle fadeout at 19.8s.
