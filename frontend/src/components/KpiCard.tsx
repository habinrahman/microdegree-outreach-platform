import { useEffect, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { animate, motion } from "framer-motion";

import { cn } from "@/lib/utils";

export type KpiTone = "success" | "danger" | "warning" | "reply" | "analytics" | "neutral";

const toneStyles: Record<
  KpiTone,
  { ring: string; icon: string; indicator: string; gradient: string }
> = {
  success: {
    ring: "border-[#22C55E]/25 hover:border-[#22C55E]/45",
    icon: "bg-[#22C55E]/15 text-[#16A34A] dark:text-[#4ADE80]",
    indicator: "bg-[#22C55E]",
    gradient: "from-[#22C55E]/12 via-emerald-500/5 to-transparent",
  },
  danger: {
    ring: "border-[#EF4444]/25 hover:border-[#EF4444]/45",
    icon: "bg-[#EF4444]/15 text-[#DC2626] dark:text-[#F87171]",
    indicator: "bg-[#EF4444]",
    gradient: "from-[#EF4444]/12 via-red-500/5 to-transparent",
  },
  warning: {
    ring: "border-[#F59E0B]/30 hover:border-[#F59E0B]/50",
    icon: "bg-[#F59E0B]/15 text-[#D97706] dark:text-[#FBBF24]",
    indicator: "bg-[#F59E0B]",
    gradient: "from-[#F59E0B]/14 via-amber-500/5 to-transparent",
  },
  reply: {
    ring: "border-[#3B82F6]/25 hover:border-[#3B82F6]/45",
    icon: "bg-[#3B82F6]/15 text-[#2563EB] dark:text-[#60A5FA]",
    indicator: "bg-[#3B82F6]",
    gradient: "from-[#3B82F6]/12 via-sky-500/5 to-transparent",
  },
  analytics: {
    ring: "border-[#4F46E5]/25 hover:border-[#4F46E5]/45",
    icon: "bg-[#4F46E5]/15 text-[#4338CA] dark:text-[#818CF8]",
    indicator: "bg-[#4F46E5]",
    gradient: "from-[#4F46E5]/14 via-violet-500/5 to-transparent",
  },
  neutral: {
    ring: "border-border hover:border-border/90",
    icon: "bg-muted text-muted-foreground",
    indicator: "bg-muted-foreground",
    gradient: "from-muted/40 to-transparent",
  },
};

function useAnimatedMetric(
  target: number,
  options: { decimals?: number; duration?: number; enabled?: boolean }
) {
  const { decimals = 0, duration = 0.85, enabled = true } = options;
  const [display, setDisplay] = useState(enabled ? 0 : target);
  const prevRef = useRef(0);

  useEffect(() => {
    if (!enabled) {
      setDisplay(target);
      prevRef.current = target;
      return;
    }
    const from = prevRef.current;
    const c = animate(from, target, {
      duration,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => {
        setDisplay(v);
        prevRef.current = v;
      },
      onComplete: () => {
        prevRef.current = target;
      },
    });
    return () => c.stop();
  }, [target, duration, enabled]);

  if (decimals > 0) {
    return display.toFixed(decimals);
  }
  return Math.round(display).toLocaleString();
}

export type KpiCardProps = {
  title: string;
  icon?: LucideIcon;
  tone?: KpiTone;
  className?: string;
  subtext?: string;
  /** Plain value (string or number). Finite numbers count up unless `staticDisplay`. */
  value?: string | number;
  /** When true, `value` as number is shown without animation. */
  staticDisplay?: boolean;
  /** Explicit display string (skips animation). */
  valueDisplay?: string;
  /** Animated numeric (takes precedence over numeric `value`). */
  numericValue?: number;
  valueSuffix?: string;
  decimals?: number;
  valueClassName?: string;
};

export function KpiCard({
  title,
  icon: Icon,
  tone = "neutral",
  className,
  subtext,
  value,
  staticDisplay = false,
  valueDisplay,
  numericValue,
  valueSuffix,
  decimals = 0,
  valueClassName,
}: KpiCardProps) {
  const animTarget =
    numericValue !== undefined
      ? numericValue
      : typeof value === "number" && Number.isFinite(value) && !staticDisplay
        ? value
        : undefined;

  const showAnimated = animTarget !== undefined && valueDisplay === undefined;
  const animated = useAnimatedMetric(animTarget ?? 0, {
    decimals,
    enabled: showAnimated,
  });

  const textContent =
    valueDisplay !== undefined
      ? valueDisplay
      : showAnimated
        ? null
        : value !== undefined
          ? String(value)
          : "—";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      whileHover={{ y: -2, transition: { duration: 0.25 } }}
      className={cn(
        "group relative overflow-hidden rounded-xl border bg-[#F8FAFC]/40 p-4 shadow-sm transition-all duration-300 dark:bg-card/30",
        "hover:shadow-md",
        toneStyles[tone].ring,
        className
      )}
    >
      <div
        className={cn(
          "pointer-events-none absolute inset-0 bg-gradient-to-br opacity-90 dark:opacity-70",
          toneStyles[tone].gradient
        )}
        aria-hidden
      />
      <div className="pointer-events-none absolute -right-6 -top-6 h-24 w-24 rounded-full bg-white/30 blur-2xl dark:bg-white/5" />
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2">
            <span
              className={cn("h-2 w-2 shrink-0 rounded-full", toneStyles[tone].indicator)}
              aria-hidden
            />
            <p className="text-lg font-semibold tracking-tight text-foreground">{title}</p>
          </div>
          <p
            className={cn(
              "text-3xl font-bold tabular-nums tracking-tight text-foreground",
              valueClassName
            )}
          >
            {showAnimated ? (
              <>
                {animated}
                {valueSuffix ?? ""}
              </>
            ) : (
              <>
                {textContent}
                {valueSuffix ?? ""}
              </>
            )}
          </p>
          {subtext ? (
            <p className="text-sm text-gray-500 dark:text-muted-foreground">{subtext}</p>
          ) : null}
        </div>
        {Icon ? (
          <div
            className={cn(
              "flex h-12 w-12 shrink-0 items-center justify-center rounded-xl shadow-sm transition-transform duration-300 group-hover:scale-110",
              toneStyles[tone].icon
            )}
          >
            <Icon className="h-6 w-6" strokeWidth={2} aria-hidden />
          </div>
        ) : null}
      </div>
    </motion.div>
  );
}
