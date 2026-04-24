import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Activity, AlertTriangle, BarChart3, BookOpen, CheckCircle2, Server, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageLayout } from "@/components/PageLayout";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { formatApiFailureLabel, getAdminReliability } from "@/api/api";

export default function SystemReliability() {
  const relQ = useQuery({
    queryKey: ["admin", "reliability"],
    queryFn: () => getAdminReliability(),
    refetchInterval: 60_000,
  });

  const data = relQ.data as
    | {
        alerts?: unknown[];
        schema_launch_gate?: {
          status?: string;
          tables?: { name: string; present: boolean; control_plane: boolean }[];
          missing_control_plane?: string[];
          missing_any?: string[];
        };
        sequence_engine?: Record<string, unknown>;
        slo_panel?: Record<string, unknown>;
        queues?: Record<string, unknown>;
        metrics?: Record<string, unknown>;
        scheduler?: Record<string, unknown>;
        smtp_rollups_24h?: Record<string, unknown>;
        per_student_email_health_counts?: Record<string, unknown>;
      }
    | undefined;

  const alerts = Array.isArray(data?.alerts) ? data!.alerts : [];

  return (
    <PageLayout
      title="System reliability"
      subtitle="Observability snapshot · GET /admin/reliability · anomaly hints · SLO proxy"
    >
      {relQ.isError ? (
        <PremiumCard className="mb-6 p-6 space-y-3 border border-destructive/30">
          <p className="text-sm font-medium text-destructive">Unable to load reliability snapshot</p>
          <p className="text-xs text-muted-foreground">{formatApiFailureLabel(relQ.error)}</p>
          <Button variant="outline" size="sm" type="button" onClick={() => relQ.refetch()} disabled={relQ.isFetching}>
            Retry
          </Button>
        </PremiumCard>
      ) : null}

      <PremiumCard
        className={`mb-6 p-4 shadow-sm border ${
          data?.schema_launch_gate?.status === "critical"
            ? "border-destructive/60 bg-destructive/5"
            : data?.schema_launch_gate?.status === "degraded"
              ? "border-amber-500/50 bg-amber-500/5"
              : "border-border"
        }`}
      >
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Server className="h-4 w-4 text-rose-600" />
            Launch gate · critical tables
          </div>
          <span
            className={`rounded px-2 py-0.5 text-xs font-medium uppercase ${
              data?.schema_launch_gate?.status === "ok"
                ? "bg-emerald-500/15 text-emerald-800 dark:text-emerald-300"
                : data?.schema_launch_gate?.status === "degraded"
                  ? "bg-amber-500/20 text-amber-900 dark:text-amber-200"
                  : "bg-destructive/15 text-destructive"
            }`}
          >
            {relQ.isLoading ? "…" : data?.schema_launch_gate?.status ?? "unknown"}
          </span>
        </div>
        <p className="mb-3 text-xs text-muted-foreground leading-relaxed">
          Same check as <code className="rounded bg-muted px-1 text-[10px]">GET /health/schema-launch-gate</code>.
          Missing <span className="font-mono text-[10px]">runtime_settings</span> is a control-plane failure (red)
          until migrations or startup bootstrap create it.
        </p>
        {relQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="py-1.5 pr-3 font-medium">Table</th>
                  <th className="py-1.5 pr-3 font-medium">Control plane</th>
                  <th className="py-1.5 font-medium">Present</th>
                </tr>
              </thead>
              <tbody>
                {(data?.schema_launch_gate?.tables ?? []).map((t) => {
                  const bad = !t.present && t.control_plane;
                  const warn = !t.present && !t.control_plane;
                  return (
                    <tr key={t.name} className="border-b border-border/60">
                      <td className="py-1.5 pr-3 font-mono">{t.name}</td>
                      <td className="py-1.5 pr-3">{t.control_plane ? "yes" : "—"}</td>
                      <td className="py-1.5">
                        {t.present ? (
                          <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            yes
                          </span>
                        ) : (
                          <span
                            className={`inline-flex items-center gap-1 ${
                              bad ? "text-destructive" : warn ? "text-amber-700 dark:text-amber-400" : ""
                            }`}
                          >
                            <XCircle className="h-3.5 w-3.5" />
                            no
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </PremiumCard>

      <PremiumCard className="mb-6 p-4 shadow-sm border-border">
        <div className="mb-2 text-sm font-semibold">Autonomous Sequencer v1</div>
        <p className="mb-2 text-xs text-muted-foreground leading-relaxed">
          Queue depth, overdue flags, and lifecycle counts on initial rows. Threshold for overdue flags:
          <code className="mx-1 rounded bg-muted px-1 text-[10px]">SEQUENCE_OVERDUE_LAG_MINUTES</code> (default 1440).
        </p>
        <pre className="max-h-48 overflow-auto text-xs leading-relaxed">
          {relQ.isLoading ? "…" : JSON.stringify(data?.sequence_engine ?? {}, null, 2)}
        </pre>
      </PremiumCard>

      <div className="mb-6 grid gap-4 lg:grid-cols-3">
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <PremiumCard className="p-4 shadow-sm">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <BarChart3 className="h-4 w-4 text-sky-600" />
              SLO / error budget (24h proxy)
            </div>
            {relQ.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : (
              <pre className="max-h-40 overflow-auto text-xs leading-relaxed">
                {JSON.stringify(data?.slo_panel ?? {}, null, 2)}
              </pre>
            )}
          </PremiumCard>
        </motion.div>
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
          <PremiumCard className="p-4 shadow-sm">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <Server className="h-4 w-4 text-emerald-600" />
              Queues &amp; SMTP (24h)
            </div>
            {relQ.isLoading ? null : (
              <pre className="max-h-40 overflow-auto text-xs leading-relaxed">
                {JSON.stringify(
                  { queues: data?.queues, smtp_rollups_24h: data?.smtp_rollups_24h },
                  null,
                  2
                )}
              </pre>
            )}
          </PremiumCard>
        </motion.div>
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <PremiumCard className="p-4 shadow-sm">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <Activity className="h-4 w-4 text-violet-600" />
              In-process metrics
            </div>
            {relQ.isLoading ? null : (
              <pre className="max-h-40 overflow-auto text-xs leading-relaxed">
                {JSON.stringify(data?.metrics ?? {}, null, 2)}
              </pre>
            )}
          </PremiumCard>
        </motion.div>
      </div>

      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <PremiumCard className="p-4 shadow-sm">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <AlertTriangle className="h-4 w-4 text-amber-600" />
            Anomaly alerts ({alerts.length})
          </div>
          {relQ.isError ? (
            <p className="text-sm text-destructive">Failed to load (check admin API key).</p>
          ) : (
            <pre className="max-h-48 overflow-auto text-xs leading-relaxed">
              {JSON.stringify(alerts, null, 2)}
            </pre>
          )}
        </PremiumCard>
        <PremiumCard className="p-4 shadow-sm">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <BookOpen className="h-4 w-4 text-muted-foreground" />
            Scheduler + student health
          </div>
          <pre className="max-h-48 overflow-auto text-xs leading-relaxed">
            {JSON.stringify(
              {
                scheduler: data?.scheduler,
                per_student_email_health_counts: data?.per_student_email_health_counts,
              },
              null,
              2
            )}
          </pre>
        </PremiumCard>
      </div>

      <PremiumCard className="p-4 shadow-sm">
        <div className="mb-2 text-sm font-semibold">Full diagnostics JSON</div>
        <pre className="max-h-[28rem] overflow-auto text-xs leading-relaxed whitespace-pre-wrap break-all">
          {relQ.isLoading ? "…" : JSON.stringify(relQ.data ?? {}, null, 2)}
        </pre>
      </PremiumCard>
    </PageLayout>
  );
}
