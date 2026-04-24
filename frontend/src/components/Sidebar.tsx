import { NavLink, useLocation } from "react-router-dom";
import { useCallback, useState } from "react";
import {
  LayoutDashboard,
  GraduationCap,
  Users,
  Send,
  Mail,
  Settings,
  Inbox,
  BarChart3,
  Wrench,
  Megaphone,
  AlarmClock,
  ListOrdered,
  Microscope,
  GitBranch,
  Activity,
  ChevronDown,
  ChevronRight,
  LayoutGrid,
} from "lucide-react";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { isAdminToolsSectionPath, isAnalyticsSectionPath } from "@/lib/routeMeta";

const LS_ANALYTICS = "sidebar.group.analytics.open";
const LS_ADMIN = "sidebar.group.admin.open";

function readTriState(key: string): boolean | null {
  if (typeof window === "undefined") return null;
  const v = localStorage.getItem(key);
  if (v === "0") return false;
  if (v === "1") return true;
  return null;
}

function writeTriState(key: string, open: boolean) {
  if (typeof window === "undefined") return;
  localStorage.setItem(key, open ? "1" : "0");
}

const primaryNav: { to: string; label: string; icon: typeof LayoutDashboard; end?: boolean }[] = [
  { to: ROUTES.dashboard, label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: ROUTES.students, label: "Students", icon: GraduationCap },
  { to: ROUTES.hrContacts, label: "HR Contacts", icon: Users },
  { to: ROUTES.outreach, label: "Outreach", icon: Send },
  { to: ROUTES.campaigns, label: "Campaigns", icon: Megaphone },
  { to: ROUTES.followups, label: "Follow-ups", icon: AlarmClock },
  { to: ROUTES.replies, label: "Replies", icon: Inbox },
  { to: ROUTES.emailLogs, label: "Email Logs", icon: Mail },
];

const analyticsChildren: { to: string; label: string }[] = [
  { to: ROUTES.analyticsStudents, label: "Analytics · Students" },
  { to: ROUTES.analyticsHrs, label: "Analytics · HRs" },
  { to: ROUTES.analyticsTemplates, label: "Analytics · Templates" },
];

const observabilityConsoleChildren: {
  panel: string;
  label: string;
  icon: typeof ListOrdered;
  standalone: string;
}[] = [
  { panel: "priority-queue", label: "Priority queue", icon: ListOrdered, standalone: ROUTES.priorityQueue },
  {
    panel: "decision-diagnostics",
    label: "Decision diagnostics",
    icon: Microscope,
    standalone: ROUTES.decisionDiagnostics,
  },
  {
    panel: "campaign-lifecycle",
    label: "Campaign lifecycle",
    icon: GitBranch,
    standalone: ROUTES.campaignLifecycle,
  },
  {
    panel: "system-reliability",
    label: "System reliability",
    icon: Activity,
    standalone: ROUTES.systemReliability,
  },
  { panel: "system-status", label: "System status", icon: Settings, standalone: ROUTES.settings },
];

function observabilityNavActive(pathname: string, search: string, panel: string, standalone: string): boolean {
  if (pathname === standalone) return true;
  if (pathname !== ROUTES.adminObservability) return false;
  const q = search.startsWith("?") ? search.slice(1) : search;
  const p = new URLSearchParams(q).get("panel");
  return p === panel;
}

function observabilityOverviewActive(pathname: string, search: string): boolean {
  if (pathname !== ROUTES.adminObservability) return false;
  const q = search.startsWith("?") ? search.slice(1) : search;
  const p = new URLSearchParams(q).get("panel");
  return !p || p === "overview";
}

export function Sidebar() {
  const { pathname, search } = useLocation();

  const [analyticsOpen, setAnalyticsOpen] = useState(() => {
    const pref = readTriState(LS_ANALYTICS);
    if (pref !== null) return pref;
    return isAnalyticsSectionPath(pathname);
  });

  const [adminOpen, setAdminOpen] = useState(() => {
    const pref = readTriState(LS_ADMIN);
    if (pref !== null) return pref;
    return isAdminToolsSectionPath(pathname);
  });

  const toggleAnalytics = useCallback((open: boolean) => {
    setAnalyticsOpen(open);
    writeTriState(LS_ANALYTICS, open);
  }, []);

  const toggleAdmin = useCallback((open: boolean) => {
    setAdminOpen(open);
    writeTriState(LS_ADMIN, open);
  }, []);

  const subNavClass = (active: boolean) =>
    cn(
      "sidebar-nav-item flex items-center gap-2 rounded-md py-2 pl-9 pr-3 text-sm",
      active ? "active" : ""
    );

  return (
    <aside
      className="flex h-screen w-56 shrink-0 flex-col overflow-y-auto border-r border-border"
      style={{ backgroundColor: "hsl(var(--sidebar-background))" }}
    >
      <div className="flex items-center gap-2 border-b border-white/5 px-4 py-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
          <Send className="h-4 w-4 text-primary-foreground" />
        </div>
        <span
          className="text-sm font-semibold tracking-tight"
          style={{ color: "hsl(var(--sidebar-foreground-active))" }}
        >
          MicroDegree Outreach
        </span>
      </div>

      <nav className="flex-1 space-y-0.5 p-2">
        {primaryNav.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "sidebar-nav-item flex items-center gap-2 rounded-md px-3 py-2 text-sm",
                isActive ? "active" : ""
              )
            }
          >
            <item.icon className="h-4 w-4 shrink-0 opacity-80" />
            <span className="leading-snug">{item.label}</span>
          </NavLink>
        ))}

        <Collapsible open={analyticsOpen} onOpenChange={toggleAnalytics}>
          <CollapsibleTrigger
            type="button"
            className="sidebar-nav-item flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-muted/50"
          >
            <span className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4 shrink-0 opacity-80" />
              <span className="leading-snug">Analytics</span>
            </span>
            {analyticsOpen ? (
              <ChevronDown className="h-4 w-4 shrink-0 opacity-60" />
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0 opacity-60" />
            )}
          </CollapsibleTrigger>
          <CollapsibleContent className="space-y-0.5 pt-0.5">
            {analyticsChildren.map((c) => (
              <NavLink key={c.to} to={c.to} className={({ isActive }) => subNavClass(isActive)}>
                <span className="leading-snug">{c.label}</span>
              </NavLink>
            ))}
          </CollapsibleContent>
        </Collapsible>

        <Collapsible open={adminOpen} onOpenChange={toggleAdmin}>
          <CollapsibleTrigger
            type="button"
            className="sidebar-nav-item flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-muted/50"
          >
            <span className="flex items-center gap-2">
              <Wrench className="h-4 w-4 shrink-0 opacity-80" />
              <span className="leading-snug">Admin Tools</span>
            </span>
            {adminOpen ? (
              <ChevronDown className="h-4 w-4 shrink-0 opacity-60" />
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0 opacity-60" />
            )}
          </CollapsibleTrigger>
          <CollapsibleContent className="space-y-0.5 pt-0.5">
            <NavLink to={ROUTES.admin} className={() => subNavClass(pathname === ROUTES.admin)}>
              <span className="leading-snug">Admin overview</span>
            </NavLink>
            <div
              className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/90"
              aria-hidden
            >
              Observability console
            </div>
            <NavLink
              to={ROUTES.adminObservability}
              className={() => subNavClass(observabilityOverviewActive(pathname, search))}
            >
              <span className="flex items-center gap-2 leading-snug">
                <LayoutGrid className="h-3.5 w-3.5 shrink-0 opacity-70" />
                Overview
              </span>
            </NavLink>
            {observabilityConsoleChildren.map((c) => (
              <NavLink
                key={c.panel}
                to={`${ROUTES.adminObservability}?panel=${encodeURIComponent(c.panel)}`}
                className={() =>
                  subNavClass(observabilityNavActive(pathname, search, c.panel, c.standalone))
                }
              >
                <span className="flex items-center gap-2 leading-snug">
                  <c.icon className="h-3.5 w-3.5 shrink-0 opacity-70" />
                  {c.label}
                </span>
              </NavLink>
            ))}
          </CollapsibleContent>
        </Collapsible>
      </nav>

      <p
        className="px-4 py-4 text-[10px] opacity-40"
        style={{ color: "hsl(var(--sidebar-foreground))" }}
      >
        © 2026 MicroDegree Outreach
      </p>
    </aside>
  );
}
