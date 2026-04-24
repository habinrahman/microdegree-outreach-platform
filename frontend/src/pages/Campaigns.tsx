import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Link } from "react-router-dom";
import { Clock, Inbox, Megaphone } from "lucide-react";
import { PageLayout } from "@/components/PageLayout";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { FilterBar, FilterField } from "@/components/FilterBar";
import { Button } from "@/components/ui/button";
import { TABLE_PAGE_SIZE } from "@/lib/constants";
import { ListPagination } from "@/components/ListPagination";
import { EmptyState } from "@/components/EmptyState";
import { listCampaigns, patchCampaigns, type CampaignRow } from "@/api/campaigns";
import { sendFollowup1 } from "@/api/api";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const FILTER_KEYS = [
  "reply_status",
  "delivery_status",
  "campaign_type",
  "is_valid_hr",
  "status",
  "student_id",
  "hr_id",
  "template_label",
] as const;

function buildListParams(sp: URLSearchParams): Record<string, string | boolean | number> {
  const page = Math.max(1, parseInt(sp.get("page") || "1", 10) || 1);
  const skip = (page - 1) * TABLE_PAGE_SIZE;
  const p: Record<string, string | boolean | number> = {
    limit: TABLE_PAGE_SIZE,
    skip,
  };
  const rs = (sp.get("reply_status") ?? "").trim();
  if (rs) p.reply_status = rs;
  const ds = (sp.get("delivery_status") ?? "").trim();
  if (ds) p.delivery_status = ds;
  const ct = (sp.get("campaign_type") ?? "").trim();
  if (ct === "followup") p.campaign_type = "followup";
  else if (ct === "initial") p.email_type = "initial";
  const vh = (sp.get("is_valid_hr") ?? "").trim();
  if (vh === "true") p.is_valid_hr = true;
  if (vh === "false") p.is_valid_hr = false;
  const st = (sp.get("status") ?? "").trim();
  if (st) p.status = st;
  const sid = (sp.get("student_id") ?? "").trim();
  if (sid) p.student_id = sid;
  const hid = (sp.get("hr_id") ?? "").trim();
  if (hid) p.hr_id = hid;
  const tl = (sp.get("template_label") ?? "").trim();
  if (tl) p.template_label = tl;
  return p;
}

const SEL_ANY = "__all__";
const REPLY_NONE = "__reply_none__";
const REPLY_PRESET_VALUES = new Set([
  "INTERESTED",
  "REJECTED",
  "INTERVIEW",
  "AUTO_REPLY",
  "BOUNCED",
  "BLOCKED",
  "REPLIED",
  "OTHER",
]);

function replyStatusSelectValue(filter: string): string {
  const t = filter.trim();
  if (!t) return REPLY_NONE;
  if (REPLY_PRESET_VALUES.has(t.toUpperCase())) return t.toUpperCase();
  return t;
}

export default function Campaigns() {
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const highlightId = (searchParams.get("campaign_id") ?? "").trim();
  const scrolledRef = useRef<string | null>(null);

  const listParams = useMemo(() => buildListParams(searchParams), [searchParams]);

  const filterSig = useMemo(() => {
    const u = new URLSearchParams(searchParams);
    u.delete("page");
    u.delete("campaign_id");
    return u.toString();
  }, [searchParams]);

  const listQ = useQuery({
    queryKey: ["campaigns", listParams],
    queryFn: () => listCampaigns(listParams),
    refetchInterval: 30_000,
    refetchIntervalInBackground: true,
  });

  const [timelineRow, setTimelineRow] = useState<CampaignRow | null>(null);

  const patchUrl = useCallback(
    (updates: Record<string, string | null | undefined>) => {
      const next = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(updates)) {
        const v = value ?? "";
        if (v === "") next.delete(key);
        else next.set(key, v);
      }
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const prevFilterSig = useRef<string | null>(null);
  useEffect(() => {
    if (prevFilterSig.current === null) {
      prevFilterSig.current = filterSig;
      return;
    }
    if (prevFilterSig.current === filterSig) return;
    prevFilterSig.current = filterSig;
    const p = searchParams.get("page");
    if (p && p !== "1") patchUrl({ page: undefined });
  }, [filterSig, searchParams, patchUrl]);

  const replyStatusFilter = searchParams.get("reply_status") ?? "";
  const deliveryStatusFilter = searchParams.get("delivery_status") ?? "";
  const campaignTypeFilter = searchParams.get("campaign_type") ?? "";
  const hrValidityFilter = searchParams.get("is_valid_hr") ?? "";
  const statusFilter = searchParams.get("status") ?? "";

  const deliverySelectValue = (deliveryStatusFilter.trim().toUpperCase() || SEL_ANY) as string;
  const statusSelectValue = statusFilter.trim() || SEL_ANY;
  const campaignTypeSelectValue = campaignTypeFilter.trim() || SEL_ANY;
  const hrValiditySelectValue = hrValidityFilter.trim() || SEL_ANY;

  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const rows = useMemo(() => {
    const data = listQ.data;
    return ((data || []) as Record<string, unknown>[]).map((c) => ({
      ...c,
      company: c.company || c.hr_company || c.organization || "—",
      hr_email: c.hr_email || c.email || "—",
    })) as CampaignRow[];
  }, [listQ.data]);

  useEffect(() => {
    if (!highlightId || !listQ.isSuccess || rows.length === 0) return;
    if (scrolledRef.current === highlightId) return;
    const found = rows.some((r) => String(r.id) === highlightId);
    if (!found) return;
    scrolledRef.current = highlightId;
    const id = requestAnimationFrame(() => {
      const el = document.getElementById(`campaign-row-${highlightId}`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    return () => cancelAnimationFrame(id);
  }, [highlightId, listQ.isSuccess, rows]);

  useEffect(() => {
    scrolledRef.current = null;
  }, [highlightId]);

  const patchM = useMutation({
    mutationFn: (body: { campaign_ids: string[]; status: "paused" | "cancelled" }) =>
      patchCampaigns(body),
    onSuccess: (res) => {
      const r = res as { updated?: number; detail?: string };
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      setSelected({});
      if ((r.updated ?? 0) === 0 && r.detail) {
        toast.error(r.detail);
        return;
      }
      toast.success(`Updated ${r.updated ?? 0} campaign(s)`);
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(typeof d === "string" ? d : "PATCH failed");
    },
  });

  const followM = useMutation({
    mutationFn: async (pairs: { student_id: string; hr_id: string }[]) => {
      for (const p of pairs) {
        await sendFollowup1({ student_id: p.student_id, hr_id: p.hr_id, template_label: null });
      }
    },
    onSuccess: () => {
      toast.success("Follow-up sent for selected pairs");
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      setSelected({});
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Follow-up failed");
    },
  });

  const selectedIds = Object.keys(selected).filter((id) => selected[id]);
  const rowIds = (rows || []).map((r) => String(r.id)).filter(Boolean);
  const allSelected = rowIds.length > 0 && selectedIds.length === rowIds.length;
  const someSelected = selectedIds.length > 0 && !allSelected;

  const toggleSelectAll = (on: boolean) => {
    if (!on) {
      setSelected({});
      return;
    }
    const next: Record<string, boolean> = {};
    rowIds.forEach((id) => {
      next[id] = true;
    });
    setSelected(next);
  };

  const clearFilters = () => {
    const next = new URLSearchParams(searchParams);
    for (const k of FILTER_KEYS) next.delete(k);
    next.delete("page");
    setSearchParams(next, { replace: true });
  };

  const columns: ColumnDef<CampaignRow>[] = [
    {
      id: "x",
      header: (
        <Checkbox
          aria-label="Select all"
          checked={allSelected ? true : someSelected ? "indeterminate" : false}
          onCheckedChange={(v) => toggleSelectAll(v === true)}
        />
      ),
      className: "w-10",
      cell: (r) => (
        <Checkbox
          checked={!!selected[String(r.id)]}
          onCheckedChange={(v) =>
            setSelected((prev) => ({ ...prev, [String(r.id)]: v === true }))
          }
          aria-label={`Select campaign ${r.id}`}
        />
      ),
    },
    { id: "student", header: "Student", cell: (r) => String(r.student_name ?? "—") },
    { id: "company", header: "Company", cell: (r) => String(r.company ?? "—") },
    { id: "hr_email", header: "HR email", cell: (r) => String(r.hr_email ?? "—") },
    {
      id: "email_type",
      header: "Type",
      cell: (r) => <StatusBadge raw={String(r.email_type)}>{String(r.email_type ?? "—")}</StatusBadge>,
    },
    {
      id: "status",
      header: "Status",
      cell: (r) => <StatusBadge raw={String(r.status)}>{String(r.status ?? "—")}</StatusBadge>,
    },
    {
      id: "reply_status",
      header: "Reply status",
      cell: (r) => <StatusBadge raw={String(r.reply_status)}>{String(r.reply_status ?? "—")}</StatusBadge>,
    },
    {
      id: "delivery",
      header: "Delivery",
      cell: (r) => (
        <StatusBadge raw={String(r.delivery_status ?? "SENT")}>
          {String(r.delivery_status ?? "—")}
        </StatusBadge>
      ),
    },
    {
      id: "sent_at",
      header: "Sent at",
      cell: (r) => (
        <span className="tabular-nums text-muted-foreground text-sm">{String(r.sent_at ?? "—")}</span>
      ),
    },
    {
      id: "timeline",
      header: "",
      cell: (r) => (
        <Button type="button" variant="ghost" size="sm" className="h-8 gap-1 text-xs" onClick={() => setTimelineRow(r)}>
          <Clock className="h-3.5 w-3.5" />
          Timeline
        </Button>
      ),
    },
  ];

  const uniquePairs = () => {
    const m = new Map<string, { student_id: string; hr_id: string }>();
    for (const id of selectedIds) {
      const row = rows.find((x) => String(x.id) === id);
      if (row?.student_id && row.hr_id) {
        m.set(`${row.student_id}:${row.hr_id}`, {
          student_id: String(row.student_id),
          hr_id: String(row.hr_id),
        });
      }
    }
    return [...m.values()];
  };

  const metrics = useMemo(() => {
    const list = rows || [];
    const total = list.length;
    const sent = list.filter((r) => String(r.status).toLowerCase() === "sent").length;
    const failed = list.filter((r) => String(r.status).toLowerCase() === "failed").length;
    const replied = list.filter((r) => String(r.status).toLowerCase() === "replied").length;
    return { total, sent, failed, replied };
  }, [rows]);

  const replyCustomExact = useMemo(() => {
    const t = replyStatusFilter.trim();
    if (!t || REPLY_PRESET_VALUES.has(t.toUpperCase())) return null;
    return t;
  }, [replyStatusFilter]);

  const page = Math.max(1, parseInt(searchParams.get("page") || "1", 10) || 1);
  const hasNextPage = listQ.isSuccess && rows.length === TABLE_PAGE_SIZE;

  return (
    <PageLayout
      title="Campaigns"
      subtitle="GET /campaigns · filters sync with the URL · auto-refresh every 30s"
      filters={
        <FilterBar>
          <FilterField label="Reply status">
            <Select
              value={replyStatusSelectValue(replyStatusFilter)}
              onValueChange={(v) => {
                if (v === REPLY_NONE) patchUrl({ reply_status: null });
                else patchUrl({ reply_status: v });
              }}
            >
              <SelectTrigger className="h-10 min-w-[220px] text-sm" aria-label="Reply status filter">
                <SelectValue placeholder="Any" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={REPLY_NONE}>Any</SelectItem>
                <SelectItem value="INTERESTED">INTERESTED</SelectItem>
                <SelectItem value="REJECTED">REJECTED</SelectItem>
                <SelectItem value="INTERVIEW">INTERVIEW</SelectItem>
                <SelectItem value="AUTO_REPLY">AUTO_REPLY</SelectItem>
                <SelectItem value="BOUNCED">BOUNCED</SelectItem>
                <SelectItem value="BLOCKED">BLOCKED</SelectItem>
                <SelectItem value="REPLIED">REPLIED</SelectItem>
                <SelectItem value="OTHER">OTHER</SelectItem>
                {replyCustomExact ? (
                  <SelectItem value={replyCustomExact}>
                    Current value: {replyCustomExact.length > 56 ? `${replyCustomExact.slice(0, 56)}…` : replyCustomExact}
                  </SelectItem>
                ) : null}
              </SelectContent>
            </Select>
          </FilterField>
          <FilterField label="Delivery status">
            <Select
              value={deliverySelectValue}
              onValueChange={(v) =>
                patchUrl({ delivery_status: v === SEL_ANY ? null : v.toUpperCase() })
              }
            >
              <SelectTrigger className="h-10 min-w-[200px] text-sm" aria-label="Delivery status">
                <SelectValue placeholder="Any" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={SEL_ANY}>Any</SelectItem>
                <SelectItem value="SENT">SENT</SelectItem>
                <SelectItem value="FAILED">Undelivered (invalid/bounced HR)</SelectItem>
              </SelectContent>
            </Select>
          </FilterField>
          <FilterField label="Campaign status">
            <Select
              value={statusSelectValue}
              onValueChange={(v) => patchUrl({ status: v === SEL_ANY ? null : v })}
            >
              <SelectTrigger className="h-10 min-w-[180px] text-sm" aria-label="Campaign status">
                <SelectValue placeholder="Any" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={SEL_ANY}>Any</SelectItem>
                <SelectItem value="pending">pending</SelectItem>
                <SelectItem value="scheduled">scheduled</SelectItem>
                <SelectItem value="processing">processing</SelectItem>
                <SelectItem value="sent">sent</SelectItem>
                <SelectItem value="failed">failed</SelectItem>
                <SelectItem value="replied">replied</SelectItem>
                <SelectItem value="expired">expired</SelectItem>
              </SelectContent>
            </Select>
          </FilterField>
          <FilterField label="Message type (URL: campaign_type)">
            <Select
              value={campaignTypeSelectValue}
              onValueChange={(v) => patchUrl({ campaign_type: v === SEL_ANY ? null : v })}
            >
              <SelectTrigger className="h-10 min-w-[260px] text-sm" aria-label="Message type filter">
                <SelectValue placeholder="Any" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={SEL_ANY}>Any</SelectItem>
                <SelectItem value="initial">Initial send (API: email_type=initial)</SelectItem>
                <SelectItem value="followup">Follow-up (API: campaign_type=followup)</SelectItem>
              </SelectContent>
            </Select>
          </FilterField>
          <FilterField label="HR validity">
            <Select
              value={hrValiditySelectValue}
              onValueChange={(v) => patchUrl({ is_valid_hr: v === SEL_ANY ? null : v })}
            >
              <SelectTrigger className="h-10 min-w-[160px] text-sm" aria-label="HR validity">
                <SelectValue placeholder="Any" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={SEL_ANY}>Any</SelectItem>
                <SelectItem value="true">Valid only</SelectItem>
                <SelectItem value="false">Invalid only</SelectItem>
              </SelectContent>
            </Select>
          </FilterField>
          <FilterField label="Deep link">
            <div className="flex flex-col gap-2">
              <Button type="button" variant="outline" size="sm" className="h-9 w-full" onClick={clearFilters}>
                Clear filters
              </Button>
              {highlightId ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-8 text-xs"
                  onClick={() => patchUrl({ campaign_id: null })}
                >
                  Clear row highlight
                </Button>
              ) : null}
            </div>
          </FilterField>
        </FilterBar>
      }
      actions={
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={!selectedIds.length || patchM.isPending}
            onClick={() => patchM.mutate({ campaign_ids: selectedIds, status: "paused" })}
          >
            Bulk pause (PATCH)
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={!selectedIds.length || patchM.isPending}
            onClick={() => patchM.mutate({ campaign_ids: selectedIds, status: "cancelled" })}
          >
            Bulk cancel (PATCH)
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!selectedIds.length || followM.isPending}
            onClick={() => {
              const pairs = uniquePairs();
              if (!pairs.length) toast.error("No valid rows");
              else followM.mutate(pairs);
            }}
          >
            Send follow-up (POST /followup1/send)
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!selectedIds.length}
            onClick={() => setSelected({})}
          >
            Clear selection
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => listQ.refetch()}>
            Refresh
          </Button>
        </div>
      }
    >
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0 }}>
          <PremiumCard className="p-4">
            <div className="flex items-center justify-between">
              <p className="text-lg font-semibold">In view</p>
              <Megaphone className="h-5 w-5 text-[#4F46E5]" />
            </div>
            <p className="mt-2 text-3xl font-bold tabular-nums">{listQ.isLoading ? "…" : metrics.total}</p>
            <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">After filters · this page</p>
          </PremiumCard>
        </motion.div>
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.04 }}>
          <PremiumCard className="p-4">
            <p className="text-lg font-semibold">Sent</p>
            <p className="mt-2 text-3xl font-bold tabular-nums text-[#22C55E]">{listQ.isLoading ? "…" : metrics.sent}</p>
            <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">Status = sent · this page</p>
          </PremiumCard>
        </motion.div>
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}>
          <PremiumCard className="p-4">
            <p className="text-lg font-semibold">Undelivered Emails (Invalid/Bounced)</p>
            <p className="mt-2 text-3xl font-bold tabular-nums text-[#EF4444]">{listQ.isLoading ? "…" : metrics.failed}</p>
            <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">Failed rows · this page</p>
          </PremiumCard>
        </motion.div>
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.12 }}>
          <PremiumCard className="p-4">
            <p className="text-lg font-semibold">Replied</p>
            <p className="mt-2 text-3xl font-bold tabular-nums text-[#3B82F6]">{listQ.isLoading ? "…" : metrics.replied}</p>
            <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">Status = replied · this page</p>
          </PremiumCard>
        </motion.div>
      </div>

      {listQ.isLoading ? null : (
        <p className="text-xs text-muted-foreground">
          Showing {rows.length.toLocaleString()} campaign{rows.length === 1 ? "" : "s"} on this page (
          {TABLE_PAGE_SIZE} per request).
          {hasNextPage ? (
            <span className="ml-1 font-medium text-amber-700 dark:text-amber-400">
              More results on the next page.
            </span>
          ) : null}
        </p>
      )}

      <DataTable<CampaignRow>
        columns={columns}
        data={rows}
        getRowKey={(r) => String(r.id)}
        getRowProps={(r) => {
          const id = String(r.id);
          const isHi = highlightId !== "" && id === highlightId;
          return {
            id: `campaign-row-${id}`,
            className: cn(
              isHi &&
                "bg-amber-500/15 ring-2 ring-amber-500/60 ring-inset animate-in fade-in duration-500"
            ),
          };
        }}
        loading={listQ.isLoading}
        emptyMessage={listQ.isError ? "Not available" : "No campaigns."}
        emptyState={
          listQ.isError || listQ.isLoading ? undefined : (
            <EmptyState
              icon={Inbox}
              title="No campaigns match"
              description="Try clearing filters or widening reply / delivery criteria. New sends appear here within a refresh cycle."
            >
              <Button type="button" variant="default" size="sm" asChild>
                <Link to="/outreach">Go to Outreach</Link>
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={clearFilters}>
                Clear filters
              </Button>
            </EmptyState>
          )
        }
      />

      {listQ.isLoading ? null : (
        <div className="mt-3">
          <ListPagination
            page={page}
            hasNext={hasNextPage}
            hasPrev={page > 1}
            pageSize={TABLE_PAGE_SIZE}
            onPageChange={(next) => patchUrl({ page: next <= 1 ? undefined : String(next) })}
          />
        </div>
      )}

      <Dialog open={timelineRow != null} onOpenChange={(o) => !o && setTimelineRow(null)}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto rounded-xl sm:rounded-xl">
          <DialogHeader>
            <DialogTitle className="text-lg font-semibold">Campaign timeline</DialogTitle>
            <DialogDescription className="font-mono text-xs">ID: {timelineRow?.id}</DialogDescription>
          </DialogHeader>
          {timelineRow ? (
            <div className="space-y-4 text-sm">
              <PremiumCard className="space-y-3 p-4">
                <TimelineItem label="Student" value={String(timelineRow.student_name ?? "—")} />
                <TimelineItem label="Company" value={String(timelineRow.company ?? "—")} />
                <TimelineItem label="HR email" value={String(timelineRow.hr_email ?? "—")} />
                <TimelineItem label="Email type" value={String(timelineRow.email_type ?? "—")} />
                <TimelineItem label="Campaign status" value={String(timelineRow.status ?? "—")} />
                <TimelineItem label="Reply status" value={String(timelineRow.reply_status ?? "—")} />
                <TimelineItem label="Delivery" value={String(timelineRow.delivery_status ?? "—")} />
                <TimelineItem label="Sent at" value={String(timelineRow.sent_at ?? "—")} />
              </PremiumCard>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </PageLayout>
  );
}

function TimelineItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-border/50 pb-2 last:border-0 last:pb-0">
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
