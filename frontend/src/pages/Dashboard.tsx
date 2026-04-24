import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Activity,
  AlertCircle,
  ArrowRight,
  Inbox,
  Mail,
  MessageSquareReply,
  Sparkles,
  TrendingUp,
  XCircle,
} from "lucide-react";

import { PageLayout } from "@/components/PageLayout";
import { ActivityLineChart, type ActivityLineDatum } from "@/components/dashboard/ActivityLineChart";
import { EmailBarChart } from "@/components/dashboard/EmailBarChart";
import { InsightsBanner } from "@/components/dashboard/InsightsBanner";
import { KpiCard, type KpiTone } from "@/components/KpiCard";
import { ReplyPieChart } from "@/components/dashboard/ReplyPieChart";
import type { ReplyPieDatum } from "@/components/dashboard/ReplyPieChart";
import {
  RecentCampaigns,
  type ActivityRow,
} from "@/components/dashboard/RecentCampaigns";
import { StatusBadge, replyCategoryTone } from "@/components/StatusBadge";
import { getAnalyticsSummary } from "@/api/analytics";
import { listCampaigns } from "@/api/campaigns";
import { getHealth, getSchedulerStatus } from "@/api/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { normalizeCampaignFields } from "@/lib/safeRender";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const REFRESH_MS = 10_000;
const NAV_DEBOUNCE_MS = 220;

type ChartRange = "7" | "30" | "all";

const safe = (v: unknown) => Number(v ?? 0);

function formatTime(t: unknown) {
  if (t == null || t === "") return "—";
  const d = new Date(String(t));
  return Number.isNaN(d.getTime()) ? String(t) : d.toLocaleString();
}

type AnalyticsSummary = Record<string, unknown>;

function mapCampaignToActivity(c: Record<string, unknown>): ActivityRow {
  const n = normalizeCampaignFields(c);
  const id = String(n.id ?? c.id ?? "");
  return {
    id,
    student_id: c.student_id != null ? String(c.student_id) : null,
    hr_id: c.hr_id != null ? String(c.hr_id) : null,
    student_name: (n.student_name ?? c.student_name) as string | null | undefined,
    company: (n.company ?? c.company) as string | null | undefined,
    hr_email: (n.hr_email ?? c.hr_email) as string | null | undefined,
    email_type: (n.email_type ?? c.email_type) as string | null | undefined,
    status: (n.status ?? c.status) as string | null | undefined,
    reply_status: (n.reply_status ?? c.reply_status ?? null) as string | null,
    delivery_status: (c.delivery_status ?? null) as string | null,
    sent_at: (n.sent_at ?? c.sent_at) as string | null | undefined,
    error: (c.error ?? null) as string | null,
    subject: (c.subject ?? null) as string | null,
    body: (c.body ?? null) as string | null,
    template_label: (c.template_label ?? null) as string | null,
  };
}

function filterActivityByRange(rows: ActivityRow[], range: ChartRange): ActivityRow[] {
  if (range === "all") return rows;
  const days = range === "7" ? 7 : 30;
  const cutoff = Date.now() - days * 86400000;
  return rows.filter((r) => {
    const t = r.sent_at ? new Date(String(r.sent_at)).getTime() : 0;
    if (!t || Number.isNaN(t)) return false;
    return t >= cutoff;
  });
}

function rangeLabel(range: ChartRange): string {
  if (range === "7") return "Last 7 days";
  if (range === "30") return "Last 30 days";
  return "All loaded";
}

function emailDomain(email: unknown): string | null {
  const s = String(email ?? "").trim().toLowerCase();
  const at = s.lastIndexOf("@");
  if (at <= 0 || at === s.length - 1) return null;
  return s.slice(at + 1);
}

function isReplyCategory(rsUpper: string): boolean {
  // Align with backend semantics: bounces/blocks are not replies.
  if (!rsUpper) return false;
  if (rsUpper === "BOUNCED" || rsUpper === "BLOCKED") return false;
  if (rsUpper === "INTERESTED" || rsUpper === "INTERVIEW" || rsUpper === "REPLIED") return true;
  if (rsUpper.includes("REJECT") || rsUpper === "NOT_INTERESTED") return true;
  return false;
}

function hasReplySignal(r: ActivityRow): boolean {
  const rsUpper = String(r.reply_status ?? "").trim().toUpperCase();
  if (isReplyCategory(rsUpper)) return true;
  return String(r.status ?? "").toLowerCase().trim() === "replied";
}

function replyStatusUpper(r: ActivityRow): string {
  return String(r.reply_status ?? "").trim().toUpperCase();
}

function buildReplyDistribution(rows: ActivityRow[]): ReplyPieDatum[] {
  let interested = 0;
  let interview = 0;
  let rejected = 0;
  let noResponse = 0;
  for (const r of rows) {
    const rs = String(r.reply_status ?? "").trim().toUpperCase();
    if (rs === "INTERESTED") interested += 1;
    else if (rs === "INTERVIEW") interview += 1;
    else if (rs.includes("REJECT") || rs === "NOT_INTERESTED") rejected += 1;
    else noResponse += 1;
  }
  return [
    { name: "Interested", value: interested },
    { name: "Interview", value: interview },
    { name: "Rejected", value: rejected },
    { name: "No Response", value: noResponse },
  ];
}

function buildSentOverTime(rows: ActivityRow[]): ActivityLineDatum[] {
  const map = new Map<string, number>();
  for (const r of rows) {
    if (String(r.status ?? "").toLowerCase() !== "sent") continue;
    const t = r.sent_at;
    if (!t) continue;
    const d = new Date(String(t));
    if (Number.isNaN(d.getTime())) continue;
    const key = d.toISOString().slice(0, 10);
    map.set(key, (map.get(key) ?? 0) + 1);
  }
  return [...map.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([date, sent]) => ({ date, sent }));
}

function topStudentFromRows(rows: ActivityRow[]) {
  const counts = new Map<string, number>();
  for (const r of rows) {
    const rs = String(r.reply_status ?? "").trim().toUpperCase();
    if (rs !== "INTERESTED" && rs !== "INTERVIEW" && rs !== "REPLIED") continue;
    const name = String(r.student_name ?? "").trim();
    if (!name) continue;
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  let best = "";
  let max = 0;
  for (const [k, v] of counts) {
    if (v > max) {
      max = v;
      best = k;
    }
  }
  return max > 0 ? { name: best, count: max } : null;
}

const DeliveryStack = memo(function DeliveryStack({
  segments,
  disabled,
  onNavigate,
}: {
  segments: {
    key: string;
    label: string;
    value: number;
    className: string;
    href: string;
  }[];
  disabled?: boolean;
  onNavigate: (search: string) => void;
}) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  const denom = total > 0 ? total : 1;

  return (
    <div className="space-y-4">
      <div className="flex h-5 w-full overflow-hidden rounded-full bg-muted/80 shadow-inner ring-1 ring-border/40">
        {segments.map((seg) => {
          const pct = total > 0 ? Math.max(0, (seg.value / denom) * 100) : 0;
          return (
            <motion.button
              key={seg.key}
              type="button"
              disabled={disabled || seg.value <= 0}
              title={`${seg.label}: ${seg.value.toLocaleString()}`}
              aria-label={`${seg.label}: ${seg.value}. Click to filter campaigns.`}
              onClick={() => onNavigate(seg.href)}
              initial={{ flexGrow: 0 }}
              animate={{ flexGrow: pct }}
              transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
              className={cn(
                "min-w-0 border-r border-background/20 last:border-r-0 transition-all duration-300",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                seg.className,
                disabled || seg.value <= 0 ? "cursor-not-allowed opacity-40" : "cursor-pointer hover:brightness-110"
              )}
              style={{ flexBasis: 0 }}
            />
          );
        })}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {segments.map((seg) => (
          <button
            key={`${seg.key}-row`}
            type="button"
            disabled={disabled || seg.value <= 0}
            onClick={() => onNavigate(seg.href)}
            className={cn(
              "rounded-xl border bg-card/40 p-4 text-left shadow-sm transition-all duration-300",
              "hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              disabled || seg.value <= 0 ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:bg-muted/30"
            )}
          >
            <div className="flex items-center gap-2">
              <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", seg.className)} />
              <span className="text-sm font-medium text-muted-foreground">{seg.label}</span>
            </div>
            <p className="mt-2 text-2xl font-bold tabular-nums">{seg.value.toLocaleString()}</p>
            <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">Click to filter in Campaigns</p>
          </button>
        ))}
      </div>
    </div>
  );
});

function MetricGridSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {Array.from({ length: 6 }).map((_, i) => (
        <Skeleton key={i} className="h-[160px] w-full rounded-xl" />
      ))}
    </div>
  );
}

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.07 },
  },
};

const item = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0 },
};

function MetricClickWrap({
  children,
  onActivate,
  ariaLabel,
  title,
}: {
  children: React.ReactNode;
  onActivate: () => void;
  ariaLabel: string;
  title?: string;
}) {
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onActivate();
    }
  };
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={ariaLabel}
      title={title}
      onClick={onActivate}
      onKeyDown={onKeyDown}
      className={cn(
        "h-full rounded-xl outline-none transition-all duration-300",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "cursor-pointer active:scale-[0.99]"
      )}
    >
      {children}
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const navTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [detailRow, setDetailRow] = useState<ActivityRow | null>(null);
  const [chartRange, setChartRange] = useState<ChartRange>("30");
  const [analyticsSlow, setAnalyticsSlow] = useState(false);

  const debouncedNavigate = useCallback(
    (to: string) => {
      if (navTimerRef.current) clearTimeout(navTimerRef.current);
      navTimerRef.current = setTimeout(() => {
        navTimerRef.current = null;
        navigate(to);
      }, NAV_DEBOUNCE_MS);
    },
    [navigate]
  );

  useEffect(
    () => () => {
      if (navTimerRef.current) clearTimeout(navTimerRef.current);
    },
    []
  );

  const summaryQ = useQuery({
    queryKey: ["analytics", "summary"],
    queryFn: async () => (await getAnalyticsSummary()) as AnalyticsSummary,
    placeholderData: keepPreviousData,
    refetchInterval: REFRESH_MS,
    refetchIntervalInBackground: true,
  });

  const campaignsQ = useQuery({
    queryKey: ["dashboard", "campaigns"],
    queryFn: () => listCampaigns({ limit: 1000, skip: 0 }),
    placeholderData: keepPreviousData,
    refetchInterval: REFRESH_MS,
    refetchIntervalInBackground: true,
  });

  const healthQ = useQuery({
    queryKey: ["health", "root"],
    queryFn: () => getHealth(),
    refetchInterval: REFRESH_MS,
    refetchIntervalInBackground: true,
  });

  const schedulerQ = useQuery({
    queryKey: ["scheduler", "status"],
    queryFn: () => getSchedulerStatus(),
    refetchInterval: REFRESH_MS,
    refetchIntervalInBackground: true,
  });

  useEffect(() => {
    if (!summaryQ.isFetching) {
      setAnalyticsSlow(false);
      return;
    }
    const t = window.setTimeout(() => setAnalyticsSlow(true), 10_000);
    return () => window.clearTimeout(t);
  }, [summaryQ.isFetching]);

  const summary = summaryQ.data;
  const activityRows = useMemo(() => {
    const raw = (campaignsQ.data || []) as Record<string, unknown>[];
    const rows = raw.map(mapCampaignToActivity);
    return [...rows].sort((a, b) => {
      const ta = a.sent_at ? new Date(String(a.sent_at)).getTime() : 0;
      const tb = b.sent_at ? new Date(String(b.sent_at)).getTime() : 0;
      return tb - ta;
    });
  }, [campaignsQ.data]);

  const filteredActivityRows = useMemo(
    () => filterActivityByRange(activityRows, chartRange),
    [activityRows, chartRange]
  );

  const emailsSent = safe(summary?.emails_sent);
  const emailsFailed = safe(summary?.emails_failed);
  const successRate = safe(summary?.success_rate);
  const totalReplies = safe(summary?.total_replies);
  const interestedReplies = safe(summary?.interested_replies);
  const bounceRate = safe(summary?.bounce_rate);

  // Prefer mutually-exclusive delivery buckets when available (prevents double counting).
  const deliverySent = safe(summary?.delivery_sent ?? summary?.total_sent ?? summary?.emails_sent);
  const deliveryFailed = safe(summary?.delivery_failed_other ?? summary?.delivery_failed ?? summary?.total_failed ?? summary?.emails_failed);
  const deliveryBlocked = safe(summary?.delivery_blocked ?? summary?.total_blocked ?? summary?.blocked_hr);
  const deliveryBounced = safe(summary?.delivery_bounced ?? summary?.total_bounced ?? summary?.bounced);
  const deliverySum =
    deliverySent + deliveryFailed + deliveryBlocked + deliveryBounced;

  const awaitingReply = useMemo(
    () => Math.max(0, emailsSent - totalReplies),
    [emailsSent, totalReplies]
  );

  const bounceMetricTone: KpiTone =
    bounceRate <= 5 ? "success" : bounceRate <= 15 ? "warning" : "danger";

  const backendOk = healthQ.data?.status === "ok";
  const dbOk = healthQ.data?.db === "ok";

  const anyError = summaryQ.isError || campaignsQ.isError || healthQ.isError;
  const initialLoading = summaryQ.isLoading && campaignsQ.isLoading;

  const summaryEmpty =
    !summaryQ.isLoading &&
    !summaryQ.isError &&
    emailsSent === 0 &&
    emailsFailed === 0 &&
    totalReplies === 0;

  const openCampaignsFiltered = useCallback(
    (search: string) => debouncedNavigate(`/campaigns${search}`),
    [debouncedNavigate]
  );

  const onEmailBarClick = useCallback(
    (name: string) => {
      if (name === "Sent") openCampaignsFiltered("?delivery_status=SENT");
      else if (name.includes("Undelivered")) openCampaignsFiltered("?delivery_status=FAILED");
      else if (name === "Bounced") openCampaignsFiltered("?reply_status=BOUNCED");
      else if (name === "Blocked") openCampaignsFiltered("?reply_status=BLOCKED");
    },
    [openCampaignsFiltered]
  );

  const onReplySliceClick = useCallback(
    (name: string) => {
      if (name === "Interested") openCampaignsFiltered("?reply_status=INTERESTED");
      else if (name === "Interview") openCampaignsFiltered("?reply_status=INTERVIEW");
      else if (name === "Rejected") openCampaignsFiltered("?reply_status=REJECTED");
      else if (name === "No Response") openCampaignsFiltered("?status=sent");
    },
    [openCampaignsFiltered]
  );

  const onActivityPointClick = useCallback(
    (_datum: ActivityLineDatum) => {
      openCampaignsFiltered("?status=sent");
    },
    [openCampaignsFiltered]
  );

  const lastUpdatedMs = Math.max(
    summaryQ.dataUpdatedAt ?? 0,
    campaignsQ.dataUpdatedAt ?? 0,
    healthQ.dataUpdatedAt ?? 0,
    schedulerQ.dataUpdatedAt ?? 0
  );
  const lastUpdatedLabel = lastUpdatedMs > 0 ? new Date(lastUpdatedMs).toLocaleString() : null;

  const emailBarData = useMemo(
    () => [
      { name: "Sent", value: deliverySent },
      { name: "Undelivered (other)", value: deliveryFailed },
      { name: "Bounced", value: deliveryBounced },
      { name: "Blocked", value: deliveryBlocked },
    ],
    [deliverySent, deliveryFailed, deliveryBounced, deliveryBlocked]
  );

  const replyPieData = useMemo(() => buildReplyDistribution(filteredActivityRows), [filteredActivityRows]);
  const activityLineData = useMemo(() => buildSentOverTime(filteredActivityRows), [filteredActivityRows]);
  const topStudent = useMemo(() => topStudentFromRows(filteredActivityRows), [filteredActivityRows]);

  const story = useMemo(() => {
    const sent = filteredActivityRows.filter((r) => String(r.status ?? "").toLowerCase() === "sent").length;
    const replies = filteredActivityRows.filter(hasReplySignal).length;
    const interested = filteredActivityRows.filter((r) => {
      const rs = replyStatusUpper(r);
      return rs === "INTERESTED" || rs === "INTERVIEW";
    }).length;
    const notResponded = Math.max(0, sent - replies);
    const interestedPct = replies > 0 ? (interested / replies) * 100 : 0;

    const replyDomains = new Map<string, number>();
    for (const r of filteredActivityRows) {
      if (!hasReplySignal(r)) continue;
      const d = emailDomain(r.hr_email);
      if (!d) continue;
      replyDomains.set(d, (replyDomains.get(d) ?? 0) + 1);
    }
    const topDomain = [...replyDomains.entries()].sort((a, b) => b[1] - a[1])[0] ?? null;

    return {
      sent,
      replies,
      interested,
      notResponded,
      interestedPct,
      topDomain: topDomain ? { domain: topDomain[0], replies: topDomain[1] } : null,
    };
  }, [filteredActivityRows]);

  const smartInsights = useMemo(() => {
    const insights: { tone: "danger" | "warning" | "neutral" | "success"; text: string }[] = [];

    if (bounceRate >= 20) {
      insights.push({
        tone: "danger",
        text: `High bounce rate detected (${bounceRate.toFixed(1)}%). Consider validating HR emails and tightening domain targeting.`,
      });
    } else if (bounceRate >= 12) {
      insights.push({
        tone: "warning",
        text: `Bounce rate is elevated (${bounceRate.toFixed(1)}%). A quick cleanup of invalid HR rows could improve delivery.`,
      });
    }

    if (story.sent >= 30 && story.replies > 0) {
      const rr = (story.replies / story.sent) * 100;
      if (rr < 8) {
        insights.push({
          tone: "warning",
          text: `Replies are low for this window (${rr.toFixed(1)}% of sends). Follow-ups + subject iteration usually lifts reply rate.`,
        });
      } else {
        insights.push({
          tone: "success",
          text: `Healthy reply flow in this window (${rr.toFixed(1)}% of sends). Keep templates consistent and scale what works.`,
        });
      }
    } else if (story.sent >= 10 && story.replies === 0) {
      insights.push({
        tone: "warning",
        text: "No replies recorded for this window yet. Consider sending a follow-up sequence after a short wait period.",
      });
    }

    if (story.topDomain && story.topDomain.replies >= 3) {
      insights.push({
        tone: "neutral",
        text: `Most replies in this window come from ${story.topDomain.domain} (${story.topDomain.replies} replies). Consider adding similar domains to targeting.`,
      });
    }

    if (story.notResponded >= 25) {
      insights.push({
        tone: "neutral",
        text: `${story.notResponded.toLocaleString()} HRs have not responded in this window. A focused follow-up review could unlock more replies.`,
      });
    }

    return insights.slice(0, 3);
  }, [bounceRate, story]);

  const deliverySegments = useMemo(
    () => [
      {
        key: "sent",
        label: "Sent",
        value: deliverySent,
        className: "bg-emerald-500",
        href: "?delivery_status=SENT",
      },
      {
        key: "failed",
        label: "Undelivered Emails (Invalid/Bounced)",
        value: deliveryFailed,
        className: "bg-red-500",
        href: "?delivery_status=FAILED",
      },
      {
        key: "blocked",
        label: "Blocked",
        value: deliveryBlocked,
        className: "bg-amber-500",
        href: "?reply_status=BLOCKED",
      },
      {
        key: "bounced",
        label: "Bounced",
        value: deliveryBounced,
        className: "bg-violet-500",
        href: "?reply_status=BOUNCED",
      },
    ],
    [deliverySent, deliveryFailed, deliveryBlocked, deliveryBounced]
  );

  return (
    <PageLayout
      title="Dashboard"
      subtitle="Time scope is explicit: KPIs are all‑time (summary). Story + charts + recent activity use the selected window."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {lastUpdatedLabel ? (
            <span className="hidden text-xs text-muted-foreground tabular-nums sm:inline">
              Last updated {lastUpdatedLabel}
            </span>
          ) : null}
          <Select value={chartRange} onValueChange={(v) => setChartRange(v as ChartRange)}>
            <SelectTrigger className="h-9 w-[200px] text-xs sm:text-sm" aria-label="Chart time range">
              <SelectValue placeholder="Time range" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">Charts: last 7 days</SelectItem>
              <SelectItem value="30">Charts: last 30 days</SelectItem>
              <SelectItem value="all">Charts: all loaded data</SelectItem>
            </SelectContent>
          </Select>
          <AnimatePresence mode="wait">
            {(summaryQ.isFetching || campaignsQ.isFetching || healthQ.isFetching || schedulerQ.isFetching) &&
            !initialLoading ? (
              <motion.div
                key="live"
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
              >
                <Badge variant="secondary" className="gap-1.5 pr-2 font-normal">
                  <span className="relative flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                  </span>
                  Updating…
                </Badge>
              </motion.div>
            ) : null}
          </AnimatePresence>
          <Button variant="outline" size="sm" asChild>
            <Link to="/campaigns">All campaigns</Link>
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {anyError ? (
          <Alert variant="destructive" className="rounded-xl border shadow-sm">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Backend error — check logs</AlertTitle>
            <AlertDescription className="text-sm">
              {summaryQ.isError ? "GET /analytics/summary failed. " : null}
              {campaignsQ.isError ? "GET /campaigns failed. " : null}
              {healthQ.isError ? "GET /health/ failed. " : null}
              Verify the API base URL and that the server is running.
            </AlertDescription>
          </Alert>
        ) : null}

        {analyticsSlow && !summaryQ.isError ? (
          <Alert className="rounded-xl border shadow-sm">
            <Activity className="h-4 w-4" />
            <AlertTitle>Analytics is taking longer than usual</AlertTitle>
            <AlertDescription className="text-sm">
              Showing cached/default values while it loads.
            </AlertDescription>
          </Alert>
        ) : null}

        {/* KPIs should be immediately visible under the Dashboard header. */}
        <section className="space-y-4">
          <div className="rounded-xl border border-border/60 bg-card/40 p-4 shadow-sm backdrop-blur-md transition-all duration-300 hover:shadow-md">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <h2 className="text-lg font-semibold text-foreground">Performance KPIs</h2>
              <Badge variant="secondary" className="font-normal" title="All-time metrics from GET /analytics/summary">
                All‑time metrics
              </Badge>
            </div>
            <p className="text-sm text-gray-500 dark:text-muted-foreground">
              Click a card to open Campaigns with the matching filter · live refresh every 10s
            </p>
          </div>
          <motion.div
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6"
            variants={container}
            initial="hidden"
            animate="show"
          >
              <motion.div variants={item} className="h-full min-h-[160px]">
                <MetricClickWrap
                  ariaLabel="Open campaigns filtered to sent emails"
                  onActivate={() => openCampaignsFiltered("?status=sent")}
                >
                  <KpiCard
                    title="Emails Sent"
                    numericValue={emailsSent}
                    subtext="Successfully delivered · click to filter"
                    icon={Mail}
                    tone="success"
                    className="h-full"
                  />
                </MetricClickWrap>
              </motion.div>
              <motion.div variants={item} className="h-full min-h-[160px]">
                <MetricClickWrap
                  ariaLabel="Open campaigns filtered to undelivered HR emails (invalid or bounced)"
                  onActivate={() => openCampaignsFiltered("?delivery_status=FAILED")}
                >
                  <KpiCard
                    title="Undelivered Emails"
                    numericValue={emailsFailed}
                    subtext="Delivery failed (see Bounced/Blocked breakdown)"
                    icon={XCircle}
                    tone="danger"
                    className="h-full"
                  />
                </MetricClickWrap>
              </motion.div>
              <motion.div variants={item} className="h-full min-h-[160px]">
                <MetricClickWrap
                  ariaLabel="Open all campaigns"
                  onActivate={() => openCampaignsFiltered("")}
                  title="Formula: success_rate = sent / (sent + failed) × 100 (all-time)"
                >
                  <KpiCard
                    title="Success Rate"
                    numericValue={successRate}
                    decimals={1}
                    valueSuffix="%"
                    subtext="Sent ÷ attempted · overview in Campaigns"
                    icon={TrendingUp}
                    tone="analytics"
                    className="h-full"
                  />
                </MetricClickWrap>
              </motion.div>
              <motion.div variants={item} className="h-full min-h-[160px]">
                <MetricClickWrap
                  ariaLabel="Open campaigns with reply status REPLIED"
                  onActivate={() => openCampaignsFiltered("?reply_status=REPLIED")}
                >
                  <KpiCard
                    title="Total Replies"
                    numericValue={totalReplies}
                    subtext="Replied campaigns · click to filter"
                    icon={MessageSquareReply}
                    tone="reply"
                    className="h-full"
                  />
                </MetricClickWrap>
              </motion.div>
              <motion.div variants={item} className="h-full min-h-[160px]">
                <MetricClickWrap
                  ariaLabel="Open interested replies"
                  onActivate={() => openCampaignsFiltered("?reply_status=INTERESTED")}
                >
                  <KpiCard
                    title="Interested Replies"
                    numericValue={interestedReplies}
                    subtext="reply_status=INTERESTED"
                    icon={Sparkles}
                    tone="reply"
                    className="h-full"
                  />
                </MetricClickWrap>
              </motion.div>
              <motion.div variants={item} className="h-full min-h-[160px]">
                <MetricClickWrap
                  ariaLabel="Open bounced campaigns"
                  onActivate={() => openCampaignsFiltered("?reply_status=BOUNCED")}
                  title="Formula: bounce_rate = bounced / sent × 100 (all-time; bounces are not replies)"
                >
                  <KpiCard
                    title="Bounce Rate"
                    numericValue={bounceRate}
                    decimals={1}
                    valueSuffix="%"
                    subtext="Open bounces in Campaigns"
                    icon={Activity}
                    tone={bounceMetricTone}
                    className="h-full"
                  />
                </MetricClickWrap>
              </motion.div>
            </motion.div>
        </section>

        {!anyError && !summaryEmpty ? (
          <motion.section
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-xl border border-border/60 bg-card/40 p-5 shadow-sm backdrop-blur-md transition-all duration-300 hover:shadow-md"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-indigo-500/[0.10] text-indigo-700 dark:text-indigo-300">
                  <Sparkles className="h-5 w-5" aria-hidden />
                </div>
                <div>
                  <p className="text-sm font-semibold text-foreground">Today’s insight</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    <span className="font-medium text-foreground">{rangeLabel(chartRange)} story</span>: you sent{" "}
                    <span className="font-semibold tabular-nums text-foreground">{story.sent.toLocaleString()}</span>{" "}
                    emails, received{" "}
                    <span className="font-semibold tabular-nums text-foreground">{story.replies.toLocaleString()}</span>{" "}
                    replies, and{" "}
                    <span className="font-semibold tabular-nums text-foreground">{story.interested.toLocaleString()}</span>{" "}
                    were interested{" "}
                    <span className="tabular-nums text-muted-foreground">
                      ({story.interestedPct.toFixed(1)}% of replies)
                    </span>
                    .{" "}
                    <span className="font-semibold tabular-nums text-foreground">
                      {story.notResponded.toLocaleString()}
                    </span>{" "}
                    HRs have not responded yet.
                  </p>
                </div>
              </div>
              <Badge variant="secondary" className="shrink-0 font-normal">
                Selected time window · {rangeLabel(chartRange)}
              </Badge>
            </div>

            {smartInsights.length > 0 ? (
              <div className="mt-4 grid gap-2 sm:grid-cols-3">
                {smartInsights.map((x, i) => (
                  <div
                    key={i}
                    className={cn(
                      "rounded-lg border px-3 py-2 text-xs leading-snug",
                      x.tone === "danger"
                        ? "border-red-500/25 bg-red-500/[0.06]"
                        : x.tone === "warning"
                          ? "border-amber-500/25 bg-amber-500/[0.08]"
                          : x.tone === "success"
                            ? "border-emerald-500/25 bg-emerald-500/[0.07]"
                            : "border-border/60 bg-muted/20"
                    )}
                  >
                    <p className="text-muted-foreground">{x.text}</p>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="mt-4 flex flex-wrap gap-2">
              <Button type="button" size="sm" onClick={() => openCampaignsFiltered("?status=sent")}>
                Review sends
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => openCampaignsFiltered("?reply_status=REPLIED")}>
                Review replies
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={() => openCampaignsFiltered("?delivery_status=FAILED")}>
                Fix undelivered
              </Button>
            </div>
          </motion.section>
        ) : null}

        {summaryEmpty ? (
          <div className="rounded-xl border border-dashed border-border/70 bg-gradient-to-br from-muted/30 to-transparent p-8 text-center shadow-sm transition-all duration-300 hover:shadow-md">
            <Inbox className="mx-auto h-10 w-10 text-muted-foreground/70" aria-hidden />
            <p className="mt-3 text-sm font-semibold text-foreground">No outreach data yet</p>
            <p className="mt-1 mx-auto max-w-md text-sm text-muted-foreground">
              Add students and HR contacts, then send campaigns. Metrics and the activity table will populate
              automatically.
            </p>
            <div className="mt-5 flex flex-wrap justify-center gap-2">
              <Button size="sm" asChild>
                <Link to="/students">Students</Link>
              </Button>
              <Button size="sm" variant="outline" asChild>
                <Link to="/hr-contacts">HR contacts</Link>
              </Button>
              <Button size="sm" variant="outline" asChild>
                <Link to="/campaigns">Campaigns</Link>
              </Button>
            </div>
          </div>
        ) : null}

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <EmailBarChart data={emailBarData} loading={summaryQ.isLoading} onBarClick={onEmailBarClick} />
          <ReplyPieChart data={replyPieData} loading={campaignsQ.isLoading} onSliceClick={onReplySliceClick} />
          <div className="lg:col-span-2">
            <ActivityLineChart
              data={activityLineData}
              loading={campaignsQ.isLoading}
              onPointClick={onActivityPointClick}
            />
          </div>
        </section>

        <section className="rounded-xl border bg-card/50 p-4 shadow-sm transition-all duration-300 hover:shadow-md backdrop-blur-md">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-foreground">Delivery analytics</h2>
              <p className="text-sm text-gray-500 dark:text-muted-foreground">
                Stacked mix of outcomes — click any segment to filter Campaigns
              </p>
            </div>
            <Badge variant="outline" className="font-mono text-xs">
              n = {deliverySum.toLocaleString()}
            </Badge>
          </div>
          <DeliveryStack
            segments={deliverySegments}
            disabled={summaryQ.isLoading}
            onNavigate={(href) => openCampaignsFiltered(href)}
          />
        </section>

        <InsightsBanner
          summary={summary}
          topStudentName={topStudent?.name ?? null}
          topStudentScore={topStudent?.count ?? 0}
        />

        {!summaryQ.isLoading && !summaryQ.isError ? (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex flex-col gap-4 rounded-xl border border-sky-500/20 bg-sky-500/[0.06] p-6 shadow-sm transition-all duration-300 hover:shadow-md sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="flex items-start gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-sky-500/15 text-sky-700 dark:text-sky-300">
                <MessageSquareReply className="h-6 w-6" aria-hidden />
              </div>
              <div>
                <p className="text-lg font-semibold text-foreground">Pipeline pulse</p>
                <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">
                  You have{" "}
                  <span className="font-bold tabular-nums text-foreground">
                    {awaitingReply.toLocaleString()}
                  </span>{" "}
                  sends without a recorded reply yet (sent − replies, from summary).
                </p>
              </div>
            </div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="shrink-0 gap-1"
              onClick={() => openCampaignsFiltered("?status=sent")}
            >
              Review sent
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </motion.div>
        ) : null}

        <RecentCampaigns
          rows={filteredActivityRows}
          isLoading={campaignsQ.isLoading}
          isError={campaignsQ.isError}
          onRetry={() => campaignsQ.refetch()}
          onRowClick={setDetailRow}
          formatTime={formatTime}
        />

        <Dialog open={detailRow != null} onOpenChange={(o) => !o && setDetailRow(null)}>
          <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto sm:rounded-xl">
            <DialogHeader>
              <DialogTitle className="text-lg">Campaign details</DialogTitle>
              <DialogDescription className="font-mono text-xs">{detailRow?.id}</DialogDescription>
            </DialogHeader>
            {detailRow ? (
              <div className="space-y-4 text-sm">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">Student</p>
                    <p className="font-medium">{detailRow.student_name ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">Company</p>
                    <p>{detailRow.company ?? "—"}</p>
                  </div>
                  <div className="sm:col-span-2">
                    <p className="text-xs font-medium text-muted-foreground">HR email</p>
                    <p className="break-all font-mono text-xs">{detailRow.hr_email ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">Type</p>
                    <StatusBadge raw={String(detailRow.email_type ?? "")}>
                      {String(detailRow.email_type ?? "—")}
                    </StatusBadge>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground">Sent at</p>
                    <p className="tabular-nums text-muted-foreground">{formatTime(detailRow.sent_at)}</p>
                  </div>
                  <div className="flex flex-wrap gap-2 sm:col-span-2">
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted-foreground">Status</p>
                      <StatusBadge raw={String(detailRow.status ?? "")}>{String(detailRow.status ?? "—")}</StatusBadge>
                    </div>
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted-foreground">Reply</p>
                      {detailRow.reply_status ? (
                        <StatusBadge tone={replyCategoryTone(detailRow.reply_status)}>
                          {detailRow.reply_status}
                        </StatusBadge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </div>
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted-foreground">Delivery</p>
                      <StatusBadge raw={String(detailRow.delivery_status ?? "SENT")}>
                        {String(detailRow.delivery_status ?? "—")}
                      </StatusBadge>
                    </div>
                  </div>
                  {detailRow.template_label ? (
                    <div className="sm:col-span-2">
                      <p className="text-xs font-medium text-muted-foreground">Template label</p>
                      <Badge variant="outline">{detailRow.template_label}</Badge>
                    </div>
                  ) : null}
                  {detailRow.subject ? (
                    <div className="sm:col-span-2">
                      <p className="text-xs font-medium text-muted-foreground">Subject</p>
                      <p className="rounded-md border bg-muted/30 p-2 text-sm">{detailRow.subject}</p>
                    </div>
                  ) : null}
                  {detailRow.body ? (
                    <div className="sm:col-span-2">
                      <p className="text-xs font-medium text-muted-foreground">Body</p>
                      <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md border bg-muted/30 p-3 text-xs">
                        {detailRow.body}
                      </pre>
                    </div>
                  ) : null}
                  {detailRow.error ? (
                    <div className="sm:col-span-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3">
                      <p className="text-xs font-medium text-destructive">Error</p>
                      <p className="mt-1 text-xs text-destructive/90">{detailRow.error}</p>
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}
            <DialogFooter className="gap-2 sm:gap-0">
              <Button type="button" variant="outline" onClick={() => setDetailRow(null)}>
                Close
              </Button>
              <Button
                type="button"
                className="gap-1"
                onClick={() => {
                  const id = detailRow?.id;
                  setDetailRow(null);
                  if (id) openCampaignsFiltered(`?campaign_id=${encodeURIComponent(id)}`);
                  else openCampaignsFiltered("");
                }}
              >
                View in Campaigns
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </PageLayout>
  );
}
