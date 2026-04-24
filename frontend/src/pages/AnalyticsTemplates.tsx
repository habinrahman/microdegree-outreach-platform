import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PageLayout } from "@/components/PageLayout";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { KpiCard } from "@/components/KpiCard";
import { SimpleBarChart } from "@/components/charts/SimpleBarChart";
import { Button } from "@/components/ui/button";
import { LayoutTemplate, Send, MessageSquare } from "lucide-react";
import { API_LIST_LIMITS } from "@/lib/constants";
import { getAnalyticsTemplates } from "@/api/analytics";

type Row = {
  template_label: string;
  sent: number;
  replies: number;
  reply_rate: number;
};

export default function AnalyticsTemplates() {
  const navigate = useNavigate();
  const q = useQuery({
    queryKey: ["analytics", "templates"],
    queryFn: () => getAnalyticsTemplates({}) as Promise<Row[]>,
  });
  const rows = (q.data ?? []) as Row[];
  const analyticsLimit = API_LIST_LIMITS.analyticsRows;
  const atAnalyticsCap = q.isSuccess && rows.length >= analyticsLimit;

  const stats = useMemo(() => {
    if (!rows.length) return { labels: 0, sent: 0, replies: 0, avgRR: 0 };
    const sent = rows.reduce((a, r) => a + (r.sent ?? 0), 0);
    const replies = rows.reduce((a, r) => a + (r.replies ?? 0), 0);
    const avgRR = rows.reduce((a, r) => a + (r.reply_rate ?? 0), 0) / rows.length;
    return { labels: rows.length, sent, replies, avgRR };
  }, [rows]);

  const chartData = useMemo(() => {
    return [...rows]
      .sort((a, b) => (b.reply_rate ?? 0) - (a.reply_rate ?? 0))
      .map((r) => ({
        name: r.template_label.length > 16 ? `${r.template_label.slice(0, 16)}…` : r.template_label,
        rate: r.reply_rate ?? 0,
        template_label: r.template_label,
      })) as Record<string, unknown>[];
  }, [rows]);

  const columns: ColumnDef<Row>[] = [
    { id: "lbl", header: "Template", cell: (r) => r.template_label },
    { id: "sent", header: "Sent", cell: (r) => r.sent },
    { id: "rep", header: "Replies", cell: (r) => r.replies },
    {
      id: "rr",
      header: "Reply rate %",
      cell: (r) => <span className="tabular-nums">{r.reply_rate}%</span>,
    },
  ];

  return (
    <PageLayout
      title="Analytics — Templates"
      subtitle="GET /analytics/templates — template volume and reply rate"
      actions={
        <Button type="button" variant="outline" size="sm" onClick={() => q.refetch()}>
          Refresh
        </Button>
      }
    >
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <KpiCard title="Template labels" value={stats.labels} icon={LayoutTemplate} tone="analytics" />
        <KpiCard title="Total sent" value={stats.sent} icon={Send} tone="analytics" />
        <KpiCard
          title="Avg reply rate %"
          value={q.isLoading ? "…" : `${stats.avgRR.toFixed(1)}%`}
          icon={MessageSquare}
          tone="analytics"
        />
      </div>

      {q.isLoading ? null : (
        <p className="mb-2 text-xs text-muted-foreground">
          Showing {rows.length.toLocaleString()} template label{rows.length === 1 ? "" : "s"} (API limit{" "}
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
          title="Template reply rate leaderboard"
          description="A/B style read — click a bar to open Campaigns filtered by template label"
          data={chartData}
          dataKey="rate"
          nameKey="name"
          loading={q.isLoading}
          color="#22C55E"
          onBarClick={(row) => {
            const label = String(row.template_label ?? "").trim();
            if (label) navigate(`/campaigns?template_label=${encodeURIComponent(label)}`);
          }}
        />
      </div>

      <DataTable<Row>
        columns={columns}
        data={rows}
        getRowKey={(r) => r.template_label}
        getRowProps={(r) => ({
          className: "cursor-pointer",
          title: "Open Campaigns for this template label",
          onClick: () =>
            navigate(`/campaigns?template_label=${encodeURIComponent(r.template_label)}`),
        })}
        loading={q.isLoading}
        emptyMessage={q.isError ? "Failed to load." : "No data."}
      />
    </PageLayout>
  );
}
