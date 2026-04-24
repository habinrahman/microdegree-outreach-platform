import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  ArrowDown,
  ArrowUp,
  Gauge,
  Loader2,
  Minus,
  Sparkles,
  Timer,
  ShieldAlert,
  Zap,
} from "lucide-react";
import { PageLayout } from "@/components/PageLayout";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatApiFailureLabel } from "@/api/api";
import { listStudents } from "@/api/students";
import {
  fetchPriorityQueue,
  loadPrevQueueMap,
  rowPairKey,
  saveQueueSnapshot,
  type PriorityQueueRow,
  type QueueBucket,
} from "@/api/priorityQueue";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";

const BUCKETS: { id: QueueBucket | "all"; label: string }[] = [
  { id: "all", label: "All buckets" },
  { id: "SEND_NOW", label: "Send now" },
  { id: "FOLLOW_UP_DUE", label: "Follow-up due" },
  { id: "WARM_LEAD_PRIORITY", label: "Warm leads" },
  { id: "WAIT_FOR_COOLDOWN", label: "Cooldown" },
  { id: "LOW_PRIORITY", label: "Low priority" },
  { id: "SUPPRESS", label: "Suppressed" },
];

function bucketBadgeClass(b: string) {
  const u = b.toUpperCase();
  if (u === "SEND_NOW") return "bg-emerald-600/15 text-emerald-800 dark:text-emerald-300 border-emerald-500/30";
  if (u === "FOLLOW_UP_DUE") return "bg-violet-600/15 text-violet-900 dark:text-violet-200 border-violet-500/30";
  if (u === "WARM_LEAD_PRIORITY") return "bg-amber-500/15 text-amber-950 dark:text-amber-200 border-amber-500/30";
  if (u === "WAIT_FOR_COOLDOWN") return "bg-sky-600/15 text-sky-900 dark:text-sky-200 border-sky-500/25";
  if (u === "SUPPRESS") return "bg-rose-600/15 text-rose-950 dark:text-rose-200 border-rose-500/30";
  return "bg-muted text-muted-foreground border-border";
}

function urgencyBadge(u: string) {
  const x = (u || "").toUpperCase();
  if (x === "CRITICAL") return "destructive";
  if (x === "HIGH") return "default";
  if (x === "MEDIUM") return "secondary";
  return "outline";
}

function movementHint(
  row: PriorityQueueRow,
  prev: Record<string, { rank: number; fingerprint: string }>
): { label: string; tone: "up" | "down" | "chg" | "same" } | null {
  const k = rowPairKey(row);
  const p = prev[k];
  if (!p) return null;
  if (p.fingerprint !== row.signal_fingerprint && p.rank !== row.priority_rank) {
    if (row.priority_rank < p.rank) return { label: `↑ rank ${p.rank}→${row.priority_rank}`, tone: "up" };
    if (row.priority_rank > p.rank) return { label: `↓ rank ${p.rank}→${row.priority_rank}`, tone: "down" };
    return { label: "↷ signals changed", tone: "chg" };
  }
  if (p.fingerprint !== row.signal_fingerprint) return { label: "↷ signals changed", tone: "chg" };
  if (p.rank !== row.priority_rank) {
    if (row.priority_rank < p.rank) return { label: `↑ rank ${p.rank}→${row.priority_rank}`, tone: "up" };
    if (row.priority_rank > p.rank) return { label: `↓ rank ${p.rank}→${row.priority_rank}`, tone: "down" };
  }
  return null;
}

export default function PriorityQueue() {
  const [bucket, setBucket] = useState<string>("all");
  const [tier, setTier] = useState<string>("all");
  const [studentId, setStudentId] = useState<string>("all");
  const [onlyDue, setOnlyDue] = useState(false);
  const [limit, setLimit] = useState("200");
  const [diversifiedRanking, setDiversifiedRanking] = useState(false);
  const [detail, setDetail] = useState<PriorityQueueRow | null>(null);

  const studentsQ = useQuery({
    queryKey: ["students", "priority-queue"],
    queryFn: () => listStudents({ include_demo: false }) as Promise<{ id: string; name: string }[]>,
  });

  const pq = useQuery({
    queryKey: ["priority-queue", bucket, tier, studentId, onlyDue, limit, diversifiedRanking],
    queryFn: () =>
      fetchPriorityQueue({
        bucket: bucket === "all" ? undefined : bucket,
        tier: tier === "all" ? undefined : tier,
        student_id: studentId === "all" ? undefined : studentId,
        only_due: onlyDue,
        limit: Math.min(500, Math.max(1, parseInt(limit, 10) || 200)),
        include_demo: false,
        diversified: diversifiedRanking,
      }),
  });

  const prevMap = useMemo(() => loadPrevQueueMap(), [pq.data]);

  const onSaveSnapshot = useCallback(() => {
    if (pq.data?.rows?.length) saveQueueSnapshot(pq.data.rows);
  }, [pq.data?.rows]);

  const summary = pq.data?.summary;
  const rows = pq.data?.rows ?? [];
  const dm = pq.data?.diversity_metrics as Record<string, unknown> | undefined;

  return (
    <PageLayout
      title="Priority queue"
      subtitle="Read-only sequencing cockpit — ranked who to email next. Does not send mail or change the scheduler."
      actions={
        <Button variant="outline" size="sm" asChild>
          <Link to={ROUTES.decisionDiagnostics}>Decision diagnostics</Link>
        </Button>
      }
      filters={
        <PremiumCard className="p-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1.5 min-w-[160px]">
              <Label className="text-xs text-muted-foreground">Bucket</Label>
              <Select value={bucket} onValueChange={setBucket}>
                <SelectTrigger>
                  <SelectValue placeholder="Bucket" />
                </SelectTrigger>
                <SelectContent>
                  {BUCKETS.map((b) => (
                    <SelectItem key={b.id} value={b.id}>
                      {b.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5 min-w-[160px]">
              <Label className="text-xs text-muted-foreground">HR tier</Label>
              <Select value={tier} onValueChange={setTier}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All tiers</SelectItem>
                  <SelectItem value="A">A</SelectItem>
                  <SelectItem value="B">B</SelectItem>
                  <SelectItem value="C">C</SelectItem>
                  <SelectItem value="D">D</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5 min-w-[200px]">
              <Label className="text-xs text-muted-foreground">Student</Label>
              <Select value={studentId} onValueChange={setStudentId}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All students</SelectItem>
                  {(studentsQ.data || []).map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5 min-w-[100px]">
              <Label className="text-xs text-muted-foreground">Limit</Label>
              <Select value={limit} onValueChange={setLimit}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="100">100</SelectItem>
                  <SelectItem value="200">200</SelectItem>
                  <SelectItem value="300">300</SelectItem>
                  <SelectItem value="500">500</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2 pb-0.5">
              <Checkbox id="onlyDue" checked={onlyDue} onCheckedChange={(v) => setOnlyDue(Boolean(v))} />
              <Label htmlFor="onlyDue" className="text-sm cursor-pointer">
                Only due (send / FU)
              </Label>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Ranking</Label>
              <div className="flex rounded-md border border-border bg-muted/40 p-0.5">
                <Button
                  type="button"
                  size="sm"
                  variant={!diversifiedRanking ? "secondary" : "ghost"}
                  className="h-8 px-3"
                  onClick={() => setDiversifiedRanking(false)}
                >
                  Standard
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={diversifiedRanking ? "secondary" : "ghost"}
                  className="h-8 px-3"
                  onClick={() => setDiversifiedRanking(true)}
                >
                  Diversified
                </Button>
              </div>
            </div>
            <Button type="button" variant="secondary" size="sm" onClick={() => pq.refetch()}>
              Refresh
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={onSaveSnapshot}>
              Save snapshot (movement)
            </Button>
          </div>
        </PremiumCard>
      }
    >
      {pq.isError ? (
        <PremiumCard className="p-6 space-y-3 border border-destructive/30">
          <p className="text-sm font-medium text-destructive">Unable to load priority queue</p>
          <p className="text-xs text-muted-foreground">{formatApiFailureLabel(pq.error)}</p>
          <Button variant="outline" size="sm" type="button" onClick={() => pq.refetch()} disabled={pq.isFetching}>
            Retry
          </Button>
        </PremiumCard>
      ) : null}

      {summary ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            {
              title: "Send now",
              value: summary.send_now_count,
              icon: Zap,
              accent: "from-emerald-500/20 to-transparent",
            },
            {
              title: "Due follow-ups",
              value: summary.followup_due_count,
              icon: Timer,
              accent: "from-violet-500/20 to-transparent",
            },
            {
              title: "Warm leads",
              value: summary.warm_lead_priority_count,
              icon: Sparkles,
              accent: "from-amber-500/25 to-transparent",
            },
            {
              title: "Suppressed",
              value: summary.suppressed_count,
              icon: ShieldAlert,
              accent: "from-rose-500/20 to-transparent",
            },
          ].map((c) => (
            <motion.div key={c.title} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
              <PremiumCard
                className={cn(
                  "relative overflow-hidden p-5 border bg-card",
                  "ring-1 ring-black/[0.04] dark:ring-white/[0.06]"
                )}
              >
                <div
                  className={cn(
                    "pointer-events-none absolute inset-0 opacity-90 bg-gradient-to-br",
                    c.accent
                  )}
                />
                <div className="relative flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{c.title}</p>
                    <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight">{c.value}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      Avg score (non-suppressed): {summary.avg_priority_score ?? "—"}
                    </p>
                  </div>
                  <div className="rounded-lg bg-background/80 p-2 shadow-sm border border-border/60">
                    <c.icon className="h-5 w-5 text-primary" />
                  </div>
                </div>
              </PremiumCard>
            </motion.div>
          ))}
        </div>
      ) : null}

      {dm && (dm.ranking_mode || dm.top_k != null) ? (
        <PremiumCard className="p-4">
          <h3 className="text-sm font-semibold tracking-tight mb-3">Diversity metrics</h3>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-xs">
            <div>
              <dt className="text-muted-foreground">Mode</dt>
              <dd className="font-medium mt-0.5">{String(dm.ranking_mode ?? "—")}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">HR concentration (max share)</dt>
              <dd className="font-mono mt-0.5">{Number(dm.hr_concentration_max_share ?? 0).toFixed(3)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Student concentration (max share)</dt>
              <dd className="font-mono mt-0.5">{Number(dm.student_concentration_max_share ?? 0).toFixed(3)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Exploration share</dt>
              <dd className="font-mono mt-0.5">{Number(dm.exploration_share ?? 0).toFixed(3)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Students starved (nonsup top‑K vs pool)</dt>
              <dd className="font-mono mt-0.5">{String(dm.students_starved_in_top_k_nonsup ?? "—")}</dd>
            </div>
            {diversifiedRanking ? (
              <div>
                <dt className="text-muted-foreground">Δ HR concentration vs standard</dt>
                <dd className="font-mono mt-0.5">{Number(dm.hr_concentration_delta_vs_standard ?? 0).toFixed(4)}</dd>
              </div>
            ) : null}
            {diversifiedRanking ? (
              <div>
                <dt className="text-muted-foreground">Students gained vs standard top‑K</dt>
                <dd className="font-mono mt-0.5">{String(dm.students_gained_visibility_vs_standard_top_k ?? "—")}</dd>
              </div>
            ) : null}
            <div>
              <dt className="text-muted-foreground">Returned / requested</dt>
              <dd className="font-mono mt-0.5">
                {String(dm.returned_count ?? "—")} / {String(dm.requested_limit ?? "—")}
              </dd>
            </div>
          </dl>
        </PremiumCard>
      ) : null}

      <PremiumCard className="p-0 overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-border/80 px-4 py-3 bg-muted/30">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Gauge className="h-4 w-4" />
            <span>
              {pq.isFetching ? "Updating…" : `${summary?.total_candidates ?? 0} candidates`}
              {pq.data?.computed_at_utc ? ` · computed ${new Date(pq.data.computed_at_utc).toLocaleString()}` : ""}
            </span>
          </div>
          {pq.isFetching ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
        </div>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-14">Rank</TableHead>
                <TableHead>Student</TableHead>
                <TableHead>HR</TableHead>
                <TableHead className="text-right w-24">Priority</TableHead>
                <TableHead>Bucket</TableHead>
                <TableHead className="w-[100px]">Slot</TableHead>
                <TableHead className="min-w-[180px]">Action</TableHead>
                <TableHead className="min-w-[220px]">Why ranked</TableHead>
                <TableHead className="min-w-[140px]">Cooldown</TableHead>
                <TableHead>Next touch</TableHead>
                <TableHead className="w-28 text-right">Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && !pq.isLoading ? (
                <TableRow>
                  <TableCell colSpan={11} className="py-16 text-center text-muted-foreground">
                    No rows match filters — widen bucket or raise limit.
                  </TableCell>
                </TableRow>
              ) : null}
              {pq.isLoading ? (
                <TableRow>
                  <TableCell colSpan={11} className="py-12 text-center text-muted-foreground">
                    <Loader2 className="inline h-5 w-5 animate-spin mr-2 align-middle" />
                    Loading queue…
                  </TableCell>
                </TableRow>
              ) : null}
              {rows.map((r) => {
                const hot = r.priority_rank <= 3 && r.queue_bucket !== "SUPPRESS";
                const mv = movementHint(r, prevMap);
                return (
                  <TableRow
                    key={rowPairKey(r)}
                    className={cn(hot && "bg-primary/[0.04]", "group")}
                  >
                    <TableCell className="font-mono text-sm">
                      <div className="flex flex-col gap-0.5">
                        <span className="font-semibold">{r.priority_rank}</span>
                        {mv ? (
                          <span
                            className={cn(
                              "text-[10px] font-medium inline-flex items-center gap-0.5",
                              mv.tone === "up" && "text-emerald-600 dark:text-emerald-400",
                              mv.tone === "down" && "text-rose-600 dark:text-rose-400",
                              mv.tone === "chg" && "text-sky-600 dark:text-sky-400"
                            )}
                          >
                            {mv.tone === "up" ? <ArrowUp className="h-3 w-3" /> : null}
                            {mv.tone === "down" ? <ArrowDown className="h-3 w-3" /> : null}
                            {mv.tone === "chg" ? <Minus className="h-3 w-3 rotate-90" /> : null}
                            {mv.label}
                          </span>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="font-medium leading-tight">{r.student.name}</div>
                      <div className="text-[11px] text-muted-foreground truncate max-w-[200px]">
                        {r.student.gmail_address}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="font-medium leading-tight">{r.hr.company}</div>
                      <div className="text-[11px] text-muted-foreground truncate max-w-[220px]">{r.hr.email}</div>
                      <div className="mt-1 flex gap-1 flex-wrap">
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-5">
                          {r.hr_tier}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell className="text-right tabular-nums font-semibold">{r.priority_score.toFixed(1)}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={cn("text-[10px]", bucketBadgeClass(r.queue_bucket))}>
                        {r.queue_bucket.replace(/_/g, " ")}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs">
                      {r.ranking_slot_type === "EXPLORATION" ? (
                        <Badge className="bg-indigo-600/90 text-white text-[10px]">EXPLORATION</Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm leading-snug">{r.recommended_action}</TableCell>
                    <TableCell className="text-xs text-muted-foreground leading-relaxed">
                      {(r.recommendation_reason || []).slice(0, 4).join(" · ")}
                      {(r.recommendation_reason || []).length > 4 ? "…" : ""}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground max-w-[200px]">
                      {r.cooldown_status || "—"}
                    </TableCell>
                    <TableCell className="text-xs font-mono text-muted-foreground whitespace-nowrap">
                      {r.next_best_touch
                        ? new Date(r.next_best_touch).toLocaleString(undefined, {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" className="h-8" onClick={() => setDetail(r)}>
                        Why ranked
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </PremiumCard>

      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Why this rank?</DialogTitle>
            <DialogDescription>
              Explainable multi-factor score (read-only). Urgency:{" "}
              <Badge variant={urgencyBadge(detail?.urgency_level || "")}>{detail?.urgency_level}</Badge>
            </DialogDescription>
          </DialogHeader>
          {detail ? (
            <div className="space-y-4 text-sm">
              <div className="rounded-lg border bg-muted/40 p-3 space-y-1">
                <div className="font-medium">
                  {detail.student.name} → {detail.hr.company}
                </div>
                <div className="text-xs text-muted-foreground break-all">{detail.hr.email}</div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge>Score {detail.priority_score.toFixed(1)}</Badge>
                <Badge variant="outline">#{detail.priority_rank}</Badge>
                <Badge variant="outline">{detail.queue_bucket}</Badge>
                <Badge variant="outline">HR {detail.hr_tier}</Badge>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Dimensions</p>
                <ul className="space-y-1 text-xs font-mono">
                  {Object.entries(detail.dimension_scores || {}).map(([k, v]) => (
                    <li key={k} className="flex justify-between gap-4 border-b border-border/50 py-1">
                      <span className="text-muted-foreground">{k}</span>
                      <span>{v.toFixed(1)}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Reasons</p>
                <ul className="list-disc pl-4 space-y-1 text-sm leading-relaxed">
                  {detail.recommendation_reason.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </div>
              <div className="text-xs text-muted-foreground space-y-1">
                {detail.diversity_note ? (
                  <div className="rounded-md border border-indigo-500/30 bg-indigo-500/10 px-2 py-1.5 text-indigo-950 dark:text-indigo-100">
                    {detail.diversity_note}
                  </div>
                ) : null}
                <div>
                  <span className="font-medium text-foreground">HR health / opp:</span> {detail.health_score.toFixed(1)}{" "}
                  / {detail.opportunity_score.toFixed(1)}
                </div>
                <div>
                  <span className="font-medium text-foreground">Follow-up engine:</span> {detail.followup_status || "—"}
                </div>
                <div>
                  <span className="font-medium text-foreground">Signal fingerprint:</span> {detail.signal_fingerprint}
                </div>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </PageLayout>
  );
}
