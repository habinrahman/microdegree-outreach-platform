import { useMemo, useState, useCallback, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Download, GraduationCap, MailCheck, Users } from "lucide-react";

import { PageLayout } from "@/components/PageLayout";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { FilterBar, FilterField } from "@/components/FilterBar";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  createStudent,
  deactivateStudent,
  getStudentTemplates,
  listStudents,
  putStudentTemplates,
  startGmailOAuth,
  type StudentTemplateBundle,
  type TemplateType,
  updateStudent,
} from "@/api/students";
import { StatusBadge, type StatusTone } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";

type StudentRow = {
  id: string;
  name: string;
  gmail_address: string;
  domain?: string | null;
  gmail_connected?: boolean;
  connection_type?: string | null;
  status?: string;
};

const TEMPLATE_SUBJECT_MAX = 300;
const TEMPLATE_BODY_MAX = 10_000;

function downloadCsv(filename: string, rows: StudentRow[]) {
  const headers = ["id", "name", "gmail_address", "domain", "gmail_connected", "status"];
  const esc = (v: unknown) => {
    const s = String(v ?? "");
    if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const lines = [headers.join(",")];
  for (const r of rows) {
    lines.push(
      [r.id, r.name, r.gmail_address, r.domain ?? "", r.gmail_connected ? "true" : "false", r.status ?? ""]
        .map(esc)
        .join(",")
    );
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

const cardMotion = {
  initial: { opacity: 0, y: 10 },
  animate: { opacity: 1, y: 0 },
};

const DOMAIN_PLACEHOLDER = "__pick_domain__";

type RosterStatusFilter = "active" | "inactive" | "all";

function rosterStatusTone(status: string | undefined): StatusTone {
  const s = (status ?? "active").toLowerCase();
  if (s === "active") return "success";
  if (s === "inactive") return "neutral";
  return "neutral";
}

function gmailTone(r: StudentRow): { cls: string; label: string } {
  const connected = Boolean(r.gmail_connected);
  const ct = String(r.connection_type ?? "").trim().toLowerCase();
  if (!connected) {
    return {
      cls: "border-border bg-muted/40 text-muted-foreground",
      label: "Not connected",
    };
  }
  if (ct === "oauth") {
    return {
      cls: "border-emerald-500/35 bg-emerald-500/15 text-emerald-800 dark:text-emerald-300",
      label: "Connected (OAuth)",
    };
  }
  if (ct === "smtp") {
    return {
      cls: "border-sky-500/35 bg-sky-500/15 text-sky-800 dark:text-sky-300",
      label: "Connected (SMTP)",
    };
  }
  return {
    cls: "border-emerald-500/35 bg-emerald-500/15 text-emerald-800 dark:text-emerald-300",
    label: "Connected",
  };
}

export default function Students() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [domain, setDomain] = useState("");
  const [resume, setResume] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<RosterStatusFilter>("active");

  const [tplOpen, setTplOpen] = useState(false);
  const [tplStudent, setTplStudent] = useState<StudentRow | null>(null);
  const [tplDraft, setTplDraft] = useState<Partial<Record<TemplateType, { subject: string; body: string }>>>({});
  const [tplDirty, setTplDirty] = useState(false);
  const [tplPreviewOpen, setTplPreviewOpen] = useState<Partial<Record<TemplateType, boolean>>>({});
  const [tplIfMatch, setTplIfMatch] = useState<Partial<Record<TemplateType, string | null>>>({});

  const templateTypes: TemplateType[] = ["INITIAL", "FOLLOWUP_1", "FOLLOWUP_2", "FOLLOWUP_3"];

  const templateTitle: Record<TemplateType, string> = {
    INITIAL: "Initial Outreach",
    FOLLOWUP_1: "Follow‑Up 1",
    FOLLOWUP_2: "Follow‑Up 2",
    FOLLOWUP_3: "Follow‑Up 3",
  };

  const openTemplatesFor = useCallback(
    (r: StudentRow) => {
      const switching = tplOpen && tplStudent?.id && tplStudent.id !== r.id;
      if (switching && tplDirty) {
        const ok = window.confirm("Discard unsaved template changes?");
        if (!ok) return;
      }
      setTplStudent(r);
      setTplDraft({});
      setTplDirty(false);
      setTplPreviewOpen({});
      setTplIfMatch({});
      setTplOpen(true);
    },
    [tplDirty, tplOpen, tplStudent?.id]
  );

  const renderPreview = useCallback(
    (text: string) => {
      const name = String(tplStudent?.name ?? "").trim();
      const domain = String(tplStudent?.domain ?? "").trim();
      const course = domain; // placeholder mapping (safe default until real course field exists)
      return String(text ?? "")
        .split("{{student_name}}")
        .join(name || "Student")
        .split("{{domain}}")
        .join(domain || "Domain")
        .split("{{course}}")
        .join(course || "Course");
    },
    [tplStudent?.domain, tplStudent?.name]
  );

  const listQ = useQuery({
    queryKey: ["students"],
    queryFn: () => listStudents({ include_demo: false }) as Promise<StudentRow[]>,
  });

  const templatesQ = useQuery({
    queryKey: ["students", tplStudent?.id, "templates"],
    enabled: tplOpen && Boolean(tplStudent?.id),
    queryFn: () => getStudentTemplates(String(tplStudent?.id)),
  });

  useEffect(() => {
    if (!tplOpen) return;
    const bundle = (templatesQ.data ?? null) as StudentTemplateBundle | null;
    if (!bundle) return;
    setTplIfMatch({
      INITIAL: bundle.INITIAL?.updated_at || bundle.INITIAL?.created_at || null,
      FOLLOWUP_1: bundle.FOLLOWUP_1?.updated_at || bundle.FOLLOWUP_1?.created_at || null,
      FOLLOWUP_2: bundle.FOLLOWUP_2?.updated_at || bundle.FOLLOWUP_2?.created_at || null,
      FOLLOWUP_3: bundle.FOLLOWUP_3?.updated_at || bundle.FOLLOWUP_3?.created_at || null,
    });
  }, [tplOpen, templatesQ.data]);

  const delM = useMutation({
    mutationFn: (id: string) => deactivateStudent(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["students"] });
      toast.success("Student deactivated");
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Deactivate failed");
    },
  });

  const reactM = useMutation({
    mutationFn: (id: string) => updateStudent(id, { status: "active" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["students"] });
      toast.success("Student reactivated");
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Reactivate failed");
    },
  });

  const oauthM = useMutation({
    mutationFn: async (studentId: string) => {
      const { auth_url } = await startGmailOAuth(studentId);
      window.location.assign(auth_url);
      return true;
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Failed to start Gmail connection");
    },
  });

  const saveTplM = useMutation({
    mutationFn: async (args: { studentId: string; patch: Partial<Record<TemplateType, { subject: string; body: string } | null>> }) =>
      putStudentTemplates(args.studentId, args.patch),
    onSuccess: (data, vars) => {
      qc.setQueryData(["students", vars.studentId, "templates"], data);
      setTplDirty(false);
      setTplIfMatch({
        INITIAL: data.INITIAL?.updated_at || data.INITIAL?.created_at || null,
        FOLLOWUP_1: data.FOLLOWUP_1?.updated_at || data.FOLLOWUP_1?.created_at || null,
        FOLLOWUP_2: data.FOLLOWUP_2?.updated_at || data.FOLLOWUP_2?.created_at || null,
        FOLLOWUP_3: data.FOLLOWUP_3?.updated_at || data.FOLLOWUP_3?.created_at || null,
      });
      toast.success("Templates saved");
    },
    onError: (e: unknown) => {
      const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Save templates failed");
    },
  });

  const allRows = (listQ.data || []) as StudentRow[];
  const rosterRows = useMemo(() => {
    if (statusFilter === "all") return allRows;
    if (statusFilter === "inactive") {
      return allRows.filter((r) => (r.status ?? "").toLowerCase() === "inactive");
    }
    return allRows.filter((r) => (r.status ?? "active").toLowerCase() !== "inactive");
  }, [allRows, statusFilter]);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rosterRows;
    return rosterRows.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.gmail_address.toLowerCase().includes(q) ||
        String(r.domain ?? "")
          .toLowerCase()
          .includes(q)
    );
  }, [rosterRows, search]);

  const stats = useMemo(() => {
    const total = rosterRows.length;
    const connected = rosterRows.filter((r) => r.gmail_connected).length;
    const domains = new Set(rosterRows.map((r) => r.domain).filter(Boolean)).size;
    return { total, connected, domains };
  }, [rosterRows]);

  const filterChipClass = useCallback((value: RosterStatusFilter) => {
    const on = statusFilter === value;
    return cn(
      "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
      on
        ? "border-primary bg-primary/10 text-primary"
        : "border-border bg-background text-muted-foreground hover:bg-muted/60"
    );
  }, [statusFilter]);

  const onAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!domain.trim() || domain === DOMAIN_PLACEHOLDER) {
      toast.error("Select a domain");
      return;
    }
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("name", name);
      fd.append("email", email);
      fd.append("app_password", password);
      fd.append("domain", domain);
      if (resume) fd.append("resume", resume);
      await createStudent(fd);
      toast.success("Student added");
      setOpen(false);
      setName("");
      setEmail("");
      setPassword("");
      setDomain("");
      setResume(null);
      qc.invalidateQueries({ queryKey: ["students"] });
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Add failed");
    } finally {
      setSubmitting(false);
    }
  };

  const columns: ColumnDef<StudentRow>[] = useMemo(
    () => [
      { id: "name", header: "Name", cell: (r) => r.name },
      { id: "email", header: "Email", cell: (r) => r.gmail_address },
      { id: "domain", header: "Domain", cell: (r) => r.domain ?? "—" },
      {
        id: "gmail",
        header: "Gmail",
        cell: (r) => {
          const t = gmailTone(r);
          return (
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium", t.cls)}>
                {t.label}
              </span>
              {!r.gmail_connected ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  disabled={oauthM.isPending}
                  onClick={() => oauthM.mutate(r.id)}
                >
                  {oauthM.isPending ? "Connecting…" : "Connect Gmail"}
                </Button>
              ) : null}
            </div>
          );
        },
      },
      {
        id: "status",
        header: "Status",
        cell: (r) => {
          const raw = (r.status ?? "active").trim() || "active";
          const label = raw.charAt(0).toUpperCase() + raw.slice(1).toLowerCase();
          return (
            <StatusBadge tone={rosterStatusTone(r.status)} raw={raw}>
              {label}
            </StatusBadge>
          );
        },
      },
      {
        id: "actions",
        header: "",
        cell: (r) => {
          const inactive = (r.status ?? "").toLowerCase() === "inactive";
          if (inactive) {
            return (
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-8"
                  onClick={() => {
                    openTemplatesFor(r);
                  }}
                >
                  Templates
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-8 border-emerald-500/40 text-emerald-800 transition-all duration-300 hover:bg-emerald-500/10 dark:text-emerald-300"
                  disabled={reactM.isPending}
                  onClick={() => reactM.mutate(r.id)}
                >
                  Reactivate
                </Button>
              </div>
            );
          }
          return (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8"
                onClick={() => {
                  openTemplatesFor(r);
                }}
              >
                Templates
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 transition-all duration-300"
                disabled={delM.isPending}
                onClick={() => {
                  if (
                    window.confirm(
                      `Deactivate “${r.name}”?\n\nThis sets status to inactive. Campaigns, replies, and analytics stay in the database. Use the Inactive chip to find this row again, or All.`
                    )
                  ) {
                    delM.mutate(r.id);
                  }
                }}
              >
                Deactivate
              </Button>
            </div>
          );
        },
      },
    ],
    [delM, reactM, oauthM]
  );

  return (
    <PageLayout
      title="Students"
      subtitle="GET /students · PUT to reactivate · Deactivate = soft delete (inactive, data kept)"
      actions={
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-1.5 transition-all duration-300"
            disabled={!rosterRows.length}
            onClick={() => downloadCsv(`students-${new Date().toISOString().slice(0, 10)}.csv`, rosterRows)}
          >
            <Download className="h-4 w-4" />
            Export CSV
          </Button>
          <Button type="button" size="sm" className="transition-all duration-300" onClick={() => setOpen(true)}>
            Add student
          </Button>
        </div>
      }
      filters={
        <FilterBar>
          <FilterField label="Search">
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name, email, domain…" />
          </FilterField>
          <FilterField label="Roster">
            <div className="flex flex-wrap gap-2">
              {(
                [
                  { value: "active" as const, label: "Active" },
                  { value: "inactive" as const, label: "Inactive" },
                  { value: "all" as const, label: "All" },
                ] as const
              ).map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  className={filterChipClass(value)}
                  onClick={() => setStatusFilter(value)}
                >
                  {label}
                </button>
              ))}
            </div>
          </FilterField>
        </FilterBar>
      }
    >
      <Dialog
        open={tplOpen}
        onOpenChange={(next) => {
          if (!next && tplDirty) {
            const ok = window.confirm("You have unsaved template changes. Discard them?");
            if (!ok) return;
          }
          if (!next) {
            setTplStudent(null);
            setTplDraft({});
            setTplDirty(false);
            setTplPreviewOpen({});
            setTplIfMatch({});
          } else if (tplStudent?.id) {
            // When opening, hydrate draft from server once loaded
            // (templatesQ will run due to enabled=true).
          }
          setTplOpen(next);
        }}
      >
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto sm:rounded-xl">
          <DialogHeader>
            <DialogTitle className="text-lg font-semibold">Personalized Email Templates</DialogTitle>
            <DialogDescription className="text-sm text-muted-foreground">
              {tplStudent ? `${tplStudent.name} · ${tplStudent.gmail_address}` : "Load templates…"}
            </DialogDescription>
          </DialogHeader>

          {templatesQ.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading templates…</p>
          ) : templatesQ.isError ? (
            <p className="text-sm text-destructive">Failed to load templates.</p>
          ) : (
            (() => {
              const bundle = (templatesQ.data ?? null) as StudentTemplateBundle | null;
              const getVal = (tt: TemplateType) => {
                const fromDraft = tplDraft[tt];
                if (fromDraft) return fromDraft;
                const t = bundle?.[tt];
                return t ? { subject: t.subject, body: t.body } : { subject: "", body: "" };
              };
              const configured = templateTypes.filter((tt) => {
                const v = getVal(tt);
                return v.subject.trim() && v.body.trim();
              }).length;

              return (
                <div className="space-y-5">
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card/40 p-4">
                    <div>
                      <p className="text-sm font-semibold text-foreground">Template completeness</p>
                      <p className="text-xs text-muted-foreground">
                        {configured}/{templateTypes.length} configured · follow-ups can be added later
                      </p>
                    </div>
                    <StatusBadge raw={configured === 4 ? "healthy" : "warning"}>
                      {configured}/{templateTypes.length}
                    </StatusBadge>
                  </div>

                  {templateTypes.map((tt) => {
                    const v = getVal(tt);
                    const has = v.subject.trim() && v.body.trim();
                    const savingThis = saveTplM.isPending;
                    const subjTrim = v.subject.trim();
                    const bodyTrim = v.body.trim();
                    const subjTooLong = subjTrim.length > TEMPLATE_SUBJECT_MAX;
                    const bodyTooLong = bodyTrim.length > TEMPLATE_BODY_MAX;
                    const previewOn = tplPreviewOpen[tt] === true;
                    return (
                      <div key={tt} className="rounded-xl border bg-card/40 p-4 space-y-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold">{templateTitle[tt]}</p>
                            <p className="text-xs text-muted-foreground">
                              {has ? "Configured" : "Not configured"} · {tt}
                            </p>
                          </div>
                          <StatusBadge raw={has ? "healthy" : "inactive"}>{has ? "Ready" : "Missing"}</StatusBadge>
                        </div>

                        <div className="grid gap-3">
                          <div className="grid gap-1.5">
                            <Label>Subject</Label>
                            <Input
                              value={v.subject}
                              maxLength={TEMPLATE_SUBJECT_MAX}
                              onChange={(e) => {
                                const subject = e.target.value;
                                setTplDraft((prev) => ({ ...prev, [tt]: { ...(prev[tt] ?? v), subject } }));
                                setTplDirty(true);
                              }}
                              placeholder="Subject…"
                            />
                            <p className={cn("text-xs", subjTooLong ? "text-destructive" : "text-muted-foreground")}>
                              {subjTrim.length}/{TEMPLATE_SUBJECT_MAX}
                            </p>
                          </div>
                          <div className="grid gap-1.5">
                            <Label>Body</Label>
                            <Textarea
                              value={v.body}
                              maxLength={TEMPLATE_BODY_MAX}
                              onChange={(e) => {
                                const body = e.target.value;
                                setTplDraft((prev) => ({ ...prev, [tt]: { ...(prev[tt] ?? v), body } }));
                                setTplDirty(true);
                              }}
                              placeholder="Write the email body…"
                              className="min-h-[140px]"
                            />
                            <p className="text-xs text-muted-foreground">Saved as plain text. Follow-ups are storage only (no sending yet).</p>
                            <p className={cn("text-xs", bodyTooLong ? "text-destructive" : "text-muted-foreground")}>
                              {bodyTrim.length}/{TEMPLATE_BODY_MAX}
                            </p>
                          </div>
                        </div>

                        <div className="flex flex-wrap gap-2">
                          <Button
                            type="button"
                            size="sm"
                            disabled={!tplStudent?.id || savingThis}
                            onClick={() => {
                              if (!tplStudent?.id) return;
                              const cur = getVal(tt);
                              const subject = cur.subject.trim();
                              const body = cur.body.trim();
                              if (!subject || !body) {
                                toast.error("Subject and body are required");
                                return;
                              }
                              if (subject.length > TEMPLATE_SUBJECT_MAX) {
                                toast.error(`Subject too long (max ${TEMPLATE_SUBJECT_MAX})`);
                                return;
                              }
                              if (body.length > TEMPLATE_BODY_MAX) {
                                toast.error(`Body too long (max ${TEMPLATE_BODY_MAX})`);
                                return;
                              }
                              const patch: any = {
                                [tt]: { subject, body },
                              };
                              const ifMatch = (tplIfMatch?.[tt] ?? null) as string | null;
                              if (ifMatch) patch[tt].if_match = ifMatch;
                              saveTplM.mutate({ studentId: tplStudent.id, patch });
                            }}
                          >
                            {savingThis ? "Saving…" : "Save"}
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => setTplPreviewOpen((p) => ({ ...p, [tt]: !previewOn }))}
                          >
                            {previewOn ? "Hide preview" : "Preview"}
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={savingThis}
                            onClick={() => {
                              setTplDraft((prev) => {
                                const next = { ...prev };
                                delete next[tt];
                                return next;
                              });
                              setTplDirty(true);
                            }}
                          >
                            Reset
                          </Button>
                        </div>

                        {previewOn ? (
                          <div className="rounded-lg border bg-muted/20 p-3 space-y-2">
                            <p className="text-xs font-medium text-muted-foreground">Preview (placeholders only)</p>
                            <div className="text-xs">
                              <p className="font-medium text-muted-foreground">Subject</p>
                              <p className="rounded-md border bg-background/60 p-2">{renderPreview(v.subject)}</p>
                            </div>
                            <div className="text-xs">
                              <p className="font-medium text-muted-foreground">Body</p>
                              <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md border bg-background/60 p-2">
                                {renderPreview(v.body)}
                              </pre>
                            </div>
                            <p className="text-[11px] text-muted-foreground">
                              Supported: {"{{student_name}}"}, {"{{domain}}"}, {"{{course}}"} (course maps to domain for
                              now)
                            </p>
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              );
            })()
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.2 }}>
            <DialogHeader>
              <DialogTitle className="text-lg font-semibold">Add student</DialogTitle>
              <DialogDescription className="text-sm text-gray-500">POST /students (multipart form)</DialogDescription>
            </DialogHeader>
            <form className="space-y-4" onSubmit={onAdd}>
              <div>
                <Label htmlFor="sn">Name</Label>
                <Input id="sn" value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
              <div>
                <Label htmlFor="se">Email</Label>
                <Input id="se" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </div>
              <div>
                <Label htmlFor="sp">Gmail app password</Label>
                <Input id="sp" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              </div>
              <div>
                <Label htmlFor="sd">Domain</Label>
                <Select
                  value={domain || DOMAIN_PLACEHOLDER}
                  onValueChange={(v) => setDomain(v === DOMAIN_PLACEHOLDER ? "" : v)}
                >
                  <SelectTrigger id="sd" className="h-10 w-full text-sm">
                    <SelectValue placeholder="Select domain" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DOMAIN_PLACEHOLDER} disabled>
                      Select
                    </SelectItem>
                    <SelectItem value="Backend">Backend</SelectItem>
                    <SelectItem value="Data">Data</SelectItem>
                    <SelectItem value="Cloud">Cloud</SelectItem>
                    <SelectItem value="DevOps">DevOps</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label htmlFor="sr">Resume</Label>
                <Input id="sr" type="file" accept=".pdf,.doc,.docx" onChange={(e) => setResume(e.target.files?.[0] ?? null)} />
              </div>
              <Button type="submit" disabled={submitting} className="w-full">
                {submitting ? "Saving…" : "Save"}
              </Button>
            </form>
          </motion.div>
        </DialogContent>
      </Dialog>

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <motion.div {...cardMotion} transition={{ delay: 0 }}>
          <PremiumCard className="p-4">
            <div className="flex items-center justify-between">
              <p className="text-lg font-semibold">Total students</p>
              <Users className="h-5 w-5 text-[#4F46E5]" />
            </div>
            <p className="mt-2 text-3xl font-bold tabular-nums">{listQ.isLoading ? "…" : stats.total}</p>
            <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">
              {statusFilter === "all"
                ? "All statuses"
                : statusFilter === "inactive"
                  ? "Inactive only"
                  : "Active roster"}
            </p>
          </PremiumCard>
        </motion.div>
        <motion.div {...cardMotion} transition={{ delay: 0.05 }}>
          <PremiumCard className="p-4">
            <div className="flex items-center justify-between">
              <p className="text-lg font-semibold">Gmail connected</p>
              <MailCheck className="h-5 w-5 text-[#22C55E]" />
            </div>
            <p className="mt-2 text-3xl font-bold tabular-nums">{listQ.isLoading ? "…" : stats.connected}</p>
            <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">OAuth / app-password ready</p>
          </PremiumCard>
        </motion.div>
        <motion.div {...cardMotion} transition={{ delay: 0.1 }}>
          <PremiumCard className="p-4">
            <div className="flex items-center justify-between">
              <p className="text-lg font-semibold">Unique domains</p>
              <GraduationCap className="h-5 w-5 text-[#3B82F6]" />
            </div>
            <p className="mt-2 text-3xl font-bold tabular-nums">{listQ.isLoading ? "…" : stats.domains}</p>
            <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">Track placement focus areas</p>
          </PremiumCard>
        </motion.div>
      </div>

      {listQ.isError ? (
        <p className="mb-4 text-sm text-destructive">Unable to load students. Check the API.</p>
      ) : null}

      {listQ.isLoading ? null : (
        <p className="mb-2 text-xs text-muted-foreground">
          Showing {rows.length.toLocaleString()} of {rosterRows.length.toLocaleString()} in roster
          {statusFilter === "active" ? " (active only)." : statusFilter === "inactive" ? " (inactive only)." : " (all statuses)."}
          {search.trim() ? " Search narrows the table below." : ""}
        </p>
      )}

      <DataTable<StudentRow>
        columns={columns}
        data={rows}
        getRowKey={(r) => r.id}
        loading={listQ.isLoading}
        emptyMessage={listQ.isError ? "Failed to load." : "No students."}
      />
    </PageLayout>
  );
}
