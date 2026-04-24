import { cn } from "@/lib/utils";

export type StatusTone = "success" | "failed" | "pending" | "replied" | "neutral";

const toneClass: Record<StatusTone, string> = {
  success: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-500/30",
  failed: "bg-red-500/15 text-red-700 dark:text-red-400 border-red-500/30",
  pending: "bg-amber-500/15 text-amber-800 dark:text-amber-300 border-amber-500/30",
  replied: "bg-sky-500/15 text-sky-800 dark:text-sky-300 border-sky-500/30",
  neutral: "bg-muted text-muted-foreground border-border",
};

/** Map raw backend strings to dashboard tone (green / red / yellow / blue). */
export function inferTone(raw: string | null | undefined): StatusTone {
  const s = (raw ?? "").toLowerCase();
  if (!s) return "neutral";

  if (
    s === "sent" ||
    s === "delivered" ||
    s === "interested" ||
    s === "closed" ||
    s === "healthy"
  )
    return "success";
  if (
    s === "failed" ||
    s.includes("reject") ||
    s === "bounce" ||
    s === "bounced" ||
    s === "blocked" ||
    s === "cancelled"
  )
    return "failed";
  if (
    s === "pending" ||
    s === "scheduled" ||
    s === "processing" ||
    s === "open" ||
    s === "paused"
  )
    return "pending";
  if (
    s === "replied" ||
    s === "interview" ||
    s.includes("interview") ||
    s.includes("progress") ||
    s === "auto_reply" ||
    s === "auto reply"
  )
    return "replied";
  if (s.includes("followup") || s === "initial") return "pending";
  return "neutral";
}

/** Canonical reply / delivery categories (INTERESTED, BOUNCE, etc.). */
export function replyCategoryTone(raw: string | null | undefined): StatusTone {
  const u = (raw ?? "").toUpperCase();
  if (!u.trim()) return "neutral";
  if (u.includes("INTERESTED")) return "success";
  if (u.includes("INTERVIEW")) return "replied";
  if (u.includes("REJECT") || u.includes("NOT_INTERESTED")) return "failed";
  if (u.includes("AUTO_REPLY") || u.includes("AUTO REPLY")) return "replied";
  if (
    u.includes("BOUNCE") ||
    u.includes("BOUNCED") ||
    u.includes("BLOCKED") ||
    u.includes("TEMP_FAIL")
  )
    return "failed";
  if (u.includes("OOO")) return "pending";
  if (u.includes("UNKNOWN") || u === "OTHER") return "neutral";
  return inferTone(raw);
}

export function StatusBadge({
  children,
  tone,
  raw,
  className,
}: {
  children: React.ReactNode;
  tone?: StatusTone;
  raw?: string | null;
  className?: string;
}) {
  const t = tone ?? inferTone(typeof children === "string" ? children : raw);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
        toneClass[t],
        className
      )}
    >
      {children}
    </span>
  );
}
