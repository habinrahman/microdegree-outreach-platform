import { useMemo, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Eye, PauseCircle, Link2, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import { PageLayout } from "@/components/PageLayout";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";
import {
  getEligibleFollowups,
  getFollowupPreview,
  listStaleProcessingFollowups,
  reconcileMarkSent,
  reconcilePause,
  sendManualFollowup,
  getFollowupsDispatchSettings,
  getFollowupsSettingsChecksum,
  getFollowupFunnelSummary,
  putFollowupsDispatchSettings,
  type FollowupRow,
  type FollowupStatus,
} from "@/api/followups";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

type FilterTab = "due" | "waiting" | "paused" | "stopped" | "all";

function toneForFollowupStatus(s: FollowupStatus) {
  switch (s) {
    case "DUE_NOW":
      return "success";
    case "SEND_IN_PROGRESS":
      return "pending";
    case "PAUSED":
      return "pending";
    case "WAITING":
      return "neutral";
    case "REPLIED_STOPPED":
      return "replied";
    case "BOUNCED_STOPPED":
      return "failed";
    case "COMPLETED_STOPPED":
      return "neutral";
    default:
      return "neutral";
  }
}

function isStopped(s: FollowupStatus): boolean {
  return s === "REPLIED_STOPPED" || s === "BOUNCED_STOPPED" || s === "COMPLETED_STOPPED";
}

function formatUtc(ts: string | null | undefined): string {
  const t = String(ts ?? "").trim();
  if (!t) return "—";
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? t : d.toLocaleString();
}

export default function FollowUps() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<FilterTab>("due");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [selected, setSelected] = useState<FollowupRow | null>(null);
  const [sending, setSending] = useState(false);
  const [reconcileConfirmOpen, setReconcileConfirmOpen] = useState<null | { mode: "mark_sent" | "pause"; campaignId: string }>(null);
  const [dispatchReason, setDispatchReason] = useState("");

  const PAGE = 50;

  const eligibleQ = useInfiniteQuery({
    queryKey: ["followups", "eligible", PAGE],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      getEligibleFollowups({ limit: PAGE, offset: typeof pageParam === "number" ? pageParam : 0 }),
    getNextPageParam: (lastPage) => {
      const p = lastPage.pagination;
      if (!p?.has_more || p.next_offset == null) return undefined;
      return p.next_offset;
    },
    refetchInterval: 30_000,
    refetchIntervalInBackground: true,
  });

  const flatRows = useMemo(
    () => eligibleQ.data?.pages.flatMap((p) => p.rows) ?? [],
    [eligibleQ.data?.pages]
  );

  const mergedSummary = useMemo(() => {
    let due_now = 0;
    let blocked = 0;
    let paused = 0;
    let completed = 0;
    for (const p of eligibleQ.data?.pages ?? []) {
      due_now += p.summary.due_now;
      blocked += p.summary.blocked;
      paused += p.summary.paused;
      completed += p.summary.completed;
    }
    return {
      total: flatRows.length,
      due_now,
      blocked,
      paused,
      completed,
    };
  }, [eligibleQ.data?.pages, flatRows.length]);

  const mergedStatusBreakdown = useMemo(() => {
    const acc: Record<string, number> = {};
    for (const p of eligibleQ.data?.pages ?? []) {
      for (const [k, v] of Object.entries(p.status_breakdown ?? {})) {
        acc[k] = (acc[k] ?? 0) + (typeof v === "number" ? v : 0);
      }
    }
    return acc;
  }, [eligibleQ.data?.pages]);

  const totalPairsInScope = eligibleQ.data?.pages[0]?.pagination?.total_pairs;

  const previewQ = useQuery({
    queryKey: ["followups", "preview", selected?.student_id, selected?.hr_id],
    queryFn: () =>
      getFollowupPreview({
        student_id: String(selected?.student_id ?? ""),
        hr_id: String(selected?.hr_id ?? ""),
      }),
    enabled: Boolean(previewOpen && selected?.student_id && selected?.hr_id),
    retry: 0,
  });

  const staleQ = useQuery({
    queryKey: ["followups", "reconcile", "stale"],
    queryFn: () => listStaleProcessingFollowups({ threshold_minutes: 15, limit: 200 }),
    refetchInterval: 30_000,
    refetchIntervalInBackground: true,
  });

  const dispatchQ = useQuery({
    queryKey: ["followups", "dispatch-settings"],
    queryFn: getFollowupsDispatchSettings,
    staleTime: 10_000,
    /** Do not block the rest of the page on repeated refetches if this endpoint errors. */
    retry: 1,
  });

  const checksumQ = useQuery({
    queryKey: ["followups", "dispatch-checksum"],
    queryFn: getFollowupsSettingsChecksum,
    staleTime: 15_000,
    retry: 1,
  });

  const funnelQ = useQuery({
    queryKey: ["followups", "funnel"],
    queryFn: getFollowupFunnelSummary,
    refetchInterval: 60_000,
  });

  const setDispatchMutation = useMutation({
    mutationFn: (payload: { enabled: boolean; reason?: string | null }) => putFollowupsDispatchSettings(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["followups", "dispatch-settings"] });
      queryClient.invalidateQueries({ queryKey: ["followups", "dispatch-checksum"] });
      setDispatchReason("");
      toast.success("Follow-up dispatch setting saved");
    },
    onError: () => toast.error("Could not update follow-up dispatch"),
  });

  const rows = useMemo(() => {
    const raw = flatRows;
    if (tab === "all") return raw;
    if (tab === "due") return raw.filter((r) => r.followup_status === "DUE_NOW");
    if (tab === "waiting") return raw.filter((r) => r.followup_status === "WAITING" || r.followup_status === "SEND_IN_PROGRESS");
    if (tab === "paused") return raw.filter((r) => r.followup_status === "PAUSED");
    if (tab === "stopped") return raw.filter((r) => isStopped(r.followup_status));
    return raw;
  }, [flatRows, tab]);

  const summary = mergedSummary;
  const statusBreakdown = mergedStatusBreakdown;

  const computed = useMemo(() => {
    const all = flatRows;
    const waiting = all.filter((r) => r.followup_status === "WAITING").length;
    const stopped = all.filter((r) => isStopped(r.followup_status)).length;
    const inProgress = all.filter((r) => r.followup_status === "SEND_IN_PROGRESS").length;
    return { waiting, stopped, inProgress };
  }, [flatRows]);

  const columns: ColumnDef<FollowupRow>[] = useMemo(
    () => [
      {
        id: "student",
        header: "Student",
        className: "min-w-[160px]",
        cell: (r) => (
          <div className="leading-tight">
            <div className="font-medium text-foreground">{r.student_name || r.student_id}</div>
            <div className="text-xs text-muted-foreground">{r.student_id}</div>
          </div>
        ),
      },
      {
        id: "hr",
        header: "HR",
        className: "min-w-[220px]",
        cell: (r) => (
          <div className="leading-tight">
            <div className="font-medium text-foreground">{r.company || "—"}</div>
            <div className="text-xs text-muted-foreground">{r.hr_email || r.hr_id}</div>
          </div>
        ),
      },
      {
        id: "current_step",
        header: "Current Step",
        className: "whitespace-nowrap",
        cell: (r) => (
          <span className="tabular-nums text-sm">{`FU${Math.max(0, r.current_step)}`}</span>
        ),
      },
      {
        id: "next",
        header: "Next Follow-up",
        className: "whitespace-nowrap",
        cell: (r) => (
          <span className="tabular-nums text-sm">
            {r.next_followup_step ? `FU${r.next_followup_step}` : "—"}
          </span>
        ),
      },
      {
        id: "due_date",
        header: "Due Date",
        className: "min-w-[170px] whitespace-nowrap",
        cell: (r) => <span className="text-sm">{formatUtc(r.due_date_utc)}</span>,
      },
      {
        id: "days",
        header: "Days Until Due",
        className: "whitespace-nowrap tabular-nums",
        cell: (r) => {
          const v = r.days_until_due;
          if (v == null) return <span className="text-muted-foreground">—</span>;
          const cls =
            v === 0 ? "text-emerald-700 dark:text-emerald-400" : v < 0 ? "text-red-700 dark:text-red-400" : "";
          return <span className={cn("text-sm", cls)}>{v}</span>;
        },
      },
      {
        id: "status",
        header: "Status",
        className: "whitespace-nowrap",
        cell: (r) => (
          <StatusBadge
            tone={toneForFollowupStatus(r.followup_status) as any}
            className={cn(r.followup_status === "SEND_IN_PROGRESS" && "animate-pulse")}
          >
            {r.followup_status}
          </StatusBadge>
        ),
      },
      {
        id: "blocked",
        header: "Blocked Reason",
        className: "min-w-[260px]",
        cell: (r) => (
          <span className={cn("text-sm", r.blocked_reason ? "text-muted-foreground" : "text-muted-foreground")}>
            {r.blocked_reason || "—"}
          </span>
        ),
      },
      {
        id: "action",
        header: "Action",
        className: "whitespace-nowrap",
        cell: (r) => {
          const viewThreadTo = `${ROUTES.campaigns}?student_id=${encodeURIComponent(
            r.student_id
          )}&hr_id=${encodeURIComponent(r.hr_id)}`;
          const locked = r.followup_status === "SEND_IN_PROGRESS";
          return (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setSelected(r);
                  setPreviewOpen(true);
                }}
              >
                <Eye className="mr-1 h-4 w-4" />
                Preview
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={locked}
                onClick={() => toast.info("Pause/unpause will be wired after Step 2C send safety model.")}
              >
                <PauseCircle className="mr-1 h-4 w-4" />
                Pause
              </Button>
              <Button asChild variant="outline" size="sm">
                <Link to={viewThreadTo}>
                  <Link2 className="mr-1 h-4 w-4" />
                  View thread
                </Link>
              </Button>
            </div>
          );
        },
      },
    ],
    []
  );

  return (
    <>
      <PageLayout
      title="Follow-ups"
      subtitle="Read-only operator console. Eligible pairs load 50 at a time (Load more). Default tab is Due now — use All for stopped, waiting, and completed among loaded rows."
      actions={
        <Button
          variant="outline"
          onClick={() => eligibleQ.refetch()}
          disabled={eligibleQ.isFetching}
          title={eligibleQ.isFetching ? "Refreshing…" : "Refresh"}
        >
          <RefreshCw className={cn("mr-2 h-4 w-4", eligibleQ.isFetching && "animate-spin")} />
          Refresh
        </Button>
      }
      filters={
        <div className="space-y-3">
          <PremiumCard className="p-4 space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border/60 pb-4">
              <div className="min-w-0 space-y-1">
                <div className="text-xs font-medium text-muted-foreground">Scheduler follow-up sends</div>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Off pauses automated follow-up delivery; queued rows are kept.{" "}
                  <span className="font-mono text-[10px]">FOLLOWUPS_ENABLED</span> on the server remains the hard
                  kill-switch.
                </p>
                {checksumQ.data ? (
                  <p className="text-xs font-mono text-muted-foreground leading-relaxed">
                    Ops checksum: effective_dispatch={String(checksumQ.data.effective_dispatch)} · source=
                    {checksumQ.data.source} · env={String(checksumQ.data.followups_env_enabled)} · db_toggle=
                    {checksumQ.data.dispatch_toggle === null ? "null" : String(checksumQ.data.dispatch_toggle)}
                  </p>
                ) : checksumQ.isError ? (
                  <p className="text-xs text-muted-foreground">Checksum unavailable (non-blocking).</p>
                ) : null}
                {dispatchQ.isError ? (
                  <p className="text-xs text-amber-700 dark:text-amber-400">
                    Could not load dispatch settings from the server. The UI assumes the safe default (dispatch ON)
                    until the request succeeds — other follow-up data below still loads independently.
                  </p>
                ) : null}
                {dispatchQ.data && !dispatchQ.data.followups_env_enabled ? (
                  <p className="text-xs text-amber-700 dark:text-amber-400">
                    Server env has follow-ups disabled — this toggle cannot enable sends until ops flips env.
                  </p>
                ) : null}
              </div>
              <div className="flex shrink-0 flex-col items-stretch gap-2 pt-0.5 sm:items-end sm:min-w-[200px]">
                <Textarea
                  placeholder="Audit note (optional) — incident id, ticket, or reason; sent with toggle change."
                  value={dispatchReason}
                  onChange={(e) => setDispatchReason(e.target.value)}
                  disabled={setDispatchMutation.isPending || (dispatchQ.isSuccess && dispatchQ.data.followups_env_enabled === false)}
                  className="min-h-[52px] max-h-24 text-xs resize-y"
                  rows={2}
                />
                <div className="flex items-center gap-2 justify-end">
                <Switch
                  id="followup-dispatch"
                  checked={
                    dispatchQ.isError
                      ? true
                      : Boolean(dispatchQ.data?.followups_dispatch_enabled)
                  }
                  disabled={
                    dispatchQ.isLoading ||
                    dispatchQ.isFetching ||
                    setDispatchMutation.isPending ||
                    dispatchQ.isError ||
                    (dispatchQ.isSuccess && dispatchQ.data.followups_env_enabled === false)
                  }
                  onCheckedChange={(v) =>
                    setDispatchMutation.mutate({
                      enabled: v,
                      reason: dispatchReason.trim() || undefined,
                    })
                  }
                />
                <Label htmlFor="followup-dispatch" className="text-sm cursor-pointer">
                  {dispatchQ.isError ? "On (default)" : dispatchQ.data?.followups_dispatch_enabled ? "On" : "Off"}
                </Label>
                </div>
              </div>
            </div>
            <div>
              <div className="text-xs font-medium text-muted-foreground">Sequence funnel (approx.)</div>
              <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
                <span>
                  Initial sent:{" "}
                  <span className="font-semibold text-foreground">{funnelQ.data?.initial_sent ?? "—"}</span>
                </span>
                <span>
                  FU1: <span className="font-semibold text-foreground">{funnelQ.data?.followup_1_sent ?? "—"}</span>
                </span>
                <span>
                  FU2: <span className="font-semibold text-foreground">{funnelQ.data?.followup_2_sent ?? "—"}</span>
                </span>
                <span>
                  FU3: <span className="font-semibold text-foreground">{funnelQ.data?.followup_3_sent ?? "—"}</span>
                </span>
                <span>
                  Cancelled FU:{" "}
                  <span className="font-semibold text-foreground">{funnelQ.data?.followup_rows_cancelled ?? "—"}</span>
                </span>
                <span>
                  Replied:{" "}
                  <span className="font-semibold text-foreground">{funnelQ.data?.campaign_rows_status_replied ?? "—"}</span>
                </span>
              </div>
            </div>
          </PremiumCard>

          <div className="grid gap-3 md:grid-cols-4">
            <PremiumCard className="p-4">
              <div className="text-xs text-muted-foreground">Due now</div>
              <div className="mt-1 text-2xl font-bold tabular-nums">{summary.due_now.toLocaleString()}</div>
            </PremiumCard>
            <PremiumCard className="p-4">
              <div className="text-xs text-muted-foreground">Waiting</div>
              <div className="mt-1 text-2xl font-bold tabular-nums">{computed.waiting.toLocaleString()}</div>
              {computed.inProgress ? (
                <div className="mt-1 text-xs text-muted-foreground">
                  <span className="font-medium">{computed.inProgress.toLocaleString()}</span> in progress
                </div>
              ) : null}
            </PremiumCard>
            <PremiumCard className="p-4">
              <div className="text-xs text-muted-foreground">Paused</div>
              <div className="mt-1 text-2xl font-bold tabular-nums">{summary.paused.toLocaleString()}</div>
            </PremiumCard>
            <PremiumCard className="p-4">
              <div className="text-xs text-muted-foreground">Completed / stopped</div>
              <div className="mt-1 text-2xl font-bold tabular-nums">{computed.stopped.toLocaleString()}</div>
            </PremiumCard>
          </div>

          {Object.keys(statusBreakdown).length > 0 ? (
            <PremiumCard className="p-4">
              <div className="text-xs font-medium text-muted-foreground">Status distribution (loaded pages)</div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                {Object.entries(statusBreakdown).map(([k, v]) => (
                  <span key={k} className="tabular-nums">
                    <span className="font-medium text-foreground">{k}</span>: {v}
                  </span>
                ))}
              </div>
            </PremiumCard>
          ) : null}

          {typeof totalPairsInScope === "number" ? (
            <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
              <span className="tabular-nums">
                Loaded <span className="font-medium text-foreground">{flatRows.length}</span> of{" "}
                <span className="font-medium text-foreground">{totalPairsInScope}</span> student–HR pairs with a sent
                initial.
              </span>
              {eligibleQ.hasNextPage ? (
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={eligibleQ.isFetchingNextPage}
                  onClick={() => eligibleQ.fetchNextPage()}
                >
                  {eligibleQ.isFetchingNextPage ? "Loading…" : `Load more (${PAGE} per page)`}
                </Button>
              ) : null}
            </div>
          ) : null}

          <Tabs value={tab} onValueChange={(v) => setTab(v as FilterTab)}>
            <TabsList className="w-full justify-start">
              <TabsTrigger value="due">Due now</TabsTrigger>
              <TabsTrigger value="waiting">Waiting</TabsTrigger>
              <TabsTrigger value="paused">Paused</TabsTrigger>
              <TabsTrigger value="stopped">Stopped</TabsTrigger>
              <TabsTrigger value="all">All</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      }
    >
      <DataTable
        columns={columns}
        data={rows}
        loading={eligibleQ.isPending && !eligibleQ.data?.pages?.length}
        getRowKey={(r) => `${r.student_id}:${r.hr_id}`}
        getRowProps={(r) => ({
          className: cn(
            r.followup_status === "DUE_NOW" && "bg-emerald-500/5",
            r.followup_status === "SEND_IN_PROGRESS" && "opacity-75"
          ),
        })}
        emptyMessage={
          eligibleQ.isError
            ? "Failed to load follow-ups."
            : tab === "due" && flatRows.length > 0
              ? "Nothing due right now for this filter — try Waiting or All."
              : "No follow-ups in this view."
        }
      />
      </PageLayout>

      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Follow-up preview</DialogTitle>
            <DialogDescription>
              Server-side preview. Eligibility is re-checked again at send time.
            </DialogDescription>
          </DialogHeader>

          {previewQ.isLoading ? (
            <div className="text-sm text-muted-foreground">Loading preview…</div>
          ) : previewQ.isError ? (
            <div className="text-sm text-red-600">Failed to load preview.</div>
          ) : (
            <div className="space-y-4">
              {previewQ.data?.thread && previewQ.data.thread.thread_continuity === false ? (
                <PremiumCard className="p-4 border-amber-500/30 bg-amber-500/5">
                  <div className="text-sm font-medium text-amber-800 dark:text-amber-300">
                    Thread continuity unavailable
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    No prior Message-ID chain was found. If you send, it may start a new email thread.
                  </div>
                </PremiumCard>
              ) : null}
              <div className="grid gap-3 md:grid-cols-2">
                <PremiumCard className="p-4">
                  <div className="text-xs text-muted-foreground">Template type</div>
                  <div className="mt-1 font-medium">
                    {String((previewQ.data?.template as any)?.template_type ?? "—")}
                  </div>
                </PremiumCard>
                <PremiumCard className="p-4">
                  <div className="text-xs text-muted-foreground">Recipient</div>
                  <div className="mt-1 font-medium">
                    {String(previewQ.data?.thread?.hr_email ?? selected?.hr_email ?? "—")}
                  </div>
                </PremiumCard>
              </div>

              <PremiumCard className="p-4">
                <div className="text-xs text-muted-foreground">Subject</div>
                <div className="mt-1 font-medium break-words">
                  {String((previewQ.data?.template as any)?.subject ?? "—")}
                </div>
              </PremiumCard>

              <PremiumCard className="p-4">
                <div className="text-xs text-muted-foreground">Body</div>
                <pre className="mt-2 max-h-[40vh] overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">
                  {String((previewQ.data?.template as any)?.body ?? "—")}
                </pre>
              </PremiumCard>

              <PremiumCard className="p-4">
                <div className="text-xs text-muted-foreground">Eligibility snapshot</div>
                <pre className="mt-2 max-h-[30vh] overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
                  {JSON.stringify(previewQ.data?.eligibility ?? {}, null, 2)}
                </pre>
              </PremiumCard>
            </div>
          )}

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                if (!selected) return;
                const to = `${ROUTES.campaigns}?student_id=${encodeURIComponent(
                  selected.student_id
                )}&hr_id=${encodeURIComponent(selected.hr_id)}`;
                window.location.assign(to);
              }}
            >
              View thread
            </Button>
            {(() => {
              // Note: stale list is by follow-up campaign row id (processing followup_* rows).
              // The table rows are keyed by (student_id, hr_id), so we match on that pair.
              if (!selected || selected.followup_status !== "SEND_IN_PROGRESS") return null;
              const items = staleQ.data?.rows ?? [];
              const match = items.find((x) => x.student_id === selected.student_id && x.hr_id === selected.hr_id);
              if (!match) return null;
              return (
                <>
                  <Button
                    variant="outline"
                    disabled={sending}
                    onClick={() => setReconcileConfirmOpen({ mode: "pause", campaignId: match.campaign_id })}
                    title="Reset to paused (no resend)"
                  >
                    Reset to paused
                  </Button>
                  <Button
                    variant="outline"
                    disabled={sending}
                    onClick={() => setReconcileConfirmOpen({ mode: "mark_sent", campaignId: match.campaign_id })}
                    title="Mark as sent (reconcile unknown outcome)"
                  >
                    Mark as sent
                  </Button>
                </>
              );
            })()}
            <Button
              disabled={
                sending ||
                !selected ||
                Boolean((previewQ.data as any)?.template_missing) ||
                selected.followup_status === "SEND_IN_PROGRESS"
              }
              onClick={() => setConfirmOpen(true)}
              title={
                (previewQ.data as any)?.template_missing
                  ? "Missing template — cannot send"
                  : selected?.followup_status === "SEND_IN_PROGRESS"
                    ? "Send in progress"
                    : "Send follow-up"
              }
            >
              Send follow-up
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Send follow-up now?</AlertDialogTitle>
            <AlertDialogDescription>
              This will send a single follow-up email for{" "}
              <span className="font-medium">{selected?.student_name ?? "student"}</span> →{" "}
              <span className="font-medium">{selected?.hr_email ?? "recipient"}</span>. The server will re-check
              eligibility and block if anything changed.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={sending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={sending || !selected}
              onClick={async () => {
                if (!selected) return;
                setSending(true);
                try {
                  const res = await sendManualFollowup({
                    student_id: selected.student_id,
                    hr_id: selected.hr_id,
                  });
                  if (res?.dry_run) {
                    toast.success(
                      `Dry run: would send${res?.would_send?.step ? ` FU${res.would_send.step}` : ""}.`
                    );
                  } else if (res?.already_sent) toast.success("Already sent (idempotent).");
                  else toast.success(`Follow-up sent${res?.step ? ` (FU${res.step})` : ""}.`);
                  setConfirmOpen(false);
                  setPreviewOpen(false);
                  await eligibleQ.refetch();
                } catch (e: any) {
                  const msg =
                    e?.response?.data?.detail ||
                    e?.message ||
                    "Send failed. Eligibility may have changed; refresh and try again.";
                  toast.error(String(msg));
                } finally {
                  setSending(false);
                }
              }}
            >
              Send now
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={Boolean(reconcileConfirmOpen)}
        onOpenChange={(open) => {
          if (!open) setReconcileConfirmOpen(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {reconcileConfirmOpen?.mode === "mark_sent"
                ? "Mark as sent (reconcile)?"
                : "Reset to paused (reconcile)?"}
            </AlertDialogTitle>
            <AlertDialogDescription>
              This is a repair action for stale <code>processing</code> follow-up rows (unknown send outcome). It will{" "}
              <span className="font-medium">not</span> resend email.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={sending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={sending || !reconcileConfirmOpen}
              onClick={async () => {
                if (!reconcileConfirmOpen) return;
                setSending(true);
                try {
                  if (reconcileConfirmOpen.mode === "mark_sent") {
                    await reconcileMarkSent({ campaign_id: reconcileConfirmOpen.campaignId, threshold_minutes: 15 });
                    toast.success("Reconciled: marked sent.");
                  } else {
                    await reconcilePause({ campaign_id: reconcileConfirmOpen.campaignId, threshold_minutes: 15 });
                    toast.success("Reconciled: paused.");
                  }
                  setReconcileConfirmOpen(null);
                  await staleQ.refetch();
                  await eligibleQ.refetch();
                } catch (e: any) {
                  const msg = e?.response?.data?.detail || e?.message || "Reconcile failed.";
                  toast.error(String(msg));
                } finally {
                  setSending(false);
                }
              }}
            >
              Confirm
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

