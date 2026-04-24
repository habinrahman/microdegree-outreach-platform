import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Download, Inbox, Mail, MailX, Send } from "lucide-react";

import { PageLayout } from "@/components/PageLayout";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { FilterBar, FilterField } from "@/components/FilterBar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TABLE_PAGE_SIZE } from "@/lib/constants";
import { ListPagination } from "@/components/ListPagination";
import { EmptyState } from "@/components/EmptyState";
import { safeGet } from "@/api/api";
import { StatusBadge } from "@/components/StatusBadge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

type LogRow = Record<string, unknown> & {
  id?: string;
  student_name?: string;
  company?: string;
  hr_email?: string;
  email_type?: string;
  status?: string;
  sent_time?: string;
  sent_at?: string;
  error?: string | null;
};

function downloadLogsCsv(rows: LogRow[]) {
  const headers = ["student_name", "company", "hr_email", "email_type", "status", "sent_time", "error"];
  const esc = (v: unknown) => {
    const s = String(v ?? "");
    if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const lines = [headers.join(",")];
  for (const r of rows) {
    lines.push(
      [
        r.student_name,
        r.company,
        r.hr_email,
        r.email_type,
        r.status,
        r.sent_time ?? r.sent_at,
        r.error,
      ]
        .map(esc)
        .join(",")
    );
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `email-logs-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export default function EmailLogs() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState("");
  const page = Math.max(1, parseInt(searchParams.get("page") || "1", 10) || 1);
  const skip = (page - 1) * TABLE_PAGE_SIZE;

  useEffect(() => {
    if (!q.trim()) return;
    setSearchParams((prev) => {
      if ((prev.get("page") || "1") === "1") return prev;
      const next = new URLSearchParams(prev);
      next.delete("page");
      return next;
    });
  }, [q, setSearchParams]);

  const logsQ = useQuery({
    queryKey: ["email-logs", page],
    queryFn: () =>
      safeGet<LogRow[]>("/email-logs", {
        limit: TABLE_PAGE_SIZE,
        skip,
      }),
    refetchInterval: 60_000,
    refetchIntervalInBackground: true,
  });

  const rawLogs = (logsQ.data || []) as LogRow[];

  const rows = useMemo(() => {
    const all = rawLogs;
    const s = q.trim().toLowerCase();
    if (!s) return all;
    return all.filter((r) =>
      [r.student_name, r.company, r.hr_email, r.status, r.email_type, r.error].some((v) =>
        String(v ?? "")
          .toLowerCase()
          .includes(s)
      )
    );
  }, [rawLogs, q]);

  const deliveryStats = useMemo(() => {
    let sent = 0;
    let failed = 0;
    let other = 0;
    for (const r of rows) {
      const st = String(r.status ?? "").toLowerCase();
      if (st === "sent" || st === "delivered") sent += 1;
      else if (st === "failed" || st === "error") failed += 1;
      else other += 1;
    }
    const total = rows.length || 1;
    return { sent, failed, other, total };
  }, [rows]);

  const hasNextPage = logsQ.isSuccess && rawLogs.length === TABLE_PAGE_SIZE;

  const setPage = (next: number) => {
    setSearchParams((prev) => {
      const n = new URLSearchParams(prev);
      if (next <= 1) n.delete("page");
      else n.set("page", String(next));
      return n;
    });
  };

  const columns: ColumnDef<LogRow>[] = [
    { id: "student", header: "Student", cell: (r) => String(r.student_name ?? "—") },
    { id: "company", header: "Company", cell: (r) => String(r.company ?? "—") },
    { id: "hr", header: "HR email", cell: (r) => String(r.hr_email ?? "—") },
    {
      id: "type",
      header: "Type",
      cell: (r) => <StatusBadge raw={String(r.email_type)}>{String(r.email_type ?? "—")}</StatusBadge>,
    },
    {
      id: "status",
      header: "Status",
      cell: (r) => <StatusBadge raw={String(r.status)}>{String(r.status ?? "—")}</StatusBadge>,
    },
    {
      id: "time",
      header: "Time",
      cell: (r) => (
        <span className="tabular-nums text-sm text-muted-foreground">
          {String(r.sent_time ?? r.sent_at ?? "—")}
        </span>
      ),
    },
    {
      id: "err",
      header: "Error",
      cell: (r) => (
        <span className="line-clamp-2 max-w-[200px] text-xs text-destructive">{r.error ? String(r.error) : "—"}</span>
      ),
    },
  ];

  return (
    <PageLayout
      title="Email logs"
      subtitle="GET /email-logs · delivery mix · CSV export · auto-refresh ~60s (newest-first cap per request)"
      actions={
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="gap-1.5"
          disabled={!rows.length || logsQ.isError}
          onClick={() => downloadLogsCsv(rows)}
        >
          <Download className="h-4 w-4" />
          Export CSV
        </Button>
      }
    >
      {logsQ.isError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Backend error — check server logs</AlertTitle>
          <AlertDescription>GET /email-logs failed.</AlertDescription>
        </Alert>
      ) : null}

      <div className="mb-6 grid gap-4 lg:grid-cols-3">
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
          <PremiumCard className="p-4">
            <div className="flex items-center justify-between">
              <p className="text-lg font-semibold">Delivery pulse</p>
              <Send className="h-5 w-5 text-[#22C55E]" />
            </div>
            <p className="mt-3 text-sm text-gray-500 dark:text-muted-foreground">Filtered rows: {rows.length}</p>
            <div className="mt-4 h-3 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-[#22C55E] transition-all duration-500"
                style={{ width: `${(deliveryStats.sent / deliveryStats.total) * 100}%` }}
              />
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Green ≈ sent/delivered ratio in the current filter.
            </p>
          </PremiumCard>
        </motion.div>
        <PremiumCard className="flex flex-col justify-center p-4">
          <div className="flex items-center gap-3">
            <Mail className="h-8 w-8 text-[#3B82F6]" />
            <div>
              <p className="text-3xl font-bold tabular-nums text-[#22C55E]">{deliveryStats.sent}</p>
              <p className="text-sm text-gray-500 dark:text-muted-foreground">Sent / delivered</p>
            </div>
          </div>
        </PremiumCard>
        <PremiumCard className="flex flex-col justify-center p-4">
          <div className="flex items-center gap-3">
            <MailX className="h-8 w-8 text-[#EF4444]" />
            <div>
              <p className="text-3xl font-bold tabular-nums text-[#EF4444]">{deliveryStats.failed}</p>
              <p className="text-sm text-gray-500 dark:text-muted-foreground">Undelivered (invalid/bounced or error)</p>
            </div>
          </div>
        </PremiumCard>
      </div>

      <FilterBar>
        <FilterField label="Search">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter rows…" />
        </FilterField>
      </FilterBar>

      {logsQ.isLoading ? null : (
        <p className="mb-2 text-xs text-muted-foreground">
          Page {page}: showing {rows.length.toLocaleString()} row{rows.length === 1 ? "" : "s"} after search (
          {rawLogs.length.toLocaleString()} loaded this request).
          {q.trim() ? " Search applies to this page only." : null}
          {hasNextPage ? (
            <span className="ml-1 font-medium text-amber-700 dark:text-amber-400">
              Older entries may be on the next page.
            </span>
          ) : null}
        </p>
      )}

      <DataTable<LogRow>
        columns={columns}
        data={logsQ.isError ? [] : rows}
        getRowKey={(r, i) => String(r.id ?? i)}
        loading={logsQ.isLoading}
        emptyMessage={logsQ.isError ? "Request failed." : "No logs."}
        emptyState={
          logsQ.isError || logsQ.isLoading ? undefined : (
            <EmptyState
              icon={Inbox}
              title="No log rows here"
              description="This page is empty for the current search. Try another page or clear the search box."
            >
              <Button type="button" variant="outline" size="sm" onClick={() => setQ("")}>
                Clear search
              </Button>
              <Button type="button" variant="default" size="sm" asChild>
                <Link to="/campaigns">Open Campaigns</Link>
              </Button>
            </EmptyState>
          )
        }
      />

      {logsQ.isLoading ? null : (
        <div className="mt-3">
          <ListPagination
            page={page}
            totalPages={!hasNextPage ? page : undefined}
            hasNext={hasNextPage}
            hasPrev={page > 1}
            pageSize={TABLE_PAGE_SIZE}
            onPageChange={setPage}
          />
        </div>
      )}
    </PageLayout>
  );
}
