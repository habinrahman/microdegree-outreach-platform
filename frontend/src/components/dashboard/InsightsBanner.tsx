import { motion } from "framer-motion";
import { Lightbulb, Sparkles, TrendingUp, UserRound } from "lucide-react";

import { cn } from "@/lib/utils";

export type AnalyticsSummaryShape = Record<string, unknown>;

function safe(v: unknown) {
  return Number(v ?? 0);
}

export function InsightsBanner({
  summary,
  topStudentName,
  topStudentScore,
  className,
}: {
  summary: AnalyticsSummaryShape | undefined;
  /** Best-effort from recent campaign rows */
  topStudentName: string | null;
  topStudentScore: number;
  className?: string;
}) {
  if (!summary) return null;

  const hrs = safe(summary.hrs ?? summary.hr_contacts);
  const uniqueReplies = safe(summary.unique_replies);
  const awaitingHrs = Math.max(0, Math.round(hrs - uniqueReplies));
  const replyRate = safe(summary.reply_rate);
  const successRate = safe(summary.success_rate);
  const interested = safe(summary.interested_replies);

  const insights: { icon: typeof Lightbulb; text: string; accent: string }[] = [];

  if (hrs > 0) {
    insights.push({
      icon: Lightbulb,
      text: `You have ${awaitingHrs.toLocaleString()} HR contacts who have not replied yet (approx. from unique reply coverage).`,
      accent: "from-amber-500/15 to-transparent border-amber-500/20",
    });
  }

  if (replyRate >= 25) {
    insights.push({
      icon: TrendingUp,
      text: `Reply rate is ${replyRate.toFixed(1)}% — strong engagement on sent mail.`,
      accent: "from-emerald-500/15 to-transparent border-emerald-500/20",
    });
  } else if (replyRate > 0) {
    insights.push({
      icon: TrendingUp,
      text: `Reply rate is ${replyRate.toFixed(1)}%. Consider refining templates or follow-ups to lift responses.`,
      accent: "from-sky-500/12 to-transparent border-sky-500/20",
    });
  }

  if (successRate >= 85) {
    insights.push({
      icon: Sparkles,
      text: `Delivery success rate is ${successRate.toFixed(1)}% — infrastructure looks healthy.`,
      accent: "from-violet-500/12 to-transparent border-violet-500/25",
    });
  }

  if (topStudentName && topStudentScore > 0) {
    insights.push({
      icon: UserRound,
      text: `Top signal in recent campaigns: ${topStudentName} (${topStudentScore} positive reply${topStudentScore === 1 ? "" : "s"}).`,
      accent: "from-indigo-500/12 to-transparent border-indigo-500/25",
    });
  } else if (interested > 0) {
    insights.push({
      icon: Sparkles,
      text: `${interested.toLocaleString()} interested / interview-style replies captured in analytics.`,
      accent: "from-fuchsia-500/10 to-transparent border-fuchsia-500/20",
    });
  }

  if (insights.length === 0) {
    insights.push({
      icon: Lightbulb,
      text: "Connect your data sources and send campaigns — insights will sharpen as volume grows.",
      accent: "from-slate-500/10 to-transparent border-border",
    });
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className={cn("space-y-4", className)}
    >
      <div className="rounded-xl border border-indigo-500/20 bg-gradient-to-r from-[#4F46E5]/[0.08] via-transparent to-[#3B82F6]/[0.06] p-6 shadow-sm backdrop-blur-md transition-all duration-300 hover:shadow-md">
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-indigo-600 dark:text-indigo-400" aria-hidden />
          <h2 className="text-lg font-semibold text-foreground">Quick insights</h2>
        </div>
        <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">
          Generated from analytics summary and recent campaign activity
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {insights.slice(0, 4).map((row, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 * i, duration: 0.35 }}
            className={cn(
              "flex gap-4 rounded-xl border bg-card/50 p-6 shadow-sm transition-all duration-300 hover:shadow-md",
              "bg-gradient-to-br",
              row.accent
            )}
          >
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-background/80 shadow-sm">
              <row.icon className="h-5 w-5 text-foreground/80" aria-hidden />
            </div>
            <p className="text-sm leading-relaxed text-foreground">{row.text}</p>
          </motion.div>
        ))}
      </div>
    </motion.section>
  );
}
