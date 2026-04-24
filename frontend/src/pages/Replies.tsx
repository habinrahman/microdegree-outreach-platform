import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Eye, Sparkles } from "lucide-react";
import { PageLayout } from "@/components/PageLayout";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { FilterBar, FilterField } from "@/components/FilterBar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { API_LIST_LIMITS } from "@/lib/constants";
import { getReplies, patchReply } from "@/api/api";
import { StatusBadge, replyCategoryTone } from "@/components/StatusBadge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type ReplyRow = {
  campaign_id: string;
  reply_message?: string | null;
  reply_status?: string | null;
  reply_type?: string | null;
  student_name?: string | null;
  company?: string | null;
  hr_email?: string | null;
  created_at?: string | null;
  time?: string | null;
  status?: string | null;
  notes?: string | null;
};

const WF = ["OPEN", "IN_PROGRESS", "CLOSED"] as const;

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

const DAYS_ANY = "__all__";

/** Backend GET /replies uses `reply_type` (lowercase slugs); see FILTER_TO_CANONICAL. */
const REPLY_UI_TO_API_TYPE: Record<string, string> = {
  INTERESTED: "interested",
  REJECTED: "rejected",
  INTERVIEW: "interview",
  AUTO_REPLY: "auto_reply",
  BOUNCED: "bounce",
  BLOCKED: "bounce",
  OTHER: "other",
};

function replyListQueryParams(statusUi: string): Record<string, string> {
  const u = statusUi.trim().toUpperCase();
  if (!u || u === "REPLIED") return {};
  const slug = REPLY_UI_TO_API_TYPE[u];
  if (!slug) return {};
  return { reply_type: slug };
}

function replyFilterSelectValue(s: string): string {
  const t = s.trim();
  if (!t) return REPLY_NONE;
  if (REPLY_PRESET_VALUES.has(t.toUpperCase())) return t.toUpperCase();
  return t;
}

const cleanMessage = (msg: string) => {
  if (!msg) return "";
  return msg.split("-----Original Message-----")[0].trim();
};

function parseReplyDate(r: ReplyRow): number | null {
  const raw = r.created_at ?? r.time;
  if (!raw) return null;
  const t = Date.parse(String(raw));
  return Number.isFinite(t) ? t : null;
}

export default function Replies() {
  const qc = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, { status: string; notes: string }>>({});
  const [replyStatus, setReplyStatus] = useState("");
  const [daysFilter, setDaysFilter] = useState("");
  const [search, setSearch] = useState("");

  const replyQueryParams = useMemo(
    () => replyListQueryParams(replyStatus),
    [replyStatus]
  );

  const listQ = useQuery({
    queryKey: ["replies", replyQueryParams],
    queryFn: () => getReplies(replyQueryParams as Record<string, unknown>),
    refetchInterval: 30_000,
    refetchIntervalInBackground: true,
  });

  const [preview, setPreview] = useState<ReplyRow | null>(null);

  const patchM = useMutation({
    mutationFn: (args: { id: string; payload: { status?: string; notes?: string } }) =>
      patchReply(args.id, args.payload),
    onSuccess: (_data, vars) => {
      toast.success("Saved", {
        action: {
          label: "View in Campaigns",
          onClick: () => {
            const id = String(vars.id ?? "").trim();
            if (!id) return;
            window.location.assign(`/campaigns?campaign_id=${encodeURIComponent(id)}`);
          },
        },
      });
      qc.invalidateQueries({ queryKey: ["replies"] });
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(typeof d === "string" ? d : "PATCH failed");
    },
  });

  const apiReplies = (listQ.data ?? []) as ReplyRow[];

  const rows = useMemo(() => {
    let list = (listQ.data ?? []) as ReplyRow[];
    const u = replyStatus.trim().toUpperCase();
    if (u === "REPLIED") {
      list = list.filter(
        (r) =>
          String(r.reply_status ?? "").toUpperCase() === "REPLIED" ||
          String(r.reply_type ?? "").toUpperCase() === "REPLIED"
      );
    } else if (u && !REPLY_UI_TO_API_TYPE[u]) {
      const needle = replyStatus.trim().toLowerCase();
      list = list.filter((r) =>
        [r.reply_status, r.reply_type].some((v) => String(v ?? "").toLowerCase().includes(needle))
      );
    }
    const now = Date.now();
    if (daysFilter === "7") {
      const ms = 7 * 24 * 60 * 60 * 1000;
      list = list.filter((r) => {
        const t = parseReplyDate(r);
        return t != null && now - t <= ms;
      });
    } else if (daysFilter === "30") {
      const ms = 30 * 24 * 60 * 60 * 1000;
      list = list.filter((r) => {
        const t = parseReplyDate(r);
        return t != null && now - t <= ms;
      });
    }
    const s = search.trim().toLowerCase();
    if (s) {
      list = list.filter((r) =>
        [r.student_name, r.company, r.hr_email, r.reply_message, r.reply_status, r.reply_type].some(
          (v) => String(v ?? "").toLowerCase().includes(s)
        )
      );
    }
    return list;
  }, [listQ.data, daysFilter, search, replyStatus]);

  const replyCustomExact = useMemo(() => {
    const t = replyStatus.trim();
    if (!t || REPLY_PRESET_VALUES.has(t.toUpperCase())) return null;
    return t;
  }, [replyStatus]);

  const draft = (r: ReplyRow) =>
    drafts[r.campaign_id] ?? {
      status: r.status || "OPEN",
      notes: r.notes || "",
    };

  const columns: ColumnDef<ReplyRow>[] = [
    {
      id: "msg",
      header: "Reply message",
      cell: (r) => {
        const text = cleanMessage(String(r.reply_message ?? ""));
        return (
          <span className="line-clamp-2 max-w-[220px] text-sm" title={text}>
            {text || "—"}
          </span>
        );
      },
    },
    {
      id: "reply_type",
      header: "Reply type",
      cell: (r) => {
        const label = String(r.reply_type ?? r.reply_status ?? "—");
        return (
          <StatusBadge tone={replyCategoryTone(r.reply_type ?? r.reply_status)} raw={label}>
            {label}
          </StatusBadge>
        );
      },
    },
    {
      id: "reply_delivery",
      header: "Reply status",
      cell: (r) => (
        <StatusBadge raw={String(r.reply_status ?? "")}>
          {String(r.reply_status ?? "—")}
        </StatusBadge>
      ),
    },
    { id: "student", header: "Student", cell: (r) => r.student_name ?? "—" },
    { id: "company", header: "Company", cell: (r) => r.company ?? "—" },
    { id: "hr", header: "HR email", cell: (r) => r.hr_email ?? "—" },
    {
      id: "created",
      header: "Created",
      cell: (r) => (
        <span className="tabular-nums text-xs text-muted-foreground">
          {r.created_at ?? r.time ?? "—"}
        </span>
      ),
    },
    {
      id: "wf",
      header: "Status (triage)",
      cell: (r) => {
        const d = draft(r);
        return (
          <div className="flex flex-col gap-1.5 min-w-[140px]">
            <StatusBadge raw={d.status}>{d.status}</StatusBadge>
            <Select
              value={d.status}
              onValueChange={(v) =>
                setDrafts((prev) => ({
                  ...prev,
                  [r.campaign_id]: { ...d, status: v },
                }))
              }
            >
              <SelectTrigger className="h-9 w-[160px] text-xs" aria-label="Triage status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(WF || []).map((w) => (
                  <SelectItem key={w} value={w}>
                    {w}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        );
      },
    },
    {
      id: "notes",
      header: "Notes",
      cell: (r) => {
        const d = draft(r);
        return (
          <Textarea
            className="min-h-[52px] w-[160px] resize-y text-xs"
            value={d.notes}
            onChange={(e) =>
              setDrafts((prev) => ({
                ...prev,
                [r.campaign_id]: { ...d, notes: e.target.value },
              }))
            }
          />
        );
      },
    },
    {
      id: "save",
      header: "",
      cell: (r) => {
        const d = draft(r);
        return (
          <div className="flex flex-col gap-1">
            <Button type="button" size="sm" variant="ghost" className="h-8 gap-1 px-2 text-xs" onClick={() => setPreview(r)}>
              <Eye className="h-3.5 w-3.5" />
              Preview
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={patchM.isPending}
              onClick={() =>
                patchM.mutate({
                  id: r.campaign_id,
                  payload: { status: d.status, notes: d.notes },
                })
              }
            >
              Save
            </Button>
          </div>
        );
      },
    },
  ];

  const repliesLimit = API_LIST_LIMITS.replies;
  const atRepliesCap = listQ.isSuccess && apiReplies.length >= repliesLimit;

  const filterBar = (
    <FilterBar>
      <FilterField label="Reply status">
        <Select
          value={replyFilterSelectValue(replyStatus)}
          onValueChange={(v) => setReplyStatus(v === REPLY_NONE ? "" : v)}
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
      <FilterField label="Date">
        <Select value={daysFilter || DAYS_ANY} onValueChange={(v) => setDaysFilter(v === DAYS_ANY ? "" : v)}>
          <SelectTrigger className="h-10 min-w-[180px] text-sm" aria-label="Date range">
            <SelectValue placeholder="All time" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={DAYS_ANY}>All time</SelectItem>
            <SelectItem value="7">Last 7 days</SelectItem>
            <SelectItem value="30">Last 30 days</SelectItem>
          </SelectContent>
        </Select>
      </FilterField>
      <FilterField label="Search">
        <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search…" />
      </FilterField>
    </FilterBar>
  );

  return (
    <PageLayout
      title="Replies"
      subtitle="GET /replies?reply_type=… · PATCH /replies/:campaign_id · triage OPEN → IN_PROGRESS → CLOSED · refresh every 30s"
      filters={filterBar}
    >
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6 flex flex-wrap items-center gap-4 rounded-xl border border-sky-500/20 bg-sky-500/[0.06] p-4 shadow-sm transition-all duration-300 hover:shadow-md"
      >
        <Sparkles className="h-5 w-5 text-sky-600 dark:text-sky-400" />
        <p className="text-sm text-gray-600 dark:text-muted-foreground">
          Use workflow status for triage; reply-type badges summarize inbound classification. Preview opens the full thread
          snippet.
        </p>
      </motion.div>
      {listQ.isError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Backend error — check server logs</AlertTitle>
          <AlertDescription>GET /replies failed.</AlertDescription>
        </Alert>
      ) : null}
      {listQ.isLoading ? null : (
        <p className="mb-2 text-xs text-muted-foreground">
          Showing {rows.length.toLocaleString()} of {apiReplies.length.toLocaleString()} replies from this request (API
          limit {repliesLimit.toLocaleString()}).
          {daysFilter || search.trim() || replyStatus.trim().toUpperCase() === "REPLIED" || (replyStatus.trim() && !REPLY_UI_TO_API_TYPE[replyStatus.trim().toUpperCase()])
            ? " Client-side filters (date, search, REPLIED, or custom reply status) apply after load."
            : replyStatus.trim()
              ? " Reply-type filter is applied server-side via reply_type."
              : null}
          {atRepliesCap ? (
            <span className="ml-1 font-medium text-amber-700 dark:text-amber-400">
              List may be truncated at the API limit.
            </span>
          ) : null}
        </p>
      )}
      <DataTable<ReplyRow>
        columns={columns}
        data={listQ.isError ? [] : rows}
        getRowKey={(r) => r.campaign_id}
        loading={listQ.isLoading}
        emptyMessage={listQ.isError ? "Request failed." : "No replies."}
      />

      <Dialog open={preview != null} onOpenChange={(o) => !o && setPreview(null)}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto rounded-xl">
          <DialogHeader>
            <DialogTitle className="text-lg font-semibold">Reply preview</DialogTitle>
            <DialogDescription className="font-mono text-xs">{preview?.campaign_id}</DialogDescription>
          </DialogHeader>
          {preview ? (
            <PremiumCard className="space-y-3 p-4">
              <div className="grid gap-2 text-sm sm:grid-cols-2">
                <p>
                  <span className="text-muted-foreground">Student:</span> {preview.student_name ?? "—"}
                </p>
                <p>
                  <span className="text-muted-foreground">Company:</span> {preview.company ?? "—"}
                </p>
                <p className="sm:col-span-2">
                  <span className="text-muted-foreground">HR:</span> {preview.hr_email ?? "—"}
                </p>
              </div>
              <div className="rounded-lg border bg-muted/40 p-3">
                <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap font-sans text-sm">
                  {cleanMessage(String(preview.reply_message ?? "")) || "—"}
                </pre>
              </div>
            </PremiumCard>
          ) : null}
        </DialogContent>
      </Dialog>
    </PageLayout>
  );
}

