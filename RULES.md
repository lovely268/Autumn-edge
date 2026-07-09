# Aurum Edge — Operating Constitution (RULES.md)

> Permanent standing rules for all agents, all sessions, all tasks.
> Read this file before starting ANY task.
> Amended only by owner instruction.

---

## §1 — TRUTH & EVIDENCE

### 1.1 Broker is the single source of truth
When internal state, journal, logs, or memory disagree with Tradovate, the broker wins. Discrepancies are logged and reported to the owner — never silently corrected.

### 1.2 Journal entries from broker fills only
Journal entries (entries, exits, P&L) are written ONLY from confirmed broker fills: orderId + fill price from the Tradovate/STA response. Manual entries with estimated or reconstructed numbers are prohibited.

### 1.3 No claim without artifact
"Verified / deployed / fixed / working" requires pasted evidence: the /health block, the orderId, the log line, the code lines, the fill. A description of evidence is not evidence.

### 1.4 "Cosmetic" is banned as a dismissal
Any residue, anomaly, or unexpected state gets reported with evidence; the owner decides materiality.

### 1.5 Proof must distinguish claim from alternative
A false→false state observation proves nothing — require the flip (e.g., directionally verify both code paths, not just the default).

### 1.6 Definition of done = pasted evidence
No task closes on a claim. Deploys close with the post-deploy /health block. Trades close with orderIds. Fixes close with before/after artifact. A one-line summary without evidence is not done.

---

## §2 — EXECUTION PATH DISCIPLINE

### 2.1 /webhook is not an admin tool
The /webhook endpoint is NEVER used for journaling, testing bookkeeping, or record-keeping. Administrative entries go through direct file/DB writes or dedicated admin paths only. Firing live orders to create paperwork is prohibited.

### 2.2 Exit paths verify position state
Every exit path verifies actual position state before sending orders. If flat: send nothing, log it.

### 2.3 Test failure → pause before investigation
Any test that fails its success criteria → re-pause BEFORE investigating. No resume without the owner's explicit word.

### 2.4 Verification test protocol
- 1-lot sizes only
- Quiet hours only (never 3–6 AM or 9:30–11 AM ET, never with a position open)
- Flatten after test completes
- Journal as TEST/EXCLUDED — never in official stats

### 2.5 Null orderId = failed execution
A missing / null / "undefined" orderId is a FAILED execution — log ERROR, alert owner, max one retry.

---

## §3 — DEPLOY DISCIPLINE

### 3.1 Quiet hours only
Deploys only in quiet hours (outside 3–6 AM and 9:30–11 AM ET). Never with a position open.

### 3.2 Post-deploy verification — mandatory
AT MINIMUM verify on the live /health endpoint:
- `bot_state.paused` — resume/escalate immediately if unexpected (never "noted")
- `balance` — confirm expected value
- `open_positions` — confirm none
- BOOT STATE log line visible in Railway logs

### 3.3 Small, isolated commits
Display changes never share a commit with logic changes.

### 3.4 State-destructive flags are temporary
Flags like RESET_STATE are removed immediately after use. Removal is verified by a second restart proving persistence.

---

## §4 — ACCESS & CREDENTIALS

### 4.1 No new agents with infrastructure access
No new agents receive repository, Railway, broker, or any infrastructure credentials without explicit owner approval. Engineer-2 is the sole code-access route unless the owner changes it.

### 4.2 Secrets never in chat
Agents never ask the owner to share passwords, tokens, or secrets in chat. Secrets are set by the owner directly in the target system (Railway variables, etc.). Never request, echo, or log secret values — only confirm presence/absence.

### 4.3 Owner handles account actions
Owner-side account actions (TradingView, STA, Tradovate, Lucid) are the owner's; agents provide exact click-path instructions, never credentials handling.

### 4.4 No improvisation around blocked paths
Escalate uncertainty; never create agents, credentials, or workarounds to route around process.

---

## §5 — MEASUREMENT INTEGRITY

### 5.1 Measuring week — no changes
No changes to strategy, sizing, gates, Pine Script, or exit model during a measuring period. Measure first, tune after — with data, not anecdotes.

### 5.2 Full journal for every signal
Every signal gets a full journal record. Every blocked signal gets its gate reason logged. Every missed setup observed by the owner gets a MISSED-SETUP entry with timestamp for autopsy.

### 5.3 Test P&L excluded from official stats
Test P&L and accidents are TEST/EXCLUDED — never in official stats. Official stats start at broker-verified zero.

---

## §6 — ALERTING & OWNER COMMUNICATION

### 6.1 Immediate alerts
Owner alert on:
- Any execution without confirmed orderId
- Cap/stop triggers
- Any restart (with post-restart state check)
- Any state/broker disagreement
- Any boot into paused state

### 6.2 Daily EOD summary
Required regardless of activity:
- Signals fired / blocked with reasons
- Trades with lifecycle
- Broker P&L
- /health snapshot
- Anomalies

### 6.3 Escalate uncertainty
Never improvise around a blocked path. If stuck, report with evidence — don't create workarounds.

### 6.4 Owner pre-approval required for state-changing operations
Any task that fires orders, modifies bot state (pause/resume/reset/balance), deploys code, or alters strategy/sizing/gates must have its written plan approved by the owner BEFORE execution. The plan states:
- What will run (exact commands, payloads, endpoints)
- Expected outcome (what "pass" looks like for each step)
- Rollback procedure (how to undo if it fails)

No execution on these categories without explicit owner approval of the specific plan. A plan described in chat after the fact is not approval — approval is given before the first action is taken.

---

## §7 — CODE & DEPLOYMENT

### 7.1 Branch → PR → merge
Feature branches for all changes. PRs reviewed by lead before merge. No direct pushes to master unless explicitly authorized.

### 7.2 Workflow.md governs deploy process
See WORKFLOW.md for deploy verification checklist and branch strategy.

### 7.3 Read this file first
Step zero of every task: read RULES.md. Rules that travel with the work can't be forgotten between sessions.

---

*Established: July 8, 2026. Amended only by owner instruction.*