import { api, safeGet } from "./api";

export type FollowupStatus =
  | "DUE_NOW"
  | "WAITING"
  | "REPLIED_STOPPED"
  | "BOUNCED_STOPPED"
  | "COMPLETED_STOPPED"
  | "PAUSED"
  | "SEND_IN_PROGRESS";

export type FollowupRow = {
  student_id: string;
  student_name?: string | null;
  hr_id: string;
  company?: string | null;
  hr_email?: string | null;
  initial_campaign_id: string;
  current_step: number;
  eligible_for_followup: boolean;
  followup_status: FollowupStatus;
  send_in_progress: boolean;
  next_followup_step?: number | null;
  next_template_type?: string | null;
  due_date_utc?: string | null;
  days_until_due?: number | null;
  blocked_reason?: string | null;
  paused: boolean;
};

export type FollowupsEligiblePagination = {
  limit: number;
  offset: number;
  returned: number;
  total_pairs: number;
  has_more: boolean;
  next_offset: number | null;
};

export type FollowupsEligibleResponse = {
  now_utc: string;
  summary: {
    total: number;
    due_now: number;
    blocked: number;
    paused: number;
    completed: number;
  };
  /** Count of rows per server ``followup_status`` (same cardinality as ``rows``). */
  status_breakdown?: Record<string, number>;
  rows: FollowupRow[];
  /** Window into distinct student–HR pairs (sent initial). Omitted on very old servers. */
  pagination?: FollowupsEligiblePagination;
};

export async function getEligibleFollowups(params?: {
  include_demo?: boolean;
  limit?: number;
  offset?: number;
}): Promise<FollowupsEligibleResponse> {
  return safeGet<FollowupsEligibleResponse>("/followups/eligible", params as any);
}

export type FollowupPreviewResponse = {
  eligibility: Record<string, unknown>;
  template: { template_type: string; subject: string; body: string } | null;
  thread: {
    student_name?: string | null;
    student_email?: string | null;
    company?: string | null;
    hr_email?: string | null;
    in_reply_to?: string | null;
    references?: string[] | null;
    thread_continuity?: boolean;
  } | null;
  server_time_utc?: string;
  template_missing?: boolean;
};

export async function getFollowupPreview(params: {
  student_id: string;
  hr_id: string;
}): Promise<FollowupPreviewResponse> {
  return safeGet<FollowupPreviewResponse>("/followups/preview", params as any);
}

export async function sendManualFollowup(params: {
  student_id: string;
  hr_id: string;
}): Promise<{
  ok: boolean;
  campaign_id?: string;
  step?: number;
  already_sent?: boolean;
  dry_run?: boolean;
  would_send?: { campaign_id?: string; step?: number; template_type?: string; subject?: string };
}> {
  const { data } = await api.post("/followups/send", null, { params });
  return data;
}

export type StaleProcessingRow = {
  campaign_id: string;
  email_type: string;
  sequence_number: number;
  student_id: string;
  student_name?: string | null;
  hr_id: string;
  company?: string | null;
  hr_email?: string | null;
  processing_started_at_utc: string;
  age_minutes: number;
  error?: string | null;
};

export async function listStaleProcessingFollowups(params?: {
  threshold_minutes?: number;
  limit?: number;
}): Promise<{ threshold_minutes: number; total_stale: number; rows: StaleProcessingRow[] }> {
  return safeGet("/followups/reconcile/stale", params as any);
}

export async function reconcileMarkSent(params: {
  campaign_id: string;
  threshold_minutes?: number;
}): Promise<{ ok: boolean; campaign_id: string; status: string; reconciled: boolean }> {
  const { data } = await api.post("/followups/reconcile/mark-sent", null, { params });
  return data;
}

export async function reconcilePause(params: {
  campaign_id: string;
  threshold_minutes?: number;
}): Promise<{ ok: boolean; campaign_id: string; status: string; reconciled: boolean }> {
  const { data } = await api.post("/followups/reconcile/pause", null, { params });
  return data;
}

export type FollowupsDispatchSettings = {
  followups_env_enabled: boolean;
  followups_dispatch_enabled: boolean;
};

export async function getFollowupsDispatchSettings(): Promise<FollowupsDispatchSettings> {
  return safeGet<FollowupsDispatchSettings>("/followups/settings/dispatch");
}

export type FollowupsDispatchChecksum = {
  followups_env_enabled: boolean;
  dispatch_toggle: boolean | null;
  effective_dispatch: boolean;
  source: string;
};

export async function getFollowupsSettingsChecksum(): Promise<FollowupsDispatchChecksum> {
  return safeGet<FollowupsDispatchChecksum>("/followups/settings/checksum");
}

export async function putFollowupsDispatchSettings(body: {
  enabled: boolean;
  reason?: string | null;
}): Promise<{
  ok: boolean;
  followups_dispatch_enabled: boolean;
}> {
  const { data } = await api.put("/followups/settings/dispatch", body);
  return data;
}

export type FollowupFunnelSummary = {
  initial_sent: number;
  followup_1_sent: number;
  followup_2_sent: number;
  followup_3_sent: number;
  followup_rows_cancelled: number;
  campaign_rows_replied_flag: number;
  campaign_rows_status_replied: number;
};

export async function getFollowupFunnelSummary(): Promise<FollowupFunnelSummary> {
  return safeGet<FollowupFunnelSummary>("/followups/funnel/summary");
}

