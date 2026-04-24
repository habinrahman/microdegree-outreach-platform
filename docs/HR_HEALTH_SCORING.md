# HR Health & Opportunity Scoring (Phase 1)

## Goals

- Rank HR contacts with **two explainable scores** and **A/B/C/D tiers**.
- **Health** = deliverability and list hygiene (avoid bounces and bad domains).
- **Opportunity** = responsiveness and positive engagement (prioritize likely replies).

## Data sources

Aggregates are computed from `EmailCampaign` rows linked to each HR (same HR can have many campaigns). Signals:

| Signal | Used in | Notes |
|--------|---------|--------|
| Bounce / delivery failure | Health | Single SQL bucket: `bounce OR delivery_failure OR status in (bounced, failed)` so one campaign is not double-counted. |
| Reply rate | Opportunity | `replied / sent` over window. |
| Positive reply (interview / positive reply_type / reply_status) | Opportunity | Count of campaigns with positive reply signals. |
| `last_contacted_at` | Opportunity | Recency bonus if contacted within 90 days. |
| Cooldown / paused | Health | `hr_contact.cooldown_until` in future → penalty; `paused` → strong penalty toward D. |
| Invalid / suppressed | Health / tier | `is_valid_email`, `is_suppressed` → cap tier at C or force D. |
| Domain heuristic | Health | High send volume to same domain (histogram over HRs in batch) suggests shared / risky domain. |
| Duplicates | Health | Same normalized email on multiple HR rows → small duplicate penalty. |

## Scores (0–100)

### Health (H)

Components (each 0–100 before blend):

1. **Delivery (D_del)**: From bounce ratio `r = failures / max(sent,1)`.
   - `D_del = max(0, 100 - 100 * min(1, r / r_soft))` with `r_soft` from env `HR_HEALTH_BOUNCE_SOFT` (default 0.15).
2. **Hygiene (D_hyg)**: Valid, not suppressed, not paused, cooldown clear → 100; each issue subtracts fixed penalties (clamped 0–100).
3. **Domain (D_dom)**: If domain send count in batch ≥ threshold (`HR_HEALTH_DOMAIN_VOLUME_THRESHOLD`, default 50), apply penalty scaled by volume.

**Formula:** `H = 0.55 * D_del + 0.35 * D_hyg + 0.10 * D_dom` (weights in `hr_health_scoring.py`).

### Opportunity (O)

1. **Reply (O_rep)**: `100 * min(1, reply_rate / reply_target)` with `reply_target` from `HR_OPP_REPLY_RATE_TARGET` (default 0.12).
2. **Positive (O_pos)**: From positive reply count per 100 sends: `100 * min(1, positives_per_100 / pos_target)` with `pos_target` from `HR_OPP_POSITIVE_PER_100_TARGET` (default 2.0).
3. **Recency (O_rec)**: Linear decay from 100 at 0 days since `last_contacted_at` to 0 at 90+ days.

**Formula:** `O = 0.45 * O_rep + 0.40 * O_pos + 0.15 * O_rec`.

## Tier mapping

Default thresholds (override via env):

| Tier | Rule (simplified) |
|------|-------------------|
| **A** | Not invalid/suppressed; `H ≥ HR_TIER_A_HEALTH_MIN` (default 70) and `O ≥ HR_TIER_A_OPP_MIN` (default 55). |
| **B** | Not D; `H ≥ HR_TIER_B_HEALTH_MIN` (default 50) and `O ≥ HR_TIER_B_OPP_MIN` (default 35). |
| **C** | Everything else that is not forced to D. |
| **D** | Invalid email, suppressed, paused, or `H < HR_TIER_D_HEALTH_MAX` (default 25) with high bounce pressure, or very low hygiene. |

`reasons[]` on each score lists human-readable strings (e.g. “High bounce rate (18%)”, “In cooldown until …”, “Strong reply history”).

## API

- `GET /hr-contacts?include_health=1&tier=A` — list with optional embedded scores/tier/reasons.
- `GET /hr-contacts/{id}/health` — full breakdown (`health`, `opportunity`, `tier`, component scores, reasons).
- Bulk assignment: optional `min_hr_tier` (`A` | `B` | `C` | `D`); rejects HRs below threshold in `rejected_low_tier`.

## Scheduler

- Env `SCHEDULER_MIN_HR_TIER` (e.g. `B`): after computing due sends, drops rows whose HR tier is below the minimum. Empty = disabled (no behavior change).

## Tuning & risks

- **Cold start:** HRs with few sends get noisy rates; tier defaults lean conservative (C until proof).
- **Volume domains:** Histogram is per **batch** of IDs; threshold is relative to that batch, not global corpus.
- **Time window:** Campaign stats use recent window (`HR_HEALTH_STATS_DAYS`, default 180); tune for seasonality.
- **Positive reply definition:** Must stay aligned with product definition of “positive” (interview + explicit positive reply fields).
- **Scheduler coupling:** Tier filter adds one batched health query per scheduler run when enabled; monitor DB load at scale.
