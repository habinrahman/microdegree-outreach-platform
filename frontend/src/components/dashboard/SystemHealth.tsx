import { motion } from "framer-motion";
import { Activity, Database, Server } from "lucide-react";

import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";

type Props = {
  backendOk: boolean;
  dbOk: boolean;
  schedulerStatus: string | undefined;
  loadingHealth: boolean;
  loadingScheduler: boolean;
  schedulerError?: boolean;
};

function StatusTile({
  label,
  sublabel,
  ok,
  loading,
  icon: Icon,
  okClass,
  badClass,
}: {
  label: string;
  sublabel: string;
  ok: boolean;
  loading: boolean;
  icon: typeof Server;
  okClass: string;
  badClass: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className={cn(
        "flex min-w-[200px] flex-1 items-center gap-4 rounded-xl border p-6 shadow-sm transition-all duration-300",
        "hover:shadow-md",
        ok ? okClass : badClass
      )}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-background/80 shadow-sm backdrop-blur-sm">
        <Icon className="h-6 w-6 text-muted-foreground" aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-gray-500 dark:text-muted-foreground">{label}</p>
        <p className="text-lg font-semibold tracking-tight text-foreground">
          {loading ? (
            <Skeleton className="mt-1 h-7 w-24" />
          ) : ok ? (
            <span className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-[#22C55E] shadow-[0_0_8px_rgba(34,197,94,0.6)]" />
              Operational
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-[#EF4444] shadow-[0_0_8px_rgba(239,68,68,0.5)]" />
              Attention
            </span>
          )}
        </p>
        <p className="mt-0.5 text-sm text-gray-500 dark:text-muted-foreground">{sublabel}</p>
      </div>
    </motion.div>
  );
}

export function SystemHealth({
  backendOk,
  dbOk,
  schedulerStatus,
  loadingHealth,
  loadingScheduler,
  schedulerError,
}: Props) {
  const sch = (schedulerStatus ?? "").toLowerCase();
  const schedulerOk = sch === "running";
  const schedulerUnknown = schedulerError || sch === "unknown" || sch === "";

  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-xl border border-border/60 bg-gradient-to-r from-slate-500/[0.06] via-transparent to-indigo-500/[0.06] p-6 shadow-sm backdrop-blur-md transition-all duration-300 hover:shadow-md">
        <h2 className="text-lg font-semibold text-foreground">System health</h2>
        <p className="text-sm text-gray-500 dark:text-muted-foreground">
          Live signals from the API · refreshes every 10s
        </p>
      </div>
      <div className="flex flex-wrap items-stretch gap-6">
        <StatusTile
          label="Backend status"
          sublabel="GET /health/"
          ok={backendOk}
          loading={loadingHealth}
          icon={Server}
          okClass="border-[#22C55E]/25 bg-[#22C55E]/[0.04]"
          badClass="border-[#F59E0B]/35 bg-[#F59E0B]/[0.06]"
        />
        <StatusTile
          label="Database connection"
          sublabel="SQL ping on health check"
          ok={dbOk}
          loading={loadingHealth}
          icon={Database}
          okClass="border-[#3B82F6]/25 bg-[#3B82F6]/[0.05]"
          badClass="border-[#EF4444]/30 bg-[#EF4444]/[0.06]"
        />
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.06 }}
          className={cn(
            "flex min-w-[200px] flex-1 items-center gap-4 rounded-xl border p-6 shadow-sm transition-all duration-300 hover:shadow-md",
            schedulerOk
              ? "border-[#22C55E]/25 bg-[#22C55E]/[0.04]"
              : schedulerUnknown
                ? "border-[#F59E0B]/35 bg-[#F59E0B]/[0.06]"
                : "border-[#EF4444]/30 bg-[#EF4444]/[0.06]"
          )}
        >
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-background/80 shadow-sm backdrop-blur-sm">
            <Activity className="h-6 w-6 text-muted-foreground" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-gray-500 dark:text-muted-foreground">Scheduler status</p>
            <p className="text-lg font-semibold tracking-tight text-foreground">
              {loadingScheduler ? (
                <Skeleton className="mt-1 h-7 w-28" />
              ) : schedulerOk ? (
                <span className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-[#22C55E] shadow-[0_0_8px_rgba(34,197,94,0.6)]" />
                  Running
                </span>
              ) : schedulerUnknown ? (
                <span className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-[#F59E0B]" />
                  Unknown
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full bg-[#EF4444]" />
                  Stopped
                </span>
              )}
            </p>
            <p className="mt-0.5 text-sm text-gray-500 dark:text-muted-foreground">
              GET /scheduler/status
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
