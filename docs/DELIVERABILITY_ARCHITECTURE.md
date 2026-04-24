# Deliverability and reputation layer

## Purpose

A **safety layer** above the campaign scheduler and SMTP/Gmail send paths. It does not replace:

- Gmail Postmaster Tools / workspace admin policies  
- DNS (SPF/DKIM/DMARC) and domain authentication  
- Provider bounce handling  

## Implementation (`app/services/deliverability_layer.py`)

| Capability | Behavior |
|------------|----------|
| **Global pause** | If recent aggregate failure rate exceeds threshold, `run_campaign_job` skips sends (`note=deliverability_global_pause`). Admin `run_once` bypasses via `ignore_deliverability_pause=True`. |
| **Pre-send gate** | `evaluate_deliverability_for_send` — bounce window, spam heuristics, reputation composite, warmup caps, optional min gap between sends. |
| **Per-student reputation score** | Derived from `email_health_status`, recent `BOUNCE`/`BOUNCED` rows, and positive reply ratio (not a stored column; recomputed). |
| **Spam-risk score** | Lexical/structural heuristic (length, caps, links, trigger phrases). |
| **Warmup** | Tighter daily cap for students newer than `DELIVERABILITY_WARMUP_STUDENT_DAYS`. |
| **Domain rotation hint** | `DELIVERABILITY_SENDER_DOMAINS` — informational index for operators (Gmail routing is per-student mailbox). |

## Activation

Default: **off** (`DELIVERABILITY_LAYER` unset). Set `DELIVERABILITY_LAYER=1` in production when DNS and mailboxes are ready.

## Observability

- `GET /admin/deliverability-health` — aggregate 24h sent/failed + pause recommendation.  
- Admin UI surfaces the same payload for operators.

## Tunables (environment)

See `backend/.env.example` — keys prefixed with `DELIVERABILITY_*` and `DELIVERABILITY_GLOBAL_*`.
