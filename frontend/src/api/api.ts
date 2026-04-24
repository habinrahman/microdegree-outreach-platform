import axios from "axios";
import { API_BASE_URL } from "@/lib/constants";

/** Default HTTP timeout so hung backends cannot leave the UI spinning indefinitely. */
export const API_REQUEST_TIMEOUT_MS = 15_000;

type ObsRequestConfig = { __obsReqStart?: number };

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: API_REQUEST_TIMEOUT_MS,
});

const adminKey = (import.meta.env.VITE_ADMIN_API_KEY as string | undefined)?.trim();
if (adminKey) {
  api.defaults.headers.common["X-API-Key"] = adminKey;
}

api.interceptors.request.use((config) => {
  (config as ObsRequestConfig).__obsReqStart = performance.now();
  const path = `${config.baseURL ?? ""}${config.url ?? ""}`;
  console.info(`[obs-api] start ${config.method?.toUpperCase() ?? "GET"} ${path}`);
  return config;
});

api.interceptors.response.use(
  (res) => {
    const t0 = (res.config as ObsRequestConfig).__obsReqStart;
    const ms = t0 != null ? Math.round(performance.now() - t0) : undefined;
    console.info(
      `[obs-api] ok ${res.status} ${res.config.method?.toUpperCase() ?? "GET"} ${res.config.url ?? ""}${ms != null ? ` ${ms}ms` : ""}`
    );
    return res;
  },
  (error: unknown) => {
    const ax = axios.isAxiosError(error) ? error : null;
    const method = ax?.config?.method?.toUpperCase();
    const url = ax?.config?.url;
    const status = ax?.response?.status;
    const t0 = ax?.config ? (ax.config as ObsRequestConfig).__obsReqStart : undefined;
    const ms = t0 != null ? Math.round(performance.now() - t0) : undefined;
    const timedOut =
      ax?.code === "ECONNABORTED" || /timeout/i.test(String(ax?.message ?? ""));
    const reason = timedOut ? "timeout" : status != null ? `http_${status}` : "network_or_unknown";
    console.warn(
      `[obs-api] fail ${method ?? "?"} ${url ?? "?"} status=${status ?? "n/a"} reason=${reason}${ms != null ? ` ${ms}ms` : ""}`,
      ax?.message ?? error
    );
    return Promise.reject(error);
  }
);

/** User-facing / operator-facing message for observability pages. */
export function formatApiFailureLabel(err: unknown): string {
  if (axios.isAxiosError(err)) {
    if (err.code === "ECONNABORTED" || /timeout/i.test(String(err.message))) {
      return `Request timed out after ${API_REQUEST_TIMEOUT_MS / 1000}s (${String(err.config?.method ?? "GET").toUpperCase()} ${String(err.config?.url ?? "")}).`;
    }
    const st = err.response?.status;
    if (st === 401 || st === 403) {
      return "Forbidden or unauthorized — when the backend requires a key, set VITE_ADMIN_API_KEY to match ADMIN_API_KEY.";
    }
    if (st) return `HTTP ${st} on ${String(err.config?.url ?? "?")}.`;
    return err.message || "Network error while calling the API.";
  }
  if (err instanceof Error) return err.message;
  return "Unable to load diagnostics.";
}

/** Propagates errors — no silent null. */
export async function safeGet<T = unknown>(
  url: string,
  params?: Record<string, unknown>
): Promise<T> {
  try {
    const { data } = await api.get<T>(url, { params });
    if (data === undefined) throw new Error(`GET ${url}: empty response body`);
    return data;
  } catch (err) {
    console.error("API failed:", err);
    throw err;
  }
}

export type HealthPayload = {
  status?: string;
  scheduler?: string;
  gmail_connected?: boolean;
  pending_campaigns?: number;
  sent_today?: number;
  db?: string;
};

export async function getHealth(): Promise<HealthPayload> {
  return safeGet<HealthPayload>("/health/");
}

export async function getSchedulerStatus(): Promise<{ scheduler: string }> {
  const d = await safeGet<{ scheduler?: string }>("/scheduler/status");
  if (d.scheduler == null) throw new Error("GET /scheduler/status: missing scheduler field");
  return { scheduler: String(d.scheduler) };
}

export async function getEmailLogsNullable(params?: { limit?: number; include_demo?: boolean }) {
  return safeGet<unknown[]>("/email-logs", params as Record<string, unknown> | undefined);
}

export async function getAdminLogsNullable(params?: { limit?: number }) {
  const limit = params?.limit ?? 200;
  return safeGet<unknown[]>("/admin/logs", { limit });
}

/** Read-only fixture pollution + integrity snapshot (requires admin API key when configured). */
export async function getAdminFixtureAudit(): Promise<unknown> {
  return safeGet<unknown>("/admin/fixture-audit");
}

export async function getAdminBackupHealth(): Promise<unknown> {
  return safeGet<unknown>("/admin/backup-health");
}

export async function getAdminDeliverabilityHealth(): Promise<unknown> {
  return safeGet<unknown>("/admin/deliverability-health");
}

/** SRE snapshot: queues, scheduler, SMTP rollups, anomaly hints, SLO proxy (admin key). */
export async function getAdminReliability(): Promise<unknown> {
  return safeGet<unknown>("/admin/reliability");
}

export async function sendOutreach(payload: {
  student_id: string;
  hr_id?: string;
  hr_email?: string;
  template_label?: string | null;
  subject?: string | null;
  body?: string | null;
}) {
  const { data } = await api.post("/outreach/send", payload);
  return data;
}

export async function sendFollowup1(payload: {
  student_id: string;
  hr_id: string;
  template_label?: string | null;
}) {
  try {
    const { data } = await api.post("/followup1/send", payload);
    return data;
  } catch (e) {
    if (axios.isAxiosError(e) && e.response?.status === 404) {
      const { data } = await api.post("/outreach/send", payload);
      return data;
    }
    throw e;
  }
}

export async function createAssignments(payload: { student_id: string; hr_ids: string[] }) {
  const { data } = await api.post("/assignments", payload);
  return data;
}

export async function getReplies(params?: Record<string, unknown>) {
  const data = await safeGet<unknown[]>("/replies", params as Record<string, unknown> | undefined);
  if (!Array.isArray(data)) throw new Error("GET /replies: expected JSON array");
  return data;
}

export async function patchReply(
  campaignId: string,
  payload: { status?: string; notes?: string | null }
) {
  const { data } = await api.patch(`/replies/${campaignId}`, payload);
  return data;
}

export async function triggerBackup() {
  try {
    const { data } = await api.post("/admin/backup");
    return data;
  } catch (e) {
    if (axios.isAxiosError(e) && (e.response?.status === 404 || e.response?.status === 405)) {
      const { data } = await api.post("/admin/backup/sqlite");
      return data;
    }
    throw e;
  }
}
