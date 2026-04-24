import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { ClipboardList, ExternalLink, Loader2, ShieldAlert, Sparkles } from "lucide-react";
import { PageLayout } from "@/components/PageLayout";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Separator } from "@/components/ui/separator";
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
  rowPairKey,
  type DecisionDiagnostics as DD,
  type PriorityQueueRow,
} from "@/api/priorityQueue";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";

function bucketBadgeClass(b: string) {
  const u = b.toUpperCase();
  if (u === "SEND_NOW") return "bg-emerald-600/15 text-emerald-800 dark:text-emerald-300 border-emerald-500/30";
  if (u === "FOLLOW_UP_DUE") return "bg-violet-600/15 text-violet-900 dark:text-violet-200 border-violet-500/30";
  if (u === "WARM_LEAD_PRIORITY") return "bg-amber-500/15 text-amber-950 dark:text-amber-200 border-amber-500/30";
  if (u === "WAIT_FOR_COOLDOWN") return "bg-sky-600/15 text-sky-900 dark:text-sky-200 border-sky-500/25";
  if (u === "SUPPRESS") return "bg-rose-600/15 text-rose-950 dark:text-rose-200 border-rose-500/30";
  return "bg-muted text-muted-foreground border-border";
}

function DiagBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h4>
      <div className="text-sm rounded-lg border border-border/80 bg-muted/20 p-3 space-y-2">{children}</div>
    </div>
  );
}

function BulletList({ items }: { items: string[] }) {
  if (!items.length) return <p className="text-sm text-muted-foreground">None</p>;
  return (
    <ul className="list-disc pl-4 space-y-1 text-sm">
      {items.map((x) => (
        <li key={x}>{x}</li>
      ))}
    </ul>
  );
}

function FollowUpBlock({ fu }: { fu: DD["follow_up"] }) {
  return (
    <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-sm">
      <dt className="text-muted-foreground">Status</dt>
      <dd className="font-medium">{fu.status ?? "—"}</dd>
      <dt className="text-muted-foreground">Eligible</dt>
      <dd>{fu.eligible_for_followup ? "Yes" : "No"}</dd>
      <dt className="text-muted-foreground">Blocked reason</dt>
      <dd>{fu.blocked_reason ?? "—"}</dd>
      <dt className="text-muted-foreground">Next step / template</dt>
      <dd>
        {fu.next_followup_step ?? "—"} / {fu.next_template_type ?? "—"}
      </dd>
      <dt className="text-muted-foreground">Due (UTC) / days</dt>
      <dd>
        {fu.due_date_utc ?? "—"} {fu.days_until_due != null ? `(${fu.days_until_due}d)` : ""}
      </dd>
      <dt className="text-muted-foreground">Paused / in progress</dt>
      <dd>
        {fu.paused ? "Paused" : "No"} / {fu.send_in_progress ? "Yes" : "No"}
      </dd>
      <dt className="text-muted-foreground">Anchor campaign</dt>
      <dd className="break-all font-mono text-xs">{fu.initial_or_anchor_campaign_id ?? "—"}</dd>
    </dl>
  );
}

export default function DecisionDiagnostics() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [bucket, setBucket] = useState<string>("all");
  const [studentId, setStudentId] = useState<string>("all");
  const [limit, setLimit] = useState("200");
  const [onlySuppressed, setOnlySuppressed] = useState(false);
  const [detail, setDetail] = useState<PriorityQueueRow | null>(null);

  const pairParam = searchParams.get("pair") ?? "";

  const studentsQ = useQuery({
    queryKey: ["students", "decision-diagnostics"],
    queryFn: () => listStudents({ include_demo: false }) as Promise<{ id: string; name: string }[]>,
  });

  const pq = useQuery({
    queryKey: ["priority-queue", "diagnostics", bucket, studentId, limit],
    queryFn: () =>
      fetchPriorityQueue({
        bucket: bucket === "all" ? undefined : bucket,
        student_id: studentId === "all" ? undefined : studentId,
        limit: Math.min(500, Math.max(1, parseInt(limit, 10) || 200)),
        include_demo: false,
        diversified: false,
      }),
  });

  const rows = pq.data?.rows ?? [];
  const computedAt = pq.data?.computed_at_utc;

  const filteredRows = useMemo(() => {
    if (!onlySuppressed) return rows;
    return rows.filter((r) => r.queue_bucket === "SUPPRESS");
  }, [rows, onlySuppressed]);

  useEffect(() => {
    if (!pairParam || !rows.length) return;
    const hit = rows.find((r) => rowPairKey(r) === pairParam);
    if (hit) setDetail(hit);
  }, [pairParam, rows]);

  const openDetail = (r: PriorityQueueRow) => {
    setDetail(r);
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.set("pair", rowPairKey(r));
        return p;
      },
      { replace: true }
    );
  };

  const closeDetail = () => {
    setDetail(null);
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.delete("pair");
        return p;
      },
      { replace: true }
    );
  };

  const dd = detail?.decision_diagnostics;

  return (
    <PageLayout
      title="Decision diagnostics"
      subtitle="Read-only explainability for priority queue and follow-up signals — same engine as Priority queue, structured for operators."
      filters={
        <PremiumCard className="p-4">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1.5 min-w-[160px]">
              <Label className="text-xs text-muted-foreground">Bucket</Label>
              <Select value={bucket} onValueChange={setBucket}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All buckets</SelectItem>
                  <SelectItem value="SUPPRESS">Suppressed only (filter)</SelectItem>
                  <SelectItem value="SEND_NOW">Send now</SelectItem>
                  <SelectItem value="FOLLOW_UP_DUE">Follow-up due</SelectItem>
                  <SelectItem value="WARM_LEAD_PRIORITY">Warm leads</SelectItem>
                  <SelectItem value="WAIT_FOR_COOLDOWN">Cooldown</SelectItem>
                  <SelectItem value="LOW_PRIORITY">Low priority</SelectItem>
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
                  <SelectItem value="400">400</SelectItem>
                  <SelectItem value="500">500</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-2 pb-0.5">
              <Checkbox
                id="os"
                checked={onlySuppressed}
                onCheckedChange={(v) => setOnlySuppressed(v === true)}
              />
              <Label htmlFor="os" className="text-sm cursor-pointer">
                Only suppressed pairs
              </Label>
            </div>
            <Button variant="outline" size="sm" asChild className="mb-0.5">
              <Link to={ROUTES.priorityQueue}>
                <ExternalLink className="w-3.5 h-3.5 mr-1.5" />
                Priority queue
              </Link>
            </Button>
            <Button variant="outline" size="sm" asChild className="mb-0.5">
              <Link to={ROUTES.campaignLifecycle}>
                <ExternalLink className="w-3.5 h-3.5 mr-1.5" />
                Campaign lifecycle
              </Link>
            </Button>
          </div>
        </PremiumCard>
      }
    >
      <div className="space-y-4">
        <PremiumCard className="p-4 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          <Sparkles className="w-4 h-4 text-amber-500 shrink-0" />
          <span>
            Last decision run (UTC):{" "}
            <span className="font-mono text-foreground">{computedAt ?? "—"}</span>. Each row includes{" "}
            <code className="text-xs bg-muted px-1 rounded">decision_diagnostics</code> from the API — no
            separate write path.
          </span>
        </PremiumCard>

        {pq.isLoading ? (
          <div className="flex items-center gap-2 text-muted-foreground p-8">
            <Loader2 className="w-5 h-5 animate-spin" />
            Loading opportunities…
          </div>
        ) : pq.isError ? (
          <PremiumCard className="p-6 space-y-3 border border-destructive/30">
            <p className="text-sm font-medium text-destructive">Unable to load diagnostics</p>
            <p className="text-xs text-muted-foreground">{formatApiFailureLabel(pq.error)}</p>
            <Button variant="outline" size="sm" type="button" onClick={() => pq.refetch()} disabled={pq.isFetching}>
              Retry
            </Button>
          </PremiumCard>
        ) : (
          <PremiumCard className="overflow-hidden">
            <div className="p-3 border-b border-border/60 flex items-center gap-2 text-sm text-muted-foreground">
              <ClipboardList className="w-4 h-4" />
              Showing {filteredRows.length} of {rows.length} rows
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">#</TableHead>
                  <TableHead>Student → HR</TableHead>
                  <TableHead>Bucket</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                  <TableHead className="min-w-[200px]">Why ranked (summary)</TableHead>
                  <TableHead className="w-[120px]" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredRows.map((r) => {
                  const d = r.decision_diagnostics;
                  const summary = d?.why_ranked?.slice(0, 2).join(" · ") || r.recommended_action;
                  return (
                    <TableRow key={rowPairKey(r)} className="align-top">
                      <TableCell className="tabular-nums font-medium">{r.priority_rank}</TableCell>
                      <TableCell>
                        <div className="font-medium">{r.student.name}</div>
                        <div className="text-xs text-muted-foreground">
                          {r.hr.company} · {r.hr.email}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className={cn("text-xs", bucketBadgeClass(r.queue_bucket))}>
                          {r.queue_bucket}
                        </Badge>
                        {r.queue_bucket === "SUPPRESS" && (
                          <Badge variant="destructive" className="ml-1 text-[10px]">
                            No send
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{r.priority_score.toFixed(1)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground max-w-md">{summary}</TableCell>
                      <TableCell>
                        <Button size="sm" variant="secondary" onClick={() => openDetail(r)}>
                          Explain
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </PremiumCard>
        )}
      </div>

      <Sheet open={!!detail} onOpenChange={(o) => !o && closeDetail()}>
        <SheetContent className="w-full sm:max-w-lg overflow-y-auto">
          {detail && (
            <>
              <SheetHeader>
                <SheetTitle className="pr-8">Decision detail</SheetTitle>
                <SheetDescription>
                  {detail.student.name} → {detail.hr.name} ({detail.hr.company})
                </SheetDescription>
              </SheetHeader>

              <div className="mt-6 space-y-6">
                <div className="flex flex-wrap gap-2">
                  <Badge className={bucketBadgeClass(detail.queue_bucket)}>{detail.queue_bucket}</Badge>
                  <Badge variant="outline">Score {detail.priority_score.toFixed(1)}</Badge>
                  <Badge variant="outline">Tier {detail.hr_tier}</Badge>
                </div>

                <Button variant="link" className="h-auto p-0 text-sm" asChild>
                  <Link
                    to={`${ROUTES.campaigns}?student_id=${encodeURIComponent(detail.student.id)}&hr_id=${encodeURIComponent(detail.hr.id)}`}
                  >
                    Open campaigns for this pair
                  </Link>
                </Button>

                {dd && (
                  <>
                    <DiagBlock title="Last decision timestamp (UTC)">
                      <p className="font-mono text-sm">{dd.decision_computed_at_utc}</p>
                      <p className="text-xs text-muted-foreground">
                        Last pair activity (latest sent/scheduled/created touch):{" "}
                        <span className="font-mono text-foreground">{dd.last_pair_activity_utc ?? "—"}</span>
                      </p>
                    </DiagBlock>

                    <DiagBlock title="Bucket assignment">
                      <p className="text-sm leading-relaxed">{dd.bucket_rationale}</p>
                      <p className="text-xs text-muted-foreground mt-2">UI action: {dd.recommended_action}</p>
                    </DiagBlock>

                    <DiagBlock title="Why ranked (positive / neutral drivers)">
                      <BulletList items={dd.why_ranked} />
                    </DiagBlock>

                    {detail.queue_bucket === "SUPPRESS" && (
                      <DiagBlock title="Why suppressed">
                        <BulletList items={dd.why_suppressed} />
                      </DiagBlock>
                    )}

                    <DiagBlock title="Follow-up eligibility (engine snapshot)">
                      <FollowUpBlock fu={dd.follow_up} />
                    </DiagBlock>

                    <DiagBlock title="Cooldown reasons">
                      <p className="text-sm mb-2">{dd.cooldown.summary_line || "No active cooldown summary string."}</p>
                      <Separator className="my-2" />
                      <p className="text-xs text-muted-foreground mb-1">Penalty axis (0–100, subtracted as 0.35×)</p>
                      <BulletList items={dd.cooldown.penalty_reasons} />
                      <p className="text-xs mt-2 tabular-nums">
                        Cooldown penalty score: {dd.cooldown.cooldown_penalty_score}
                      </p>
                    </DiagBlock>

                    <DiagBlock title="Top scoring components (weighted axes)">
                      <p className="text-xs text-muted-foreground mb-2">{dd.scoring.formula}</p>
                      <ul className="text-sm space-y-1">
                        {dd.scoring.top_components.map((c) => (
                          <li key={c.name} className="flex justify-between gap-2">
                            <span className="text-muted-foreground">{c.name}</span>
                            <span className="font-mono tabular-nums">
                              {c.weighted.toFixed(2)}{" "}
                              <span className="text-muted-foreground text-xs">
                                (= {c.value.toFixed(1)} × {c.weight.toFixed(3)})
                              </span>
                            </span>
                          </li>
                        ))}
                      </ul>
                      <Separator className="my-2" />
                      <p className="text-xs text-muted-foreground">
                        Blended (pre-subtract): {dd.scoring.blended_before_cooldown_subtraction.toFixed(2)} ·
                        Cooldown term: −{dd.scoring.cooldown_subtracted.toFixed(2)} → Priority{" "}
                        {dd.scoring.priority_score.toFixed(2)}
                      </p>
                    </DiagBlock>

                    <DiagBlock title="Full signal lines (deduped)">
                      <BulletList items={detail.recommendation_reason} />
                    </DiagBlock>

                    {dd.why_not_sent && (
                      <DiagBlock title="Why not sent? (suppressed pair drilldown)">
                        <div className="flex items-start gap-2 text-amber-700 dark:text-amber-300">
                          <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
                          <p className="text-sm font-medium">{dd.why_not_sent.summary}</p>
                        </div>
                        <p className="text-xs text-muted-foreground mt-2">{dd.why_not_sent.operator_note}</p>
                        <Separator className="my-3" />
                        <p className="text-xs font-semibold text-muted-foreground mb-1">Blockers</p>
                        <BulletList items={dd.why_not_sent.blockers} />
                        <Separator className="my-3" />
                        <p className="text-xs font-semibold text-muted-foreground mb-1">Follow-up at decision time</p>
                        <FollowUpBlock fu={dd.why_not_sent.follow_up_snapshot} />
                        <Separator className="my-3" />
                        <p className="text-xs font-semibold text-muted-foreground mb-1">All signal lines</p>
                        <BulletList items={dd.why_not_sent.all_signal_lines} />
                      </DiagBlock>
                    )}

                    {dd.waiting_or_deferred && (
                      <DiagBlock title="Waiting / deferred (not suppressed)">
                        <p className="text-sm">{dd.waiting_or_deferred.summary}</p>
                        <BulletList items={dd.waiting_or_deferred.negative_signals} />
                      </DiagBlock>
                    )}
                  </>
                )}

                {!dd && (
                  <p className="text-sm text-muted-foreground">
                    No structured diagnostics on this row (older API). Refresh backend.
                  </p>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </PageLayout>
  );
}
