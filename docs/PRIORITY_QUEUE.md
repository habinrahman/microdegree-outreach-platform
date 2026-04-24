# Priority outreach queue (Phase 1)

Read-only ranked recommendations for **which student–HR pair to work next**. Does **not** send email, mutate campaigns, or replace `campaign_scheduler`.

## Ranking model

Each **active assignment** (student–HR) becomes one candidate. Inputs:

| Signal | Role |
|--------|------|
| Follow-up engine | `compute_followup_eligibility_for_pair` — due follow-ups, waiting, stopped, paused. |
| HR health / tier | `compute_health_for_hr_ids` — health, opportunity, A/B/C/D. **D → suppress.** |
| Campaign rows | Next due `pending`/`scheduled` send, future `scheduled_at`, warm reply types. |
| Student | Active, demo, OAuth/SMTP readiness, `email_health_status`. |
| Cooldown / safety | HR `paused` / `paused_until`, student Gmail auth cooldown (10m), over-contact frequency, blocked HR list. |

## Scoring formula

Let normalized weights `wf + wopp + whealth + wstu + wwarm = 1` (from env defaults, renormalized if overridden):

```
blended = wf * followup_urgency
       + wopp * opportunity_score
       + whealth * health_score
       + wstu * student_priority
       + wwarm * warm_lead

priority_score = clamp( blended - 0.35 * cooldown_penalty, 0, 100 )
```

- **followup_urgency**, **student_priority**, **warm_lead**, **cooldown_penalty** are each on a **0–100** scale; HR scores reuse **health_score** / **opportunity_score** (0–100).  
- **Cooldown penalty** is **not** folded into HR health again (avoids double counting bounce/reputation with follow-up urgency).

Env tunables (examples):

- `PRIORITY_W_FOLLOWUP`, `PRIORITY_W_HR_OPP`, `PRIORITY_W_HR_HEALTH`, `PRIORITY_W_STUDENT`, `PRIORITY_W_WARM`
- `PRIORITY_OVER_CONTACT_DAYS`, `PRIORITY_OVER_CONTACT_SOFT`, `PRIORITY_OVER_CONTACT_HARD`

## Queue buckets

| Bucket | Meaning |
|--------|---------|
| `SEND_NOW` | Due `pending`/`scheduled` campaign for the pair. |
| `FOLLOW_UP_DUE` | Follow-up engine says `DUE_NOW`. |
| `WARM_LEAD_PRIORITY` | Strong HR + approaching follow-up or high opportunity with waiting sequence. |
| `WAIT_FOR_COOLDOWN` | Paused HR, student cooldown, future schedule, or interval wait. |
| `LOW_PRIORITY` | No immediate action. |
| `SUPPRESS` | Unsafe or stopped (D-tier, invalid, blocked list, replied/bounce/completed stop, paused thread, flagged student). |

**Stable rank order (bucket key, then score):** `FOLLOW_UP_DUE` sorts before `SEND_NOW` (ongoing follow-up thread before a due scheduled touch). `WARM_LEAD_PRIORITY` before `LOW_PRIORITY`. Stopped pairs are always `SUPPRESS` and never `SEND_NOW` / `FOLLOW_UP_DUE`.

`recommended_action` and `recommendation_reason[]` are chosen to **match** the bucket (no “send now” on `SUPPRESS`).

## APIs

- `GET /queue/priority` — ranked rows + summary. Query: `bucket`, `student_id`, `tier`, `only_due`, `limit`, `include_demo`.
- `GET /queue/priority/summary` — aggregates only (same filters; `limit` caps scan for very large DBs).
- `GET /queue/priority/scheduler-hook` — documents `SCHEDULER_USE_PRIORITY_QUEUE`.

## Scheduler hook (design only)

- `SCHEDULER_USE_PRIORITY_QUEUE` in `app.config` (default **false**).  
- Phase 1: **not consumed** by `campaign_scheduler.py`. Future: optionally sort `due` by `priority_score` after existing filters.

## Movement / “what changed?”

Each row includes `signal_fingerprint` (hash of bucket, follow-up status, tier, next touch, rounded score, campaign id). The UI can store a snapshot in `sessionStorage` and diff ranks/fingerprints on refresh.

## Risks / tuning

- Large assignment counts → each request scans at most **`PRIORITY_QUEUE_MAX_ASSIGNMENTS_SCAN`** active assignments (default 4000), most recent `assigned_date` first. Summary/totals are **within that window** only.
- HR health for the queue skips the global domain histogram (`skip_domain_histogram=True`) for speed; tier/scores still reflect bounce/reply/validity. Use `GET /hr-contacts/{id}/health` for full domain-peer detail.
- **Student Gmail auth cooldown** (10m window from a recent `gmail_auth_block` pause) is not part of `compute_followup_eligibility_for_pair`. The queue maps **follow-up due + cooldown** to `WAIT_FOR_COOLDOWN` so the bucket matches what the scheduler will skip.
- **D-tier = suppress** is strict; ops may want “show D without hiding” — use tier filter or separate product flag later.
- Weights and over-contact thresholds should be calibrated against real send volume.

## Phase 2 — Diversity & exploration (layered re-rank)

`GET /queue/priority?diversified=true` keeps the **same base scores and buckets**, then applies:

- **Per-HR cap** in the visible window (`PRIORITY_DIV_HR_CAP`, default 2).
- **Per-student floor** (best effort, `PRIORITY_DIV_STUDENT_FLOOR`, default 1).
- **Exploration tail** (~`PRIORITY_DIV_EXPLORATION_PCT`, default 0.075): under-contacted / low-urgency promising rows tagged **`EXPLORATION`** (never `SUPPRESS`).
- **Optional MMR** among `SEND_NOW` / `FOLLOW_UP_DUE` only (`PRIORITY_DIV_MMR_ENABLED`, `PRIORITY_DIV_MMR_LAMBDA`, `PRIORITY_DIV_MMR_WINDOW`).

Response includes **`diversity_metrics`** (concentration, exploration share, starvation hints, deltas vs standard when diversified). If the HR cap binds, **`returned_count` may be &lt; `requested_limit`**.
