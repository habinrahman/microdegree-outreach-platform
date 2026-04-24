# Autonomous outreach orchestration (design — future)

## Vision

A **policy layer** that recommends or executes: *which student–HR pair to contact next, when, with which template, when to stop,* and *how to rebalance fairness* — built on existing primitives:

- Priority queue engine (`PRIORITY_*`, `/queue/priority`)  
- Follow-up eligibility (`followup_eligibility`, `/followups`)  
- Reply signals (`reply_tracker`, `reply_classifier`, `EmailCampaign.replied` / `reply_type`)  
- HR opportunity + health scoring (`hr_health_scoring`, scheduler tier filter)  
- Diversity layer (`PRIORITY_DIV_*`)  
- Cooldowns (scheduler HR pause, Gmail auth block cooldown, deliverability global pause)  
- Campaign lifecycle + idempotent worker claims  

## Non-negotiables

1. **Simulation mode** — any autonomous plan must run as **dry-run** first: proposed sends, expected caps, fairness metrics, and **no SMTP**. Persist audit JSON under `AuditLog` or export only.  
2. **Human approval gate** — first production phase: *recommendations only* in UI; operator confirms batches.  
3. **Rate + reputation** — autonomous mode must respect `deliverability_layer` and `email_health_status`.  
4. **Stop conditions** — per-pair caps (existing sequence rules), HR `paused`, student `inactive`, global pause, and explicit **max touches per HR per week** (to be added if product requires).  

## Proposed modules (not all implemented)

| Module | Responsibility |
|--------|----------------|
| `autonomous_state.py` | Snapshot of queue + diversity + cooldown constraints. |
| `autonomous_policy.py` | Scoring: blend priority queue score with exploration and fatigue penalties. |
| `autonomous_simulation.py` | Replay “what if” without mutating `EmailCampaign` except optional shadow rows with `status=cancelled` + `error=simulation` (prefer **no DB writes**). |
| `autonomous_executor.py` | Phase 3: enqueue `scheduled` campaigns only after approval token. |

## API sketch

- `POST /autonomous/simulate` — body: horizon hours, max proposals; response: ranked list + reasons.  
- `POST /autonomous/approve` — body: simulation id + subset; creates or reschedules real campaigns (behind `AUTONOMOUS_OUTREACH=1`).  

## Milestones

1. **Read-only recommendations** in dashboard (uses priority queue + eligibility only).  
2. **Simulation CLI** — `python -m app.scripts.autonomous_simulate` printing JSON plan.  
3. **Approved auto-enqueue** — strict feature flag + audit trail.  

This file is the **source design** until milestones ship in code.
