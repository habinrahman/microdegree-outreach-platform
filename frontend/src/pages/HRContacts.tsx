import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Inbox, Upload } from "lucide-react";
import { PageLayout } from "@/components/PageLayout";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { FilterBar, FilterField } from "@/components/FilterBar";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { createAssignments, sendOutreach } from "@/api/api";
import { listStudents } from "@/api/students";
import {
  fetchHrHealthDetail,
  listHrContacts,
  uploadHrContactsCsv,
  type HrContactRow,
  type HrHealthDetail,
} from "@/api/hrContacts";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { API_LIST_LIMITS, TABLE_PAGE_SIZE } from "@/lib/constants";
import { ListPagination } from "@/components/ListPagination";
import { EmptyState } from "@/components/EmptyState";
import { cn } from "@/lib/utils";
import { HrBulkSendModal, type HrBulkSendPayload } from "@/components/HrBulkSendModal";

type StudentOpt = { id: string; name: string; status?: string };

const SEL_NO_STUDENT = "__none__";

function tierBadgeClass(t?: string) {
  const u = (t || "?").toUpperCase();
  if (u === "A") return "bg-emerald-600/15 text-emerald-800 dark:text-emerald-300 border-emerald-500/30";
  if (u === "B") return "bg-sky-600/15 text-sky-800 dark:text-sky-300 border-sky-500/30";
  if (u === "C") return "bg-amber-600/15 text-amber-900 dark:text-amber-200 border-amber-500/30";
  if (u === "D") return "bg-rose-600/15 text-rose-900 dark:text-rose-200 border-rose-500/30";
  return "bg-muted text-muted-foreground";
}

function apiDetail(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const d = e.response?.data as { detail?: unknown } | undefined;
    if (d?.detail != null) return typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail);
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export default function HRContacts() {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [hideInvalid, setHideInvalid] = useState(true);
  const [selectedStudentId, setSelectedStudentId] = useState("");
  const [selectedHRIds, setSelectedHRIds] = useState<Set<string>>(() => new Set());
  const [sendModalOpen, setSendModalOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [bulkProgress, setBulkProgress] = useState<{ current: number; total: number } | null>(null);
  const [hrPage, setHrPage] = useState(1);
  const [dragOver, setDragOver] = useState(false);
  const [tierFilter, setTierFilter] = useState<string>("all");
  const [healthDialogOpen, setHealthDialogOpen] = useState(false);
  const [healthDetail, setHealthDetail] = useState<HrHealthDetail | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);

  const studentsQ = useQuery({
    queryKey: ["students", "hr-page"],
    queryFn: () => listStudents({ include_demo: false }) as Promise<StudentOpt[]>,
  });

  const listQ = useQuery({
    queryKey: ["hr-contacts", tierFilter],
    queryFn: () =>
      listHrContacts({
        limit: API_LIST_LIMITS.hrContacts,
        includeHealth: true,
        tier: tierFilter === "all" ? undefined : tierFilter,
      }),
  });

  const upM = useMutation({
    mutationFn: (fd: FormData) => uploadHrContactsCsv(fd),
    onSuccess: () => {
      toast.success("Upload complete");
      setFile(null);
      qc.invalidateQueries({ queryKey: ["hr-contacts"] });
    },
    onError: (e: unknown) => {
      toast.error(apiDetail(e) || "Upload failed");
    },
  });

  useEffect(() => {
    setHrPage(1);
  }, [hideInvalid, tierFilter]);

  const raw = (listQ.data || []) as HrContactRow[];
  const rows = useMemo(
    () =>
      hideInvalid
        ? raw.filter((r) => r.is_valid && String(r.status).toLowerCase() !== "invalid")
        : raw,
    [raw, hideInvalid]
  );

  const totalHrPages = Math.max(1, Math.ceil(rows.length / TABLE_PAGE_SIZE));
  const pagedRows = useMemo(() => {
    const start = (hrPage - 1) * TABLE_PAGE_SIZE;
    return rows.slice(start, start + TABLE_PAGE_SIZE);
  }, [rows, hrPage]);

  useEffect(() => {
    if (hrPage > totalHrPages) setHrPage(totalHrPages);
  }, [hrPage, totalHrPages]);

  const students = useMemo(
    () => ((studentsQ.data || []) as StudentOpt[]).filter((s) => s.status !== "inactive"),
    [studentsQ.data]
  );

  const allSelected = pagedRows.length > 0 && pagedRows.every((r) => selectedHRIds.has(r.id));
  const someSelected = pagedRows.some((r) => selectedHRIds.has(r.id));

  const toggleRow = useCallback((id: string) => {
    setSelectedHRIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const setSelectAllVisible = useCallback((on: boolean) => {
    if (pagedRows.length === 0) return;
    if (!on) {
      setSelectedHRIds(new Set());
      return;
    }
    setSelectedHRIds(new Set(pagedRows.map((r) => r.id)));
  }, [pagedRows]);

  const clearSelection = useCallback(() => setSelectedHRIds(new Set()), []);

  const openSendModal = () => {
    if (!selectedStudentId) {
      toast.error("Select a student first");
      return;
    }
    if (selectedHRIds.size === 0) {
      toast.error("Select at least one HR contact");
      return;
    }
    setSendModalOpen(true);
  };

  const runBulkSend = async (payload: HrBulkSendPayload) => {
    const sid = selectedStudentId;
    const ids = Array.from(selectedHRIds);
    const subj = payload.subject.trim() || null;
    const bod = payload.body.trim() || null;
    const template = payload.template_label;

    setSending(true);
    setBulkProgress({ current: 0, total: ids.length });
    try {
      try {
        await createAssignments({ student_id: sid, hr_ids: ids });
      } catch (e) {
        toast.warning(`Assignments: ${apiDetail(e)} — continuing with sends.`);
      }

      let ok = 0;
      const failures: { email: string; message: string }[] = [];

      for (let i = 0; i < ids.length; i++) {
        const hrId = ids[i];
        setBulkProgress({ current: i + 1, total: ids.length });
        const hr = raw.find((r) => r.id === hrId);
        const email = hr?.email?.trim();
        if (!email) {
          failures.push({ email: hrId, message: "Missing HR email for selected row" });
          continue;
        }

        const attemptSend = async () => {
          await sendOutreach({
            student_id: sid,
            hr_email: email,
            template_label: template,
            subject: subj,
            body: bod,
          });
        };

        try {
          await attemptSend();
          ok += 1;
        } catch (e) {
          const msg = apiDetail(e);
          const needsAssign = msg.toLowerCase().includes("assignment");
          if (needsAssign) {
            try {
              await createAssignments({ student_id: sid, hr_ids: [hrId] });
              await attemptSend();
              ok += 1;
            } catch (e2) {
              failures.push({ email, message: apiDetail(e2) });
            }
          } else {
            failures.push({ email, message: msg });
          }
        }
      }

      const failed = failures.length;
      if (failed === 0) {
        toast.success(`Bulk send complete: sent ${ok.toLocaleString()} / ${ids.length.toLocaleString()}.`);
      } else {
        const preview = failures
          .slice(0, 3)
          .map((f) => `${f.email}: ${f.message}`)
          .join("; ");
        toast.error(
          `Bulk send complete: sent ${ok.toLocaleString()}, failed ${failed.toLocaleString()}. ${preview}${
            failed > 3 ? "…" : ""
          }`,
          { duration: 9000 }
        );
      }

      setSendModalOpen(false);
      clearSelection();
      qc.invalidateQueries({ queryKey: ["hr-contacts"] });
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      qc.invalidateQueries({ queryKey: ["assignments"] });
    } finally {
      setSending(false);
      setBulkProgress(null);
    }
  };

  const openHealthDetail = useCallback(async (hrId: string) => {
    setHealthDialogOpen(true);
    setHealthLoading(true);
    setHealthDetail(null);
    try {
      const d = await fetchHrHealthDetail(hrId);
      setHealthDetail(d);
    } catch (e) {
      toast.error(apiDetail(e) || "Failed to load HR health");
      setHealthDialogOpen(false);
    } finally {
      setHealthLoading(false);
    }
  }, []);

  const columns: ColumnDef<HrContactRow>[] = useMemo(
    () => [
      {
        id: "sel",
        header: (
          <Checkbox
            checked={allSelected ? true : someSelected ? "indeterminate" : false}
            onCheckedChange={(v) => setSelectAllVisible(v === true)}
            disabled={pagedRows.length === 0}
            aria-label="Select all visible"
          />
        ),
        className: "w-10",
        cell: (r) => (
          <Checkbox
            checked={selectedHRIds.has(r.id)}
            onCheckedChange={() => toggleRow(r.id)}
            aria-label={`Select ${r.email}`}
          />
        ),
      },
      { id: "company", header: "Company", cell: (r) => r.company },
      { id: "name", header: "Name", cell: (r) => r.name },
      { id: "email", header: "Email", cell: (r) => r.email },
      {
        id: "domain",
        header: "Domain",
        cell: (r) =>
          r.domain ? (
            <Badge variant="secondary" className="font-normal">
              {r.domain}
            </Badge>
          ) : (
            "—"
          ),
      },
      {
        id: "valid",
        header: "Valid",
        cell: (r) => (
          <StatusBadge raw={r.is_valid ? "sent" : "failed"}>{r.is_valid ? "Yes" : "No"}</StatusBadge>
        ),
      },
      {
        id: "status",
        header: "Status",
        cell: (r) => <StatusBadge raw={r.status}>{r.status}</StatusBadge>,
      },
      {
        id: "tier",
        header: "Tier",
        cell: (r) => (
          <Badge variant="outline" className={cn("font-semibold", tierBadgeClass(r.tier))}>
            {r.tier ?? "—"}
          </Badge>
        ),
      },
      {
        id: "health",
        header: "Health",
        className: "text-right tabular-nums",
        cell: (r) => (r.health_score != null ? Math.round(r.health_score) : "—"),
      },
      {
        id: "opp",
        header: "Opportunity",
        className: "text-right tabular-nums",
        cell: (r) => (r.opportunity_score != null ? Math.round(r.opportunity_score) : "—"),
      },
      {
        id: "explain",
        header: "",
        cell: (r) => (
          <Button type="button" variant="ghost" size="sm" className="h-8 px-2" onClick={() => openHealthDetail(r.id)}>
            Scores
          </Button>
        ),
      },
    ],
    [allSelected, pagedRows.length, selectedHRIds, someSelected, toggleRow, setSelectAllVisible, openHealthDetail]
  );

  return (
    <PageLayout
      title="HR Contacts"
      subtitle="GET /hr-contacts · assignments · POST /outreach/send (bulk)"
      filters={
        <FilterBar>
          <FilterField label="Student">
            <Select
              value={selectedStudentId || SEL_NO_STUDENT}
              onValueChange={(v) => setSelectedStudentId(v === SEL_NO_STUDENT ? "" : v)}
              disabled={studentsQ.isLoading}
            >
              <SelectTrigger className="h-10 min-w-[220px] text-sm" aria-label="Student">
                <SelectValue placeholder="Select a student" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={SEL_NO_STUDENT}>Select a student</SelectItem>
                {students.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FilterField>
          <FilterField label="CSV upload">
            <PremiumCard
              className={cn(
                "flex min-h-[100px] max-w-md flex-col items-center justify-center gap-2 border-2 border-dashed p-4 transition-all duration-300",
                dragOver ? "border-[#4F46E5] bg-indigo-500/[0.06]" : "border-border/80"
              )}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const f = e.dataTransfer.files?.[0];
                if (f && f.name.toLowerCase().endsWith(".csv")) setFile(f);
                else if (f) toast.error("Please drop a .csv file");
              }}
            >
              <Upload className="h-6 w-6 text-muted-foreground" aria-hidden />
              <p className="text-center text-sm text-gray-500 dark:text-muted-foreground">
                Drag & drop CSV here, or choose a file
              </p>
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Input
                  type="file"
                  accept=".csv"
                  className="max-w-[200px] cursor-pointer"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
                <Button
                  type="button"
                  size="sm"
                  disabled={!file || upM.isPending}
                  onClick={() => {
                    if (!file) return;
                    const fd = new FormData();
                    fd.append("file", file);
                    upM.mutate(fd);
                  }}
                >
                  {upM.isPending ? "Uploading…" : "Upload"}
                </Button>
              </div>
              {file ? <p className="text-xs font-medium text-foreground">{file.name}</p> : null}
            </PremiumCard>
          </FilterField>
          <FilterField label="Tier">
            <Select value={tierFilter} onValueChange={setTierFilter}>
              <SelectTrigger className="h-10 w-[140px] text-sm" aria-label="HR tier filter">
                <SelectValue placeholder="All tiers" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All tiers</SelectItem>
                <SelectItem value="A">A — prioritize</SelectItem>
                <SelectItem value="B">B — good</SelectItem>
                <SelectItem value="C">C — low confidence</SelectItem>
                <SelectItem value="D">D — suppress</SelectItem>
              </SelectContent>
            </Select>
          </FilterField>
          <FilterField label=" ">
            <div className="mt-6 flex items-center gap-2">
              <Checkbox id="hide-invalid" checked={hideInvalid} onCheckedChange={(v) => setHideInvalid(v === true)} />
              <Label htmlFor="hide-invalid" className="cursor-pointer text-sm font-normal">
                Hide invalid
              </Label>
            </div>
          </FilterField>
        </FilterBar>
      }
    >
      {listQ.isError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Backend error — check server logs</AlertTitle>
          <AlertDescription>GET /hr-contacts failed.</AlertDescription>
        </Alert>
      ) : null}

      {studentsQ.isError ? (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Backend error — check server logs</AlertTitle>
          <AlertDescription>GET /students failed.</AlertDescription>
        </Alert>
      ) : null}

      {selectedHRIds.size > 0 ? (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-[#4F46E5]/25 bg-gradient-to-r from-indigo-500/[0.07] to-transparent p-4 shadow-sm transition-all duration-300"
        >
          <span className="text-sm font-semibold">{selectedHRIds.size} HR(s) selected</span>
          <Button
            type="button"
            size="sm"
            onClick={openSendModal}
            disabled={!selectedStudentId || selectedHRIds.size === 0 || sending}
          >
            Send email
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={clearSelection} disabled={sending}>
            Clear selection
          </Button>
        </motion.div>
      ) : null}

      {listQ.isLoading ? null : (
        <p className="mb-2 text-xs text-muted-foreground">
          Showing {pagedRows.length.toLocaleString()} on page {hrPage} of {rows.length.toLocaleString()} in view (
          {raw.length.toLocaleString()} loaded, API limit {API_LIST_LIMITS.hrContacts.toLocaleString()}).
          {hideInvalid ? " Invalid rows are hidden by the filter above." : null}
          {listQ.isSuccess && raw.length >= API_LIST_LIMITS.hrContacts ? (
            <span className="ml-1 font-medium text-amber-700 dark:text-amber-400">
              Additional contacts may exist beyond this cap.
            </span>
          ) : null}
        </p>
      )}

      <DataTable<HrContactRow>
        columns={columns}
        data={listQ.isError ? [] : pagedRows}
        getRowKey={(r) => r.id}
        loading={listQ.isLoading}
        emptyMessage={listQ.isError ? "Request failed." : "No HR contacts."}
        emptyState={
          listQ.isError || listQ.isLoading ? undefined : (
            <EmptyState
              icon={Inbox}
              title="No HR contacts in view"
              description="Upload a CSV or turn off “Hide invalid” if everything was filtered out."
            >
              <Button type="button" variant="default" size="sm" asChild>
                <Link to="/students">Students</Link>
              </Button>
            </EmptyState>
          )
        }
      />

      {listQ.isLoading ? null : (
        <div className="mt-3">
          <ListPagination
            page={hrPage}
            totalPages={totalHrPages}
            hasNext={hrPage < totalHrPages}
            hasPrev={hrPage > 1}
            pageSize={TABLE_PAGE_SIZE}
            onPageChange={setHrPage}
          />
        </div>
      )}

      <HrBulkSendModal
        open={sendModalOpen}
        onOpenChange={setSendModalOpen}
        onSend={runBulkSend}
        loading={sending}
        selectedCount={selectedHRIds.size}
        sendProgress={bulkProgress}
      />

      <Dialog open={healthDialogOpen} onOpenChange={setHealthDialogOpen}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>HR targeting scores</DialogTitle>
            <DialogDescription>
              Health = deliverability / list hygiene. Opportunity = responsiveness and upside. Tier combines both with
              suppress rules.
            </DialogDescription>
          </DialogHeader>
          {healthLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : healthDetail ? (
            <div className="space-y-4 text-sm">
              <div>
                <p className="font-medium text-foreground">
                  {healthDetail.name} · {healthDetail.company}
                </p>
                <p className="text-muted-foreground">{healthDetail.email}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge className={cn("font-semibold", tierBadgeClass(healthDetail.tier))}>Tier {healthDetail.tier}</Badge>
                <Badge variant="secondary">Health {Math.round(healthDetail.health_score ?? 0)}</Badge>
                <Badge variant="secondary">Opportunity {Math.round(healthDetail.opportunity_score ?? 0)}</Badge>
              </div>
              <div>
                <p className="mb-1 font-semibold text-foreground">Health factors</p>
                <ul className="list-inside list-disc space-y-1 text-muted-foreground">
                  {(healthDetail.health_reasons || []).map((x) => (
                    <li key={x.code}>{x.label}</li>
                  ))}
                  {(healthDetail.health_reasons || []).length === 0 ? <li>No negative health flags</li> : null}
                </ul>
              </div>
              <div>
                <p className="mb-1 font-semibold text-foreground">Opportunity factors</p>
                <ul className="list-inside list-disc space-y-1 text-muted-foreground">
                  {(healthDetail.opportunity_reasons || []).map((x) => (
                    <li key={x.code}>{x.label}</li>
                  ))}
                </ul>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </PageLayout>
  );
}
