import { useCallback, useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Activity,
  GitBranch,
  LayoutGrid,
  ListOrdered,
  Microscope,
  Settings as SettingsIcon,
} from "lucide-react";
import { PageLayout } from "@/components/PageLayout";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";

import PriorityQueue from "@/pages/PriorityQueue";
import DecisionDiagnostics from "@/pages/DecisionDiagnostics";
import CampaignLifecycle from "@/pages/CampaignLifecycle";
import SystemReliability from "@/pages/SystemReliability";
import Settings from "@/pages/Settings";

const VALID_PANELS = [
  "overview",
  "priority-queue",
  "decision-diagnostics",
  "campaign-lifecycle",
  "system-reliability",
  "system-status",
] as const;

type Panel = (typeof VALID_PANELS)[number];

function normalizePanel(raw: string | null): Panel {
  if (raw && (VALID_PANELS as readonly string[]).includes(raw)) return raw as Panel;
  return "overview";
}

const PANEL_META: { id: Panel; label: string; description: string; icon: typeof Activity; deepLink: string }[] = [
  {
    id: "priority-queue",
    label: "Priority queue",
    description: "Ranked assignments and scheduler-facing queue health.",
    icon: ListOrdered,
    deepLink: ROUTES.priorityQueue,
  },
  {
    id: "decision-diagnostics",
    label: "Decision diagnostics",
    description: "Explainability and scoring diagnostics.",
    icon: Microscope,
    deepLink: ROUTES.decisionDiagnostics,
  },
  {
    id: "campaign-lifecycle",
    label: "Campaign lifecycle",
    description: "FSM and lifecycle state for campaigns.",
    icon: GitBranch,
    deepLink: ROUTES.campaignLifecycle,
  },
  {
    id: "system-reliability",
    label: "System reliability",
    description: "SLO proxy, queues, alerts, and diagnostics JSON.",
    icon: Activity,
    deepLink: ROUTES.systemReliability,
  },
  {
    id: "system-status",
    label: "System status",
    description: "Health, config, and environment snapshot.",
    icon: SettingsIcon,
    deepLink: ROUTES.settings,
  },
];

export default function ObservabilityConsole() {
  const [searchParams, setSearchParams] = useSearchParams();
  const panel = useMemo(() => normalizePanel(searchParams.get("panel")), [searchParams]);

  const setPanel = useCallback(
    (next: Panel) => {
      setSearchParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          if (next === "overview") {
            p.delete("panel");
            p.delete("pair");
          } else {
            p.set("panel", next);
            if (next !== "decision-diagnostics") p.delete("pair");
          }
          return p;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  return (
    <PageLayout
      title="Observability console"
      subtitle="Operator cockpit: queue health, diagnostics, lifecycle, reliability, and system status. Deep links such as /priority-queue still work unchanged."
    >
      <Tabs value={panel} onValueChange={(v) => setPanel(normalizePanel(v))} className="space-y-6">
        <TabsList
          className={cn(
            "flex h-auto w-full flex-wrap justify-start gap-1 bg-muted/40 p-1",
            "overflow-x-auto"
          )}
        >
          <TabsTrigger value="overview" className="gap-1.5 text-xs sm:text-sm">
            <LayoutGrid className="h-3.5 w-3.5 opacity-70" />
            Overview
          </TabsTrigger>
          {PANEL_META.map((p) => (
            <TabsTrigger key={p.id} value={p.id} className="gap-1.5 text-xs sm:text-sm">
              <p.icon className="h-3.5 w-3.5 opacity-70" />
              <span className="hidden sm:inline">{p.label}</span>
              <span className="sm:hidden">{p.label.split(" ")[0]}</span>
            </TabsTrigger>
          ))}
        </TabsList>

        {panel === "overview" ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {PANEL_META.map((p) => (
              <PremiumCard key={p.id} className="overflow-hidden p-4 shadow-sm">
                <div className="mb-2 flex items-center gap-2">
                  <p.icon className="h-4 w-4 text-primary" />
                  <h3 className="text-sm font-semibold">{p.label}</h3>
                </div>
                <p className="mb-3 text-xs leading-relaxed text-muted-foreground">{p.description}</p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="text-xs font-medium text-primary underline-offset-4 hover:underline"
                    onClick={() => setPanel(p.id)}
                  >
                    Open in console
                  </button>
                  <span className="text-muted-foreground">·</span>
                  <Link
                    to={p.deepLink}
                    className="text-xs font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                  >
                    Open standalone route
                  </Link>
                </div>
              </PremiumCard>
            ))}
          </div>
        ) : null}
        {panel === "priority-queue" ? <PriorityQueue /> : null}
        {panel === "decision-diagnostics" ? <DecisionDiagnostics /> : null}
        {panel === "campaign-lifecycle" ? <CampaignLifecycle /> : null}
        {panel === "system-reliability" ? <SystemReliability /> : null}
        {panel === "system-status" ? <Settings /> : null}
      </Tabs>
    </PageLayout>
  );
}
