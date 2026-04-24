import { ROUTES } from "@/lib/constants";

/** Standalone routes that belong to Admin Tools → Observability console IA. */
export const OBSERVABILITY_STANDALONE_PATHS: Record<string, string> = {
  [ROUTES.priorityQueue]: "priority-queue",
  [ROUTES.decisionDiagnostics]: "decision-diagnostics",
  [ROUTES.campaignLifecycle]: "campaign-lifecycle",
  [ROUTES.systemReliability]: "system-reliability",
  [ROUTES.settings]: "system-status",
};

const PANEL_BREADCRUMB_LABEL: Record<string, string> = {
  overview: "Overview",
  "priority-queue": "Priority queue",
  "decision-diagnostics": "Decision diagnostics",
  "campaign-lifecycle": "Campaign lifecycle",
  "system-reliability": "System reliability",
  "system-status": "System status",
};

export const ROUTE_TITLES: Record<string, string> = {
  [ROUTES.dashboard]: "Dashboard",
  [ROUTES.students]: "Students",
  [ROUTES.hrContacts]: "HR Contacts",
  [ROUTES.outreach]: "Outreach",
  [ROUTES.campaigns]: "Campaigns",
  [ROUTES.campaignLifecycle]: "Campaign lifecycle",
  [ROUTES.followups]: "Follow-ups",
  [ROUTES.priorityQueue]: "Priority queue",
  [ROUTES.decisionDiagnostics]: "Decision diagnostics",
  [ROUTES.replies]: "Replies",
  [ROUTES.emailLogs]: "Email Logs",
  [ROUTES.analyticsStudents]: "Analytics — Students",
  [ROUTES.analyticsHrs]: "Analytics — HRs",
  [ROUTES.analyticsTemplates]: "Analytics — Templates",
  [ROUTES.admin]: "Admin overview",
  [ROUTES.adminObservability]: "Observability console",
  [ROUTES.systemReliability]: "System reliability",
  [ROUTES.settings]: "System status",
};

export function titleForPath(pathname: string): string {
  return ROUTE_TITLES[pathname] ?? "Placement Outreach";
}

export type Crumb = { label: string; to?: string };

function _searchKey(search: string): string {
  if (!search) return "";
  return search.startsWith("?") ? search : `?${search}`;
}

function _panelFromLocation(pathname: string, search: string): string {
  if (pathname === ROUTES.adminObservability) {
    const q = new URLSearchParams(_searchKey(search));
    const p = q.get("panel");
    if (p && PANEL_BREADCRUMB_LABEL[p]) return p;
    return "overview";
  }
  const mapped = OBSERVABILITY_STANDALONE_PATHS[pathname];
  return mapped ?? "";
}

export function breadcrumbsForPath(pathname: string, search: string = ""): Crumb[] {
  const root: Crumb = { label: "Dashboard", to: ROUTES.dashboard };
  if (pathname === ROUTES.dashboard || pathname === "") return [root];

  if (pathname.startsWith("/analytics/")) {
    const leaf = ROUTE_TITLES[pathname] ?? pathname;
    const short = leaf.replace(/^Analytics — /, "");
    return [root, { label: "Analytics" }, { label: short || leaf }];
  }

  if (pathname === ROUTES.admin) {
    return [root, { label: "Admin Tools", to: ROUTES.admin }, { label: "Admin overview" }];
  }

  if (pathname === ROUTES.adminObservability) {
    const panel = _panelFromLocation(pathname, search);
    const leaf = PANEL_BREADCRUMB_LABEL[panel] ?? "Observability console";
    return [
      root,
      { label: "Admin Tools", to: ROUTES.admin },
      { label: "Observability console", to: ROUTES.adminObservability },
      { label: leaf },
    ];
  }

  const standalonePanel = OBSERVABILITY_STANDALONE_PATHS[pathname];
  if (standalonePanel) {
    const leaf = PANEL_BREADCRUMB_LABEL[standalonePanel] ?? ROUTE_TITLES[pathname] ?? pathname;
    return [
      root,
      { label: "Admin Tools", to: ROUTES.admin },
      {
        label: "Observability console",
        to: `${ROUTES.adminObservability}?panel=${encodeURIComponent(standalonePanel)}`,
      },
      { label: leaf },
    ];
  }

  const title = ROUTE_TITLES[pathname] ?? (pathname.replace(/^\//, "") || "Page");
  return [root, { label: title }];
}

/** Whether current location should expand the Admin Tools sidebar group on first load. */
export function isAdminToolsSectionPath(pathname: string): boolean {
  if (pathname === ROUTES.admin || pathname === ROUTES.adminObservability) return true;
  return pathname in OBSERVABILITY_STANDALONE_PATHS;
}

/** Whether current location should expand the Analytics sidebar group on first load. */
export function isAnalyticsSectionPath(pathname: string): boolean {
  return pathname.startsWith("/analytics/");
}
