import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Database, HardDrive, ScrollText, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { PageLayout } from "@/components/PageLayout";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { API_LIST_LIMITS } from "@/lib/constants";
import {
  getAdminBackupHealth,
  getAdminDeliverabilityHealth,
  getAdminFixtureAudit,
  safeGet,
  triggerBackup,
} from "@/api/api";
import { listStudents, updateStudent } from "@/api/students";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMemo, useState } from "react";

type LogRow = {
  id: string;
  actor: string;
  action: string;
  entity_type?: string;
  created_at?: string | null;
};

type Stu = { id: string; name: string; is_demo?: boolean };

export default function AdminTools() {
  const qc = useQueryClient();
  const [logFilter, setLogFilter] = useState<"all" | "followups">("all");

  const logsQ = useQuery({
    queryKey: ["admin", "logs"],
    queryFn: () => safeGet<LogRow[]>("/admin/logs", { limit: API_LIST_LIMITS.adminLogs }),
  });

  const studentsQ = useQuery({
    queryKey: ["students", "demo"],
    queryFn: () => listStudents({ include_demo: true }) as Promise<Stu[]>,
  });

  const fixtureAuditQ = useQuery({
    queryKey: ["admin", "fixture-audit"],
    queryFn: () => getAdminFixtureAudit(),
  });

  const backupHealthQ = useQuery({
    queryKey: ["admin", "backup-health"],
    queryFn: () => getAdminBackupHealth(),
  });

  const deliverabilityQ = useQuery({
    queryKey: ["admin", "deliverability-health"],
    queryFn: () => getAdminDeliverabilityHealth(),
  });

  const backupM = useMutation({
    mutationFn: () => triggerBackup(),
    onSuccess: (data) => {
      const f = (data as { backup_file?: string })?.backup_file;
      toast.success(f ? `Backup: ${f}` : "Backup started");
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Backup failed");
    },
  });

  const demoM = useMutation({
    mutationFn: ({ id, is_demo }: { id: string; is_demo: boolean }) => updateStudent(id, { is_demo }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["students"] });
      toast.success("Updated");
    },
  });

  const logColumns: ColumnDef<LogRow>[] = [
    {
      id: "t",
      header: "Time",
      cell: (r) => (
        <span className="text-xs text-muted-foreground whitespace-nowrap">{r.created_at ?? "—"}</span>
      ),
    },
    { id: "a", header: "Actor", cell: (r) => r.actor },
    { id: "ac", header: "Action", cell: (r) => r.action },
    { id: "e", header: "Entity", cell: (r) => r.entity_type ?? "—" },
  ];

  const logRowsRaw = (logsQ.data || []) as LogRow[];
  const followupActions = useMemo(
    () => new Set(["followup_sent", "followup_reconciled_mark_sent", "followup_reconciled_pause"]),
    []
  );
  const logRows =
    logFilter === "followups"
      ? logRowsRaw.filter((r) => followupActions.has(String(r.action || "").trim()))
      : logRowsRaw;

  return (
    <PageLayout
      title="Admin overview"
      subtitle="Backups, fixtures, logs, and demo controls · GET /admin/backup-health · deliverability-health · fixture-audit · POST /admin/backup"
      actions={
        <Button type="button" size="sm" disabled={backupM.isPending} onClick={() => backupM.mutate()}>
          Run backup
        </Button>
      }
    >
      <div className="mb-10 grid gap-4 lg:grid-cols-2">
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <PremiumCard className="overflow-hidden shadow-sm transition-all duration-300 hover:shadow-md">
            <div className="flex items-center gap-2 border-b border-border/60 bg-gradient-to-r from-indigo-500/[0.06] to-transparent p-4">
              <Database className="h-5 w-5 text-[#4F46E5]" />
              <h3 className="text-lg font-semibold">Database · demo students</h3>
            </div>
            <div className="max-h-56 min-h-[3rem] divide-y divide-border overflow-y-auto text-sm">
            {studentsQ.isLoading ? (
              <p className="px-3 py-4 text-muted-foreground text-sm">Loading students…</p>
            ) : studentsQ.isError ? (
              <p className="px-3 py-4 text-destructive text-sm">Could not load students.</p>
            ) : (studentsQ.data || []).length === 0 ? (
              <p className="px-3 py-4 text-muted-foreground text-sm">No students returned.</p>
            ) : (
              (studentsQ.data || []).map((s) => (
                <div key={s.id} className="flex items-center justify-between gap-2 px-3 py-2">
                  <span>{s.name}</span>
                  <Checkbox
                    checked={!!s.is_demo}
                    onCheckedChange={(v) => demoM.mutate({ id: s.id, is_demo: v === true })}
                    aria-label={`Mark ${s.name} as demo`}
                  />
                </div>
              ))
            )}
            </div>
          </PremiumCard>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <PremiumCard className="overflow-hidden shadow-sm transition-all duration-300 hover:shadow-md">
            <div className="flex items-center gap-2 border-b border-border/60 bg-gradient-to-r from-emerald-500/[0.06] to-transparent p-4">
              <Database className="h-5 w-5 text-emerald-600" />
              <h3 className="text-lg font-semibold">Fixture audit &amp; cleanup (read-only)</h3>
            </div>
            <div className="space-y-3 p-4 text-sm">
              <p className="text-muted-foreground">
                Live snapshot from <code className="rounded bg-muted px-1 py-0.5 text-xs">GET /admin/fixture-audit</code>.
                No deletes from this UI — use CLI on the server.
              </p>
              {fixtureAuditQ.isLoading ? (
                <p className="text-muted-foreground">Loading fixture audit…</p>
              ) : fixtureAuditQ.isError ? (
                <p className="text-destructive">Could not load fixture audit (check admin API key and backend).</p>
              ) : (
                <>
                  <div className="rounded-lg border border-border/60 bg-muted/30 p-3">
                    <p className="mb-1 font-medium text-xs uppercase tracking-wide text-muted-foreground">
                      Suggested commands (backend cwd)
                    </p>
                    <pre className="whitespace-pre-wrap break-all text-xs leading-relaxed">
                      {JSON.stringify(
                        (fixtureAuditQ.data as { suggested_commands?: Record<string, string> } | undefined)
                          ?.suggested_commands ?? {},
                        null,
                        2
                      )}
                    </pre>
                  </div>
                  <div className="rounded-lg border border-border/60 bg-background p-3">
                    <p className="mb-1 font-medium text-xs uppercase tracking-wide text-muted-foreground">
                      Full JSON (copy for support)
                    </p>
                    <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs leading-relaxed">
                      {JSON.stringify(fixtureAuditQ.data, null, 2)}
                    </pre>
                  </div>
                </>
              )}
            </div>
          </PremiumCard>
        </motion.div>
      </div>

      <div className="mb-10 grid gap-4 lg:grid-cols-2">
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <PremiumCard className="overflow-hidden shadow-sm transition-all duration-300 hover:shadow-md">
            <div className="flex items-center gap-2 border-b border-border/60 bg-gradient-to-r from-sky-500/[0.06] to-transparent p-4">
              <HardDrive className="h-5 w-5 text-sky-600" />
              <h3 className="text-lg font-semibold">Backup &amp; recovery health</h3>
            </div>
            <div className="space-y-3 p-4 text-sm">
              <p className="text-muted-foreground">
                Read-only <code className="rounded bg-muted px-1 py-0.5 text-xs">GET /admin/backup-health</code> — manifests,
                integrity checks, DR hints.
              </p>
              {backupHealthQ.isLoading ? (
                <p className="text-muted-foreground">Loading…</p>
              ) : backupHealthQ.isError ? (
                <p className="text-destructive">Could not load backup health.</p>
              ) : (
                <>
                  <div className="rounded-lg border border-border/60 bg-muted/30 p-3">
                    <p className="mb-1 font-medium text-xs uppercase tracking-wide text-muted-foreground">Suggested commands</p>
                    <pre className="whitespace-pre-wrap break-all text-xs leading-relaxed">
                      {JSON.stringify(
                        (backupHealthQ.data as { suggested_commands?: Record<string, string> } | undefined)
                          ?.suggested_commands ?? {},
                        null,
                        2
                      )}
                    </pre>
                  </div>
                  <pre className="max-h-48 overflow-auto rounded-lg border border-border/60 bg-background p-3 text-xs leading-relaxed whitespace-pre-wrap break-all">
                    {JSON.stringify(backupHealthQ.data, null, 2)}
                  </pre>
                </>
              )}
            </div>
          </PremiumCard>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <PremiumCard className="overflow-hidden shadow-sm transition-all duration-300 hover:shadow-md">
            <div className="flex items-center gap-2 border-b border-border/60 bg-gradient-to-r from-violet-500/[0.06] to-transparent p-4">
              <ShieldCheck className="h-5 w-5 text-violet-600" />
              <h3 className="text-lg font-semibold">Deliverability health</h3>
            </div>
            <div className="space-y-3 p-4 text-sm">
              <p className="text-muted-foreground">
                <code className="rounded bg-muted px-1 py-0.5 text-xs">GET /admin/deliverability-health</code> — aggregate
                sends vs failures; enable layer with{" "}
                <code className="rounded bg-muted px-1 py-0.5 text-xs">DELIVERABILITY_LAYER=1</code>.
              </p>
              {deliverabilityQ.isLoading ? (
                <p className="text-muted-foreground">Loading…</p>
              ) : deliverabilityQ.isError ? (
                <p className="text-destructive">Could not load deliverability health.</p>
              ) : (
                <pre className="max-h-64 overflow-auto rounded-lg border border-border/60 bg-background p-3 text-xs leading-relaxed whitespace-pre-wrap break-all">
                  {JSON.stringify(deliverabilityQ.data, null, 2)}
                </pre>
              )}
            </div>
          </PremiumCard>
        </motion.div>
      </div>

      {logsQ.isError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Backend error — check server logs</AlertTitle>
          <AlertDescription>GET /admin/logs failed.</AlertDescription>
        </Alert>
      ) : null}

      <div className="mb-4 space-y-3">
        <div className="flex items-center gap-2 rounded-xl border border-border/60 bg-gradient-to-r from-slate-500/[0.06] to-transparent p-4 shadow-sm transition-all duration-300 hover:shadow-md">
          <ScrollText className="h-5 w-5 text-muted-foreground" />
          <h3 className="text-lg font-semibold">Audit log</h3>
        </div>
        <Tabs value={logFilter} onValueChange={(v) => setLogFilter(v as any)}>
          <TabsList className="w-full justify-start">
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="followups">Follow-up events</TabsTrigger>
          </TabsList>
        </Tabs>
        {logsQ.isLoading ? null : (
          <p className="mb-2 text-xs text-muted-foreground">
            Showing {logRows.length.toLocaleString()} audit entr{logRows.length === 1 ? "y" : "ies"} (API limit{" "}
            {API_LIST_LIMITS.adminLogs.toLocaleString()}).
            {logsQ.isSuccess && logRows.length >= API_LIST_LIMITS.adminLogs ? (
              <span className="ml-1 font-medium text-amber-700 dark:text-amber-400">
                Older entries may be truncated.
              </span>
            ) : null}
          </p>
        )}
        <DataTable<LogRow>
          columns={logColumns}
          data={logsQ.isError ? [] : logRows}
          getRowKey={(r, i) => String(r.id ?? `log-${i}`)}
          loading={logsQ.isLoading}
          emptyMessage={logsQ.isError ? "Request failed." : "No entries."}
        />
      </div>
    </PageLayout>
  );
}
