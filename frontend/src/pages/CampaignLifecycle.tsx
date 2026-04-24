import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { GitBranch, Loader2, Shield, Table2 } from "lucide-react";
import { PageLayout } from "@/components/PageLayout";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { LifecycleMermaid } from "@/components/LifecycleMermaid";
import { formatApiFailureLabel } from "@/api/api";
import { fetchCampaignLifecycle } from "@/api/campaignLifecycle";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";

function countBar(count: number, max: number) {
  if (max <= 0) return 0;
  return Math.min(100, Math.round((count / max) * 100));
}

export default function CampaignLifecycle() {
  const q = useQuery({
    queryKey: ["campaigns", "lifecycle"],
    queryFn: fetchCampaignLifecycle,
  });

  const data = q.data;
  const maxCount = Math.max(0, ...(data?.status_counts.map((s) => s.count) ?? []));

  return (
    <PageLayout
      title="Campaign lifecycle"
      subtitle="Read-only view of EmailCampaign.status FSM: allowed transitions, terminal states, and live row counts. No sends or mutations."
      actions={
        <Button variant="outline" size="sm" asChild>
          <Link to={ROUTES.decisionDiagnostics}>Decision diagnostics</Link>
        </Button>
      }
    >
      {q.isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground p-8">
          <Loader2 className="w-5 h-5 animate-spin" />
          Loading lifecycle snapshot…
        </div>
      ) : q.isError ? (
        <PremiumCard className="p-6 space-y-3 border border-destructive/30">
          <p className="text-sm font-medium text-destructive">Unable to load campaign lifecycle</p>
          <p className="text-xs text-muted-foreground">{formatApiFailureLabel(q.error)}</p>
          <Button variant="outline" size="sm" type="button" onClick={() => q.refetch()} disabled={q.isFetching}>
            Retry
          </Button>
        </PremiumCard>
      ) : data ? (
        <div className="space-y-6">
          <PremiumCard className="p-4 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <GitBranch className="w-4 h-4 shrink-0 text-sky-500" />
            <span>
              Snapshot UTC: <span className="font-mono text-foreground">{data.computed_at_utc}</span>
              {" · "}
              Total <code className="text-xs bg-muted px-1 rounded">email_campaigns</code> rows:{" "}
              <span className="font-semibold text-foreground">{data.total_campaign_rows}</span>
            </span>
          </PremiumCard>

          <div className="grid gap-6 lg:grid-cols-2">
            <PremiumCard className="p-4 space-y-3">
              <div className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-rose-500" />
                <h2 className="text-sm font-semibold">Terminal states</h2>
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Rows in these statuses do not leave the terminal set via normal ORM transitions (see model in
                backend <code className="text-[10px]">campaign_lifecycle</code>).
              </p>
              <div className="flex flex-wrap gap-2">
                {data.terminal_statuses.map((s) => (
                  <Badge key={s} variant="destructive" className="font-mono text-xs">
                    {s}
                  </Badge>
                ))}
              </div>
              <Separator />
              <p className="text-xs font-medium text-muted-foreground">Statuses with idempotent self-loop</p>
              <div className="flex flex-wrap gap-1.5">
                {data.self_loop_statuses.map((s) => (
                  <Badge key={s} variant="secondary" className="font-mono text-[10px]">
                    {s}
                  </Badge>
                ))}
              </div>
            </PremiumCard>

            <PremiumCard className="p-4 space-y-3">
              <h2 className="text-sm font-semibold">Bulk SQL transitions</h2>
              <p className="text-xs text-muted-foreground leading-relaxed">
                These paths bypass row-level ORM guards but are documented in the lifecycle service.
              </p>
              <ul className="text-xs space-y-2 list-disc pl-4 text-muted-foreground">
                {data.bulk_transitions.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </PremiumCard>
          </div>

          <PremiumCard className="p-4 space-y-4">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <h2 className="text-sm font-semibold flex items-center gap-2">
                <Table2 className="w-4 h-4" />
                Rows per status
              </h2>
            </div>
            <div className="space-y-3">
              {data.status_counts.map((row) => (
                <div key={row.status} className="space-y-1">
                  <div className="flex justify-between text-xs gap-2">
                    <span className="font-mono flex items-center gap-2">
                      {row.status}
                      {row.is_terminal ? (
                        <Badge variant="outline" className="text-[9px] h-4 px-1 border-rose-500/40">
                          terminal
                        </Badge>
                      ) : null}
                    </span>
                    <span className="tabular-nums text-muted-foreground">{row.count}</span>
                  </div>
                  <div className="h-2 rounded-full bg-muted overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all",
                        row.is_terminal ? "bg-rose-600/70" : "bg-sky-600/70"
                      )}
                      style={{ width: `${countBar(row.count, maxCount)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
            {data.unknown_status_counts.length > 0 ? (
              <div className="pt-2 border-t border-border/60">
                <p className="text-xs font-medium text-amber-700 dark:text-amber-300 mb-2">
                  Unknown / non-canonical status values in DB
                </p>
                <ul className="text-xs font-mono space-y-1">
                  {data.unknown_status_counts.map((u) => (
                    <li key={u.status}>
                      {u.status}: {u.count}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </PremiumCard>

          <PremiumCard className="p-4 space-y-3">
            <h2 className="text-sm font-semibold">Allowed transitions (ORM)</h2>
            <div className="rounded-lg border border-border/80 overflow-hidden max-h-[320px] overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[40%]">From</TableHead>
                    <TableHead>To</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.edges.map((e) => (
                    <TableRow key={`${e.source}->${e.target}`}>
                      <TableCell className="font-mono text-xs">{e.source}</TableCell>
                      <TableCell className="font-mono text-xs">{e.target}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </PremiumCard>

          <PremiumCard className="p-4 space-y-3">
            <h2 className="text-sm font-semibold">Lifecycle graph (Mermaid)</h2>
            <p className="text-xs text-muted-foreground">
              Interactive diagram below. Raw source is also available in the API field{" "}
              <code className="text-[10px]">mermaid_state_diagram</code> for export.
            </p>
            <LifecycleMermaid chart={data.mermaid_state_diagram} />
          </PremiumCard>
        </div>
      ) : null}
    </PageLayout>
  );
}
