import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";

export type HrBulkSendPayload = {
  subject: string;
  body: string;
  template_label: string | null;
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSend: (payload: HrBulkSendPayload) => Promise<void>;
  loading: boolean;
  selectedCount: number;
  /** While sending, shows X / total and a progress bar. */
  sendProgress?: { current: number; total: number } | null;
};

export function HrBulkSendModal({ open, onOpenChange, onSend, loading, selectedCount, sendProgress }: Props) {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [templateLabel, setTemplateLabel] = useState("");

  useEffect(() => {
    if (open) {
      setSubject("");
      setBody("");
      setTemplateLabel("");
    }
  }, [open]);

  const submit = async () => {
    await onSend({
      subject,
      body,
      template_label: templateLabel.trim() ? templateLabel.trim() : null,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Send email</DialogTitle>
          <DialogDescription>
            Sends one POST /outreach/send per selected HR ({selectedCount} selected). Optional subject/body
            override templates; leave blank to use campaign defaults.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2">
          {loading && sendProgress && sendProgress.total > 0 ? (
            <div className="rounded-lg border border-border/60 bg-muted/30 p-3">
              <p className="text-sm font-medium text-foreground">
                Sending {sendProgress.current.toLocaleString()} / {sendProgress.total.toLocaleString()}
              </p>
              <Progress
                className="mt-2 h-2"
                value={Math.min(100, (sendProgress.current / sendProgress.total) * 100)}
              />
              <p className="mt-1 text-xs text-muted-foreground">One POST /outreach/send per HR — keep this tab open.</p>
            </div>
          ) : null}
          <div className="space-y-2">
            <Label htmlFor="hr-bulk-subject">Subject</Label>
            <Input
              id="hr-bulk-subject"
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              placeholder="Optional — uses template if empty"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="hr-bulk-body">Body</Label>
            <Textarea
              id="hr-bulk-body"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Optional — uses template if empty"
              className="min-h-[160px] font-mono text-sm"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="hr-bulk-template">Template label (optional)</Label>
            <Input
              id="hr-bulk-template"
              value={templateLabel}
              onChange={(e) => setTemplateLabel(e.target.value)}
              placeholder="e.g. V1, funding_hook"
            />
          </div>
        </div>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
          <Button type="button" onClick={submit} disabled={loading || selectedCount === 0}>
            {loading ? "Sending…" : "Send"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
