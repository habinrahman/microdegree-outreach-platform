import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Eye, Send } from "lucide-react";

import { PageLayout } from "@/components/PageLayout";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { FilterBar, FilterField } from "@/components/FilterBar";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { createAssignments, sendOutreach } from "@/api/api";
import { listStudents } from "@/api/students";
import { listHrContacts, type HrContactRow } from "@/api/hrContacts";

type Stu = { id: string; name: string; status?: string };

const SEL_NONE = "__none__";
const TPL_DEFAULT = "__default__";

export default function Outreach() {
  const qc = useQueryClient();
  const [studentId, setStudentId] = useState("");
  const [hrId, setHrId] = useState("");
  const [hrSearch, setHrSearch] = useState("");
  const [templateLabel, setTemplateLabel] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const studentsQ = useQuery({
    queryKey: ["students", "outreach"],
    queryFn: () => listStudents({ include_demo: false }) as Promise<Stu[]>,
  });

  const hrsQ = useQuery({
    queryKey: ["hr-contacts", "outreach"],
    queryFn: () => listHrContacts({ limit: 8000 }),
  });

  const students = useMemo(
    () => ((studentsQ.data || []) as Stu[]).filter((s) => s.status !== "inactive"),
    [studentsQ.data]
  );

  const filteredHrs = useMemo(() => {
    const q = hrSearch.trim().toLowerCase();
    const all = (hrsQ.data || []) as HrContactRow[];
    if (!q) return all;
    return all.filter(
      (h) =>
        String(h.email ?? "")
          .toLowerCase()
          .includes(q) ||
        String(h.name ?? "")
          .toLowerCase()
          .includes(q) ||
        String(h.company ?? "")
          .toLowerCase()
          .includes(q)
    );
  }, [hrsQ.data, hrSearch]);

  const selectedHr = useMemo(
    () => (filteredHrs ?? []).find((h) => h.id === hrId),
    [filteredHrs, hrId]
  );
  const selectedStudent = useMemo(() => students.find((s) => s.id === studentId), [students, studentId]);

  const doSend = async () => {
    if (!studentId || !hrId) {
      toast.error("Select student and HR");
      return;
    }
    setSending(true);
    const payload = {
      student_id: studentId,
      hr_id: hrId,
      template_label: templateLabel.trim() ? templateLabel.trim() : null,
      subject: subject.trim() ? subject.trim() : null,
      body: body.trim() ? body.trim() : null,
    };
    try {
      await sendOutreach(payload);
      toast.success("Sent", {
        action: {
          label: "View in Campaigns",
          onClick: () => {
            const qs = new URLSearchParams();
            qs.set("student_id", studentId);
            qs.set("hr_id", hrId);
            window.location.assign(`/campaigns?${qs.toString()}`);
          },
        },
      });
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      qc.invalidateQueries({ queryKey: ["email-logs"] });
    } catch (first: unknown) {
      const msg = String(
        (first as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? ""
      );
      if (msg.toLowerCase().includes("assignment")) {
        try {
          await createAssignments({ student_id: studentId, hr_ids: [hrId] });
          await sendOutreach(payload);
          toast.success("Assigned and sent", {
            action: {
              label: "View in Campaigns",
              onClick: () => {
                const qs = new URLSearchParams();
                qs.set("student_id", studentId);
                qs.set("hr_id", hrId);
                window.location.assign(`/campaigns?${qs.toString()}`);
              },
            },
          });
          qc.invalidateQueries({ queryKey: ["campaigns"] });
        } catch (second: unknown) {
          const d = (second as { response?: { data?: { detail?: string } } }).response?.data?.detail;
          toast.error(typeof d === "string" ? d : "Send failed");
        }
      } else {
        toast.error(msg || "Send failed");
      }
    } finally {
      setSending(false);
      setConfirmOpen(false);
    }
  };

  return (
    <PageLayout
      title="Outreach"
      subtitle="POST /outreach/send — compose, preview, and confirm before sending"
      actions={
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="gap-1.5"
          disabled={!studentId || !hrId}
          onClick={() => setConfirmOpen(true)}
        >
          <Send className="h-4 w-4" />
          Send now
        </Button>
      }
    >
      <FilterBar>
        <FilterField label="Student">
          <Select
            value={studentId || SEL_NONE}
            onValueChange={(v) => {
              setStudentId(v === SEL_NONE ? "" : v);
              setHrId("");
            }}
          >
            <SelectTrigger className="h-10 min-w-[220px] text-sm" aria-label="Student">
              <SelectValue placeholder="Select student" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={SEL_NONE}>Select student</SelectItem>
              {students.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FilterField>
        <FilterField label="Find HR (email / name / company)">
          <Input value={hrSearch} onChange={(e) => setHrSearch(e.target.value)} placeholder="Type to filter…" />
        </FilterField>
        <FilterField label="HR contact">
          <Select
            value={hrId || SEL_NONE}
            onValueChange={(v) => setHrId(v === SEL_NONE ? "" : v)}
            disabled={!studentId}
          >
            <SelectTrigger className="h-10 min-w-[260px] max-w-md text-sm" aria-label="HR contact">
              <SelectValue placeholder={studentId ? "Select HR" : "Pick student first"} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={SEL_NONE}>{studentId ? "Select HR" : "Pick student first"}</SelectItem>
              {(filteredHrs ?? []).map((h) => (
                <SelectItem key={h.id} value={h.id}>
                  {h.company} — {h.name} ({h.email})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FilterField>
        <FilterField label="Template (optional)">
          <Select
            value={templateLabel.trim() ? templateLabel : TPL_DEFAULT}
            onValueChange={(v) => setTemplateLabel(v === TPL_DEFAULT ? "" : v)}
          >
            <SelectTrigger className="h-10 min-w-[200px] text-sm" aria-label="Template">
              <SelectValue placeholder="Default" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={TPL_DEFAULT}>Default</SelectItem>
              <SelectItem value="V1">V1</SelectItem>
              <SelectItem value="funding_hook">funding_hook</SelectItem>
            </SelectContent>
          </Select>
        </FilterField>
      </FilterBar>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
          <PremiumCard className="p-4">
            <h3 className="text-lg font-semibold">Message overrides</h3>
            <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">Optional subject & body — leave blank to use templates.</p>
            <div className="mt-4 space-y-3">
              <div>
                <Label htmlFor="subj">Subject</Label>
                <Input id="subj" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Re: …" />
              </div>
              <div>
                <Label htmlFor="bod">Body</Label>
                <Textarea
                  id="bod"
                  className="min-h-[140px] font-mono text-sm"
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder="Email body…"
                />
              </div>
            </div>
          </PremiumCard>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <PremiumCard className="p-4">
            <div className="flex items-center gap-2">
              <Eye className="h-5 w-5 text-[#4F46E5]" />
              <h3 className="text-lg font-semibold">Live preview</h3>
            </div>
            <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">What will be sent (overrides + routing context)</p>
            <div className="mt-4 space-y-3 rounded-lg border border-border/80 bg-muted/30 p-4 text-sm">
              <p>
                <span className="font-medium text-muted-foreground">Student:</span> {selectedStudent?.name ?? "—"}
              </p>
              <p>
                <span className="font-medium text-muted-foreground">HR:</span>{" "}
                {selectedHr ? `${selectedHr.name} · ${selectedHr.email}` : "—"}
              </p>
              <p>
                <span className="font-medium text-muted-foreground">Template:</span> {templateLabel || "Default pipeline"}
              </p>
              <div className="border-t border-border/60 pt-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Subject</p>
                <p className="mt-1 font-medium">{subject.trim() || "(template default)"}</p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Body</p>
                <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-sans text-sm">
                  {body.trim() || "(template default)"}
                </pre>
              </div>
            </div>
          </PremiumCard>
        </motion.div>
      </div>

      <PremiumCard className="mt-6 border-dashed p-4">
        <p className="text-sm text-gray-500 dark:text-muted-foreground">
          Use the HR filter to narrow the list, pick a row, then <strong>Send now</strong>. You will confirm recipients in the next step.
          Bulk workflows live under <strong>HR Contacts</strong>.
        </p>
      </PremiumCard>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent className="rounded-xl">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-lg font-semibold">Confirm send</AlertDialogTitle>
            <AlertDialogDescription className="text-sm text-gray-500">
              Send one email from <strong>{selectedStudent?.name ?? "?"}</strong> to{" "}
              <strong>{selectedHr?.email ?? "?"}</strong>?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <Button type="button" onClick={() => void doSend()} disabled={sending || !studentId || !hrId}>
              {sending ? "Sending…" : "Confirm send"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </PageLayout>
  );
}
