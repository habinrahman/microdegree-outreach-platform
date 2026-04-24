import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { AlertCircle, Inbox } from "lucide-react";

import { StatusBadge, replyCategoryTone } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export type ActivityRow = {
  id: string;
  student_id?: string | null;
  hr_id?: string | null;
  student_name?: string | null;
  company?: string | null;
  hr_email?: string | null;
  email_type?: string | null;
  status?: string | null;
  reply_status?: string | null;
  delivery_status?: string | null;
  sent_at?: string | null;
  error?: string | null;
  subject?: string | null;
  body?: string | null;
  template_label?: string | null;
};

function activityRowClassName(r: ActivityRow) {
  const st = String(r.status ?? "").toLowerCase().trim();
  const rs = r.reply_status;
  const hasReply = rs != null && String(rs).trim() !== "";
  if (st === "failed") {
    return "bg-destructive/[0.06] hover:bg-destructive/10 transition-all duration-300 border-border/60";
  }
  if (st === "replied" || hasReply) {
    return "bg-sky-500/[0.06] hover:bg-sky-500/10 transition-all duration-300 border-border/60";
  }
  return "hover:bg-muted/50 transition-all duration-300 border-border/60";
}

function TableSkeleton() {
  return (
    <div className="space-y-2 p-2">
      {Array.from({ length: 8 }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full rounded-lg" />
      ))}
    </div>
  );
}

export function RecentCampaigns({
  rows,
  isLoading,
  isError,
  onRetry,
  onRowClick,
  formatTime,
}: {
  rows: ActivityRow[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  onRowClick: (row: ActivityRow) => void;
  formatTime: (t: unknown) => string;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="overflow-hidden rounded-xl border bg-card/50 shadow-sm transition-all duration-300 hover:shadow-md backdrop-blur-md"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-gradient-to-r from-slate-500/[0.05] to-transparent p-6">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Recent campaigns</h2>
          <p className="text-sm text-gray-500 dark:text-muted-foreground">
            Latest outreach rows · click a row for details · sorted by sent time
          </p>
        </div>
        <Button variant="ghost" size="sm" asChild className="transition-all duration-300">
          <Link to="/campaigns">Open full table</Link>
        </Button>
      </div>

      {isLoading ? (
        <TableSkeleton />
      ) : isError ? (
        <div className="m-6 rounded-xl border border-dashed border-destructive/30 bg-destructive/[0.04] px-6 py-12 text-center">
          <AlertCircle className="mx-auto h-8 w-8 text-destructive/80" />
          <p className="mt-3 text-sm font-medium text-foreground">Could not load campaigns</p>
          <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">Backend error — check logs</p>
          <Button className="mt-4" variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        </div>
      ) : rows.length === 0 ? (
        <div className="m-6 rounded-xl border border-dashed border-border/60 bg-muted/20 px-6 py-14 text-center">
          <Inbox className="mx-auto h-10 w-10 text-muted-foreground/70" />
          <p className="text-sm font-medium text-foreground">No campaigns to show</p>
          <p className="mt-2 max-w-md mx-auto text-sm text-gray-500 dark:text-muted-foreground">
            The activity feed is empty. Create assignments and queue sends, or open Campaigns for the full list.
          </p>
          <Button className="mt-6" variant="default" asChild>
            <Link to="/campaigns">Go to Campaigns</Link>
          </Button>
        </div>
      ) : (
        <div className="max-h-[min(70vh,640px)] overflow-x-auto overflow-y-auto">
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
              <TableRow className="border-border/60 hover:bg-transparent">
                <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Student
                </TableHead>
                <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Company
                </TableHead>
                <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  HR email
                </TableHead>
                <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Email type
                </TableHead>
                <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Status
                </TableHead>
                <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Reply status
                </TableHead>
                <TableHead className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Sent time
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r, i) => (
                <TableRow
                  key={r.id || i}
                  className={cn("cursor-pointer border-b", activityRowClassName(r))}
                  onClick={() => onRowClick(r)}
                  title="Campaign details"
                >
                  <TableCell className="font-medium">{r.student_name ?? "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{r.company ?? "—"}</TableCell>
                  <TableCell className="max-w-[200px] truncate font-mono text-xs text-muted-foreground">
                    {r.hr_email ?? "—"}
                  </TableCell>
                  <TableCell>
                    <StatusBadge raw={String(r.email_type ?? "")}>{String(r.email_type ?? "—")}</StatusBadge>
                  </TableCell>
                  <TableCell>
                    <StatusBadge raw={String(r.status ?? "")}>{String(r.status ?? "—")}</StatusBadge>
                  </TableCell>
                  <TableCell>
                    {r.reply_status ? (
                      <StatusBadge tone={replyCategoryTone(r.reply_status)} raw={String(r.reply_status)}>
                        {String(r.reply_status)}
                      </StatusBadge>
                    ) : (
                      <span className="text-xs text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <span className="tabular-nums text-sm text-muted-foreground">{formatTime(r.sent_at)}</span>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </motion.section>
  );
}
