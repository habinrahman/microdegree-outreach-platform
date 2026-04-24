import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PageLayout } from "@/components/PageLayout";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { KpiCard } from "@/components/KpiCard";
import { SimpleBarChart } from "@/components/charts/SimpleBarChart";
import { Button } from "@/components/ui/button";
import { Users, Send, MessageSquare } from "lucide-react";
import { API_LIST_LIMITS } from "@/lib/constants";
import { getAnalyticsHrs } from "@/api/analytics";

type Row = {
  hr_id: string;
  hr_name: string;
  email: string;
  company: string;
  status: string;
  campaigns_total: number;
  campaigns_sent: number;
  responses: number;
  reply_rate: number;
};

export default function AnalyticsHRs() {
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: ["analytics", "hrs"],
    queryFn: () => getAnalyticsHrs({ limit: API_LIST_LIMITS.analyticsRows }) as Promise<Row[]>,
  });
  const rows = (q.data ?? []) as Row[];
  const analyticsLimit = API_LIST_LIMITS.analyticsRows;
  const atAnalyticsCap = q.isSuccess && rows.length >= analyticsLimit;

  const stats = useMemo(() => {
    if (!rows.length) return { hrs: 0, sent: 0, replies: 0, avgRR: 0 };
    const sent = rows.reduce((a, r) => a + (r.campaigns_sent ?? 0), 0);
    const replies = rows.reduce((a, r) => a + (r.responses ?? 0), 0);
    const avgRR = rows.reduce((a, r) => a + (r.reply_rate ?? 0), 0) / rows.length;
    return { hrs: rows.length, sent, replies, avgRR };
  }, [rows]);

  const chartData = useMemo(() => {
    return [...rows]
      .sort((a, b) => (b.responses ?? 0) - (a.responses ?? 0))
      .slice(0, 8)
      .map((r) => {
        const label = String(r.company || r.hr_name || r.email || "—");
        return {
          name: label.length > 12 ? `${label.slice(0, 12)}…` : label,
          engagement: r.responses ?? 0,
          hr_id: r.hr_id,
        };
      }) as Record<string, unknown>[];
  }, [rows]);

  const columns: ColumnDef<Row>[] = [
    { id: "co", header: "Company", cell: (r) => r.company },
    { id: "nm", header: "HR", cell: (r) => r.hr_name },
    { id: "em", header: "Email", cell: (r) => r.email },
    { id: "st", header: "Status", cell: (r) => r.status },
    { id: "tot", header: "Campaigns", cell: (r) => r.campaigns_total },
    { id: "sent", header: "Sent", cell: (r) => r.campaigns_sent },
    { id: "rep", header: "Replies", cell: (r) => r.responses },
    {
      id: "rr",
      header: "Reply rate %",
      cell: (r) => <span className="tabular-nums">{r.reply_rate}%</span>,
    },
  ];

  return (
    <PageLayout
      title="Analytics — HRs"
      subtitle="GET /analytics/hrs — performance by HR contact (reply rate)"
      actions={
        <Button type="button" variant="outline" size="sm" onClick={() => q.refetch()}>
          Refresh
        </Button>
      }
    >
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <KpiCard title="HRs in view" value={stats.hrs} icon={Users} tone="analytics" />
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
          Showing {rows.length.toLocaleString()} HR contact{rows.length === 1 ? "" : "s"} (API limit{" "}
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
          title="Top HRs by responses (bar chart)"
          description="Sorted by captured responses — click a bar to open Campaigns for that HR"
          data={chartData}
          dataKey="engagement"
          nameKey="name"
          loading={q.isLoading}
          color="#3B82F6"
          onBarClick={(row) => {
            const id = String(row.hr_id ?? "").trim();
            if (id) navigate(`/campaigns?hr_id=${encodeURIComponent(id)}`);
          }}
        />
      </div>

      <DataTable<Row>
        columns={columns}
        data={rows}
        getRowKey={(r) => r.hr_id}
        getRowProps={(r) => ({
          className: "cursor-pointer",
          title: "Open Campaigns filtered to this HR",
          onClick: () => navigate(`/campaigns?hr_id=${encodeURIComponent(r.hr_id)}`),
        })}
        loading={q.isLoading}
        emptyMessage={q.isError ? "Failed to load." : "No data."}
      />
    </PageLayout>
  );
}
