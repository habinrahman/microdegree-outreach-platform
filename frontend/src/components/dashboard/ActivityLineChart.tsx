import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { motion } from "framer-motion";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export type ActivityLineDatum = { date: string; sent: number };

export function ActivityLineChart({
  data,
  loading,
  className,
  onPointClick,
}: {
  data: ActivityLineDatum[];
  loading?: boolean;
  className?: string;
  /** Click a point to jump to sent campaigns (time window is visual only). */
  onPointClick?: (datum: ActivityLineDatum) => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.15 }}
      className={cn("h-full", className)}
    >
      <Card className="h-full rounded-xl border bg-card/60 shadow-sm transition-all duration-300 hover:shadow-md backdrop-blur-md">
        <CardHeader className="space-y-1 border-b border-border/50 bg-gradient-to-r from-[#4F46E5]/[0.08] to-transparent p-6 pb-4">
          <CardTitle className="text-lg font-semibold">Campaign activity trend</CardTitle>
          <CardDescription className="text-sm text-gray-500 dark:text-muted-foreground">
            Emails sent over time (from loaded campaigns) · hover for detail · click a point to filter Campaigns
          </CardDescription>
        </CardHeader>
        <CardContent className="p-6 pt-4">
          {loading ? (
            <Skeleton className="h-[280px] w-full rounded-xl" />
          ) : data.length === 0 ? (
            <p className="flex h-[220px] items-center justify-center text-sm text-gray-500 dark:text-muted-foreground">
              No sent timestamps yet — activity will appear after sends complete.
            </p>
          ) : (
            <div className="h-[min(280px,38vh)] w-full min-h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border/60" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} className="text-muted-foreground" />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12 }} className="text-muted-foreground" />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 12,
                      border: "1px solid hsl(var(--border))",
                      background: "hsl(var(--card))",
                      maxWidth: 300,
                    }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const row = payload[0].payload as ActivityLineDatum;
                      return (
                        <div className="space-y-1 p-1 text-xs">
                          <p className="font-semibold text-foreground">{row.date}</p>
                          <p className="tabular-nums text-muted-foreground">{row.sent.toLocaleString()} sent</p>
                          <p className="leading-snug text-muted-foreground">
                            Daily tally of campaigns marked sent with a timestamp on that calendar day.
                          </p>
                          {onPointClick ? (
                            <p className="pt-1 font-medium text-primary">Click point → Campaigns (sent)</p>
                          ) : null}
                        </div>
                      );
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="sent"
                    stroke="#4F46E5"
                    strokeWidth={2.5}
                    dot={{ r: 3, fill: "#4F46E5", strokeWidth: 0 }}
                    activeDot={{
                      r: 6,
                      cursor: onPointClick ? "pointer" : undefined,
                      onClick: (_e, payload) => {
                        if (!onPointClick || !payload || typeof payload !== "object") return;
                        const p = payload as { payload?: ActivityLineDatum };
                        if (p.payload) onPointClick(p.payload);
                      },
                    }}
                    animationDuration={700}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
