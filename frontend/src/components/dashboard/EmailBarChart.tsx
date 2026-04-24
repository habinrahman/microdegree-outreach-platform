import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { motion } from "framer-motion";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const BAR_COLORS: Record<string, string> = {
  Sent: "#22C55E",
  "Undelivered (invalid/bounced)": "#EF4444",
  Bounced: "#8B5CF6",
  Blocked: "#F59E0B",
};

export type EmailBarDatum = { name: string; value: number };

const BAR_HINTS: Record<string, string> = {
  Sent: "Messages accepted by the mail path for valid HR addresses (includes rows with blank delivery flags).",
  "Undelivered (invalid/bounced)":
    "Hard failures: invalid HR mailbox, transport errors, or policy blocks counted as failed delivery.",
  Bounced: "Recipient server rejected after acceptance (bounce signals).",
  Blocked: "Safety or policy holds (e.g. blocked HR or compliance gate).",
};

export function EmailBarChart({
  data,
  loading,
  className,
  onBarClick,
}: {
  data: EmailBarDatum[];
  loading?: boolean;
  className?: string;
  /** Click a bar to drill into Campaigns with the matching delivery lens. */
  onBarClick?: (name: string) => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.05 }}
      className={cn("h-full", className)}
    >
      <Card className="h-full rounded-xl border bg-card/60 shadow-sm transition-all duration-300 hover:shadow-md backdrop-blur-md">
        <CardHeader className="space-y-1 border-b border-border/50 bg-gradient-to-r from-indigo-500/[0.06] to-transparent p-6 pb-4">
          <CardTitle className="text-lg font-semibold">Email performance</CardTitle>
          <CardDescription className="text-sm text-gray-500 dark:text-muted-foreground">
            Sent, undelivered (invalid/bounced HR), bounced, and blocked volume · click a bar to filter Campaigns
          </CardDescription>
        </CardHeader>
        <CardContent className="p-6 pt-4">
          {loading ? (
            <Skeleton className="h-[280px] w-full rounded-xl" />
          ) : (
            <div className="h-[min(280px,40vh)] w-full min-h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border/60" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} className="text-muted-foreground" />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12 }} className="text-muted-foreground" />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 12,
                      border: "1px solid hsl(var(--border))",
                      background: "hsl(var(--card))",
                      maxWidth: 320,
                    }}
                    formatter={(value: number, name: string) => [value.toLocaleString(), name]}
                    labelFormatter={(label) => String(label)}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const row = payload[0].payload as EmailBarDatum;
                      const hint = BAR_HINTS[row.name] ?? "Volume from the live summary endpoint.";
                      return (
                        <div className="space-y-1 p-1 text-xs">
                          <p className="font-semibold text-foreground">{row.name}</p>
                          <p className="tabular-nums text-muted-foreground">{row.value.toLocaleString()} campaigns</p>
                          <p className="leading-snug text-muted-foreground">{hint}</p>
                          {onBarClick ? (
                            <p className="pt-1 font-medium text-primary">Click bar to open Campaigns</p>
                          ) : null}
                        </div>
                      );
                    }}
                  />
                  <Bar dataKey="value" radius={[8, 8, 0, 0]} maxBarSize={56}>
                    {data.map((entry) => (
                      <Cell
                        key={entry.name}
                        fill={BAR_COLORS[entry.name] ?? "#4F46E5"}
                        style={{ cursor: onBarClick ? "pointer" : undefined }}
                        onClick={() => onBarClick?.(entry.name)}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
