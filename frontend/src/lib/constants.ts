function _normalizeOrigin(v: unknown): string {
  const s = String(v ?? "").trim();
  return s.endsWith("/") ? s.slice(0, -1) : s;
}

/**
 * Single source of truth for API origin.
 *
 * Preferred: VITE_API_BASE_URL
 * Back-compat: VITE_API_URL
 * Local default: http://127.0.0.1:8010
 */
export const API_BASE_URL = _normalizeOrigin(
  import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8010"
);

// Optional diagnostics: log active API base once in dev.
if (import.meta.env.DEV) {
  const g = globalThis as unknown as { __apiBaseLogged?: boolean };
  if (!g.__apiBaseLogged) {
    g.__apiBaseLogged = true;
    try {
      if (!String(import.meta.env.VITE_API_BASE_URL ?? "").trim()) {
        // eslint-disable-next-line no-console
        console.warn("[api] VITE_API_BASE_URL is not set; using fallback/back-compat value.");
      }
      const api = new URL(API_BASE_URL);
      // eslint-disable-next-line no-console
      console.log(`[api] Using API base: ${api.origin}`);

      // Warn if the frontend is served from a different host than the API base (common misconfig).
      // Ports can differ in dev (5173 vs 8010) — that's expected.
      const fe = new URL(window.location.href);
      if (fe.hostname !== api.hostname) {
        // eslint-disable-next-line no-console
        console.warn(
          `[api] Host mismatch: frontend=${fe.hostname} api=${api.hostname}. If requests fail, set VITE_API_BASE_URL.`
        );
      }
    } catch {
      // eslint-disable-next-line no-console
      console.warn(
        `[api] Invalid API base URL: ${API_BASE_URL}. Set VITE_API_BASE_URL (e.g. http://127.0.0.1:8010).`
      );
    }
  }
}

export const ROUTES = {
  dashboard: "/",
  students: "/students",
  hrContacts: "/hr-contacts",
  outreach: "/outreach",
  campaigns: "/campaigns",
  campaignLifecycle: "/campaign-lifecycle",
  followups: "/followups",
  priorityQueue: "/priority-queue",
  decisionDiagnostics: "/decision-diagnostics",
  replies: "/replies",
  emailLogs: "/email-logs",
  analyticsStudents: "/analytics/students",
  analyticsHrs: "/analytics/hrs",
  analyticsTemplates: "/analytics/templates",
  admin: "/admin",
  adminObservability: "/admin/observability",
  systemReliability: "/system-reliability",
  settings: "/settings",
} as const;

/** Server list page size for tables that paginate via skip/limit. */
export const TABLE_PAGE_SIZE = 50;

/** Documented frontend request caps (for “showing X of Y” + truncation hints). */
export const API_LIST_LIMITS = {
  campaigns: 1000,
  replies: 500,
  emailLogs: 500,
  hrContacts: 8000,
  analyticsRows: 500,
  adminLogs: 400,
} as const;
