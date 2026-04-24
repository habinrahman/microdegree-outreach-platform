import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { PageLayout } from "@/components/PageLayout";
import { KpiCard } from "@/components/KpiCard";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { API_BASE_URL } from "@/lib/constants";
import { getHealth, getSchedulerStatus } from "@/api/api";
import { Activity, RefreshCw, Server } from "lucide-react";

export default function Settings() {
  const healthQ = useQuery({
    queryKey: ["health"],
    queryFn: () => getHealth(),
    refetchInterval: 60_000,
    refetchIntervalInBackground: true,
  });
  const schedQ = useQuery({
    queryKey: ["scheduler"],
    queryFn: () => getSchedulerStatus(),
    refetchInterval: 60_000,
    refetchIntervalInBackground: true,
  });

  const h = healthQ.data ?? {};
  const healthOk = !healthQ.isError && healthQ.data != null;
  const healthHasData = healthOk && Object.keys(h).length > 0;

  const refetchAll = () => {
    healthQ.refetch();
    schedQ.refetch();
  };

  const schedLabel = schedQ.isLoading
    ? "…"
    : schedQ.isError
      ? "Error"
      : (schedQ.data?.scheduler ?? "—");

  return (
    <PageLayout
      title="System Status"
      subtitle="GET /health/ · GET /scheduler/status — live connectivity and queue signals"
      actions={
        <Button type="button" variant="outline" size="sm" onClick={refetchAll} disabled={healthQ.isFetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${healthQ.isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      }
    >
      {healthQ.isError ? (
        <Alert variant="destructive" className="mb-6">
          <AlertTitle>Backend error — check server logs</AlertTitle>
          <AlertDescription>GET /health/ failed at {API_BASE_URL}.</AlertDescription>
        </Alert>
      ) : null}
      {schedQ.isError ? (
        <Alert variant="destructive" className="mb-6">
          <AlertTitle>Backend error — check server logs</AlertTitle>
          <AlertDescription>GET /scheduler/status failed.</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid max-w-5xl gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[
          {
            key: "api",
            node: (
              <KpiCard
                title="API base URL"
                valueDisplay={API_BASE_URL}
                icon={Server}
                tone="neutral"
                valueClassName="break-all text-lg font-mono font-semibold leading-snug"
              />
            ),
          },
          {
            key: "health",
            node: (
              <KpiCard
                title="GET /health/"
                valueDisplay={healthQ.isLoading ? "…" : healthQ.isError ? "Error" : healthHasData ? "OK" : "—"}
                icon={Activity}
                tone="neutral"
              />
            ),
          },
          { key: "sched", node: <KpiCard title="GET /scheduler/status" value={schedLabel} icon={Activity} tone="neutral" /> },
          {
            key: "db",
            node: (
              <KpiCard
                title="Database"
                value={String((h as { db?: string }).db ?? (healthHasData ? "OK" : "—"))}
                icon={Server}
                tone="neutral"
              />
            ),
          },
          {
            key: "pend",
            node: (
              <KpiCard
                title="Pending campaigns"
                value={
                  (h as { pending_campaigns?: number }).pending_campaigns != null
                    ? String((h as { pending_campaigns?: number }).pending_campaigns)
                    : "—"
                }
                icon={Activity}
                tone="neutral"
              />
            ),
          },
          {
            key: "today",
            node: (
              <KpiCard
                title="Sent today"
                value={
                  (h as { sent_today?: number }).sent_today != null
                    ? String((h as { sent_today?: number }).sent_today)
                    : "—"
                }
                icon={Activity}
                tone="neutral"
              />
            ),
          },
          {
            key: "gmail",
            node: (
              <KpiCard
                title="Gmail connected (any)"
                value={
                  (h as { gmail_connected?: boolean }).gmail_connected == null
                    ? "—"
                    : (h as { gmail_connected?: boolean }).gmail_connected
                      ? "Yes"
                      : "No"
                }
                icon={Server}
                tone="neutral"
              />
            ),
          },
        ].map((item, i) => (
          <motion.div
            key={item.key}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.04 }}
          >
            {item.node}
          </motion.div>
        ))}
      </div>

      <p className="mt-8 text-sm text-muted-foreground">
        Frontend: <code className="rounded bg-muted px-1.5 py-0.5 text-xs">http://localhost:5173</code>
      </p>
    </PageLayout>
  );
}
