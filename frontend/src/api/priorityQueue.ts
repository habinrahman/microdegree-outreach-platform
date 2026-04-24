import { safeGet } from "@/api/api";

export type QueueBucket =
  | "SEND_NOW"
  | "FOLLOW_UP_DUE"
  | "WARM_LEAD_PRIORITY"
  | "WAIT_FOR_COOLDOWN"
  | "SUPPRESS"
  | "LOW_PRIORITY";

export type PriorityQueueSummary = {
  send_now_count: number;
  followup_due_count: number;
  warm_lead_priority_count: number;
  wait_for_cooldown_count: number;
  suppressed_count: number;
  low_priority_count: number;
  avg_priority_score: number | null;
  total_candidates: number;
};

export type PriorityStudentBrief = {
  id: string;
  name: string;
  gmail_address: string;
  status?: string;
  email_health_status?: string;
  is_demo?: boolean;
};

export type PriorityHRBrief = {
  id: string;
  name: string;
  company: string;
  email: string;
  is_valid?: boolean;
  status?: string | null;
};

export type FollowUpDiagnosticSnapshot = {
  status: string | null;
  eligible_for_followup: boolean;
  blocked_reason: string | null;
  next_followup_step: number | null;
  next_template_type: string | null;
  due_date_utc: string | null;
  days_until_due: number | null;
  paused: boolean;
  send_in_progress: boolean;
  initial_or_anchor_campaign_id: string | null;
};

/** Nested explainability payload from GET /queue/priority (read-only diagnostics). */
export type DecisionDiagnostics = {
  decision_computed_at_utc: string;
  last_pair_activity_utc: string | null;
  queue_bucket: string;
  bucket_rationale: string;
  recommended_action: string;
  why_ranked: string[];
  why_suppressed: string[];
  follow_up: FollowUpDiagnosticSnapshot;
  cooldown: {
    summary_line: string | null;
    penalty_reasons: string[];
    cooldown_penalty_score: number;
  };
  scoring: {
    priority_score: number;
    blended_before_cooldown_subtraction: number;
    cooldown_subtracted: number;
    formula: string;
    axes: { name: string; value: number; weight: number; weighted: number }[];
    top_components: { name: string; value: number; weight: number; weighted: number }[];
  };
  why_not_sent: {
    is_suppressed: boolean;
    summary: string;
    blockers: string[];
    all_signal_lines: string[];
    follow_up_snapshot: FollowUpDiagnosticSnapshot;
    operator_note: string;
  } | null;
  waiting_or_deferred: {
    bucket_is_wait: boolean;
    negative_signals: string[];
    summary: string;
  } | null;
};

export type PriorityQueueRow = {
  student: PriorityStudentBrief;
  hr: PriorityHRBrief;
  priority_score: number;
  priority_rank: number;
  recommendation_reason: string[];
  recommended_action: string;
  urgency_level: string;
  queue_bucket: QueueBucket;
  hr_tier: string;
  health_score: number;
  opportunity_score: number;
  dimension_scores: Record<string, number>;
  next_best_touch: string | null;
  cooldown_status: string | null;
  followup_status: string | null;
  campaign_id: string | null;
  signal_fingerprint: string;
  ranking_mode?: string;
  ranking_slot_type?: string | null;
  diversity_note?: string | null;
  decision_diagnostics?: DecisionDiagnostics;
};

export type PriorityQueueResponse = {
  computed_at_utc: string;
  summary: PriorityQueueSummary;
  rows: PriorityQueueRow[];
  diversity_metrics?: Record<string, unknown>;
};

const STORAGE_KEY = "priorityQueuePrev.v1";

export type StoredQueueEntry = { rank: number; fingerprint: string };

export function loadPrevQueueMap(): Record<string, StoredQueueEntry> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const p = JSON.parse(raw) as unknown;
    return p && typeof p === "object" ? (p as Record<string, StoredQueueEntry>) : {};
  } catch {
    return {};
  }
}

export function saveQueueSnapshot(rows: PriorityQueueRow[]) {
  const m: Record<string, StoredQueueEntry> = {};
  for (const r of rows) {
    const k = `${r.student.id}:${r.hr.id}`;
    m[k] = { rank: r.priority_rank, fingerprint: r.signal_fingerprint };
  }
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(m));
}

export function rowPairKey(r: PriorityQueueRow) {
  return `${r.student.id}:${r.hr.id}`;
}

export function fetchPriorityQueue(params?: {
  bucket?: string;
  student_id?: string;
  tier?: string;
  only_due?: boolean;
  limit?: number;
  include_demo?: boolean;
  diversified?: boolean;
}): Promise<PriorityQueueResponse> {
  return safeGet<PriorityQueueResponse>("/queue/priority", params as Record<string, unknown> | undefined);
}

export function fetchPriorityQueueSummary(params?: {
  bucket?: string;
  student_id?: string;
  tier?: string;
  only_due?: boolean;
  limit?: number;
  include_demo?: boolean;
}): Promise<{ computed_at_utc: string; summary: PriorityQueueSummary }> {
  return safeGet("/queue/priority/summary", params as Record<string, unknown> | undefined);
}
