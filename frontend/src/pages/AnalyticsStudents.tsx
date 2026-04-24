import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PageLayout } from "@/components/PageLayout";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { KpiCard } from "@/components/KpiCard";
import { SimpleBarChart } from "@/components/charts/SimpleBarChart";
import { Button } from "@/components/ui/button";
import { GraduationCap, Send, MessageSquare } from "lucide-react";
import { API_LIST_LIMITS } from "@/lib/constants";
import { getAnalyticsStudents } from "@/api/analytics";

type Row = {
  student_id: string;
  student_name: string;
  assigned_hrs: number;
  campaigns_total: number;
  campaigns_sent: number;
  responses: number;
  reply_rate: number;
};

export default function AnalyticsStudents() {
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: ["analytics", "students"],
    queryFn: () => getAnalyticsStudents({ limit: API_LIST_LIMITS.analyticsRows }) as Promise<Row[]>,
  });
  const rows = (q.data ?? []) as Row[];
  const analyticsLimit = API_LIST_LIMITS.analyticsRows;
  const atAnalyticsCap = q.isSuccess && rows.length >= analyticsLimit;

  const stats = useMemo(() => {
    if (!rows.length) return { students: 0, sent: 0, replies: 0, avgRR: 0 };
    const sent = rows.reduce((a, r) => a + (r.campaigns_sent ?? 0), 0);
    const replies = rows.reduce((a, r) => a + (r.responses ?? 0), 0);
    const avgRR = rows.reduce((a, r) => a + (r.reply_rate ?? 0), 0) / rows.length;
    return { students: rows.length, sent, replies, avgRR };
  }, [rows]);

  const chartData = useMemo(() => {
    return [...rows]
      .sort((a, b) => (b.campaigns_sent ?? 0) - (a.campaigns_sent ?? 0))
      .slice(0, 8)
      .map((r) => ({
        name: r.student_name.length > 14 ? `${r.student_name.slice(0, 14)}…` : r.student_name,
        volume: r.campaigns_sent ?? 0,
        student_id: r.student_id,
      })) as Record<string, unknown>[];
  }, [rows]);

  const columns: ColumnDef<Row>[] = [
    { id: "name", header: "Student", cell: (r) => r.student_name },
    { id: "hrs", header: "Assigned HRs", cell: (r) => r.assigned_hrs },
    { id: "tot", header: "Campaigns", cell: (r) => r.campaigns_total },
    { id: "sent", header: "Sent", cell: (r) => r.campaigns_sent },
    { id: "resp", header: "Replies", cell: (r) => r.responses },
    {
      id: "rr",
      header: "Reply rate %",
      cell: (r) => <span className="tabular-nums">{r.reply_rate}%</span>,
    },
  ];

  return (
    <PageLayout
      title="Analytics — Students"
      subtitle="GET /analytics/students — counts and reply rate (per student)"
      actions={
        <Button type="button" variant="outline" size="sm" onClick={() => q.refetch()}>
          Refresh
        </Button>
      }
    >
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <KpiCard title="Students in view" value={stats.students} icon={GraduationCap} tone="analytics" />
        <KpiCard title="Campaigns sent (sum)" value={stats.sent} icon={Send} tone="analytics" />
        <KpiCard
          title="Avg reply rate %"
          value={q.isLoading ? "…" : `${stats.avgRR.toFixed(1)}%`}
          icon={MessageSquare}
          tone="analytics"
        />
      </div>

      {q.isLoading ? null : (
        <p className="mb-2 text-xs text-muted-foreground">
          Showing {rows.length.toLocaleString()} student{rows.length === 1 ? "" : "s"} (API limit{" "}
          {analyticsLimit.toLocaleString()}).
          {atAnalyticsCap ? (
            <span className="ml-1 font-medium text-amber-700 dark:text-amber-400">
              Results may be truncated at the limit.
            </span>
          ) : null}
        </p>
      )}

      <div className="mb-6">
        <SimpleBarChart
          title="Top students by sends"
          description="Campaign volume — proxy for outreach intensity · click a bar to open Campaigns"
          data={chartData}
          dataKey="volume"
          nameKey="name"
          loading={q.isLoading}
          color="#4F46E5"
          onBarClick={(row) => {
            const id = String(row.student_id ?? "").trim();
            if (id) navigate(`/campaigns?student_id=${encodeURIComponent(id)}`);
          }}
        />
      </div>

      <DataTable<Row>
        columns={columns}
        data={rows}
        getRowKey={(r) => r.student_id}
        getRowProps={(r) => ({
          className: "cursor-pointer",
          title: "Open Campaigns filtered to this student",
          onClick: () =>
            navigate(`/campaigns?student_id=${encodeURIComponent(r.student_id)}`),
        })}
        loading={q.isLoading}
        emptyMessage={q.isError ? "Failed to load." : "No data."}
      />
    </PageLayout>
  );
}
