import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { motion } from "framer-motion";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const SLICE_COLORS = ["#22C55E", "#3B82F6", "#EF4444", "#94A3B8"];

export type ReplyPieDatum = { name: string; value: number };

const SLICE_HINTS: Record<string, string> = {
  Interested: "HR replied with positive intent (reply_status ≈ INTERESTED).",
  Interview: "Pipeline moved to interview or scheduling signals.",
  Rejected: "Explicit declines or not-interested outcomes.",
  "No Response": "Sent campaigns without a classified reply yet.",
};

export function ReplyPieChart({
  data,
  loading,
  className,
  onSliceClick,
}: {
  data: ReplyPieDatum[];
  loading?: boolean;
  className?: string;
  onSliceClick?: (name: string) => void;
}) {
  const total = data.reduce((s, d) => s + d.value, 0);

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 }}
      className={cn("h-full", className)}
    >
      <Card className="h-full rounded-xl border bg-card/60 shadow-sm transition-all duration-300 hover:shadow-md backdrop-blur-md">
        <CardHeader className="space-y-1 border-b border-border/50 bg-gradient-to-r from-violet-500/[0.07] to-transparent p-6 pb-4">
          <CardTitle className="text-lg font-semibold">Reply distribution</CardTitle>
          <CardDescription className="text-sm text-gray-500 dark:text-muted-foreground">
            Interested, interview, rejected, and no response (from recent campaigns) · click a slice to filter
          </CardDescription>
        </CardHeader>
        <CardContent className="p-6 pt-4">
          {loading ? (
            <Skeleton className="mx-auto aspect-square max-h-[280px] w-full max-w-[280px] rounded-full" />
          ) : total === 0 ? (
            <p className="flex h-[220px] items-center justify-center text-sm text-gray-500 dark:text-muted-foreground">
              No reply breakdown yet — send campaigns to populate this chart.
            </p>
          ) : (
            <div className="h-[min(300px,42vh)] w-full min-h-[240px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={58}
                    outerRadius={88}
                    paddingAngle={2}
                    animationDuration={600}
                    style={{ cursor: onSliceClick ? "pointer" : undefined }}
                    onClick={(_, index) => {
                      const name = data[index]?.name;
                      if (name) onSliceClick?.(name);
                    }}
                  >
                    {data.map((_, i) => (
                      <Cell key={i} fill={SLICE_COLORS[i % SLICE_COLORS.length]} stroke="hsl(var(--background))" strokeWidth={2} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      borderRadius: 12,
                      border: "1px solid hsl(var(--border))",
                      background: "hsl(var(--card))",
                      maxWidth: 300,
                    }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const row = payload[0] as { name?: string; value?: number };
                      const name = String(row.name ?? "");
                      const hint = SLICE_HINTS[name] ?? "Share of campaigns in this slice.";
                      return (
                        <div className="space-y-1 p-1 text-xs">
                          <p className="font-semibold text-foreground">{name}</p>
                          <p className="tabular-nums text-muted-foreground">
                            {(row.value ?? 0).toLocaleString()} campaigns
                          </p>
                          <p className="leading-snug text-muted-foreground">{hint}</p>
                          {onSliceClick ? (
                            <p className="pt-1 font-medium text-primary">Click slice to drill in</p>
                          ) : null}
                        </div>
                      );
                    }}
                  />
                  <Legend
                    verticalAlign="bottom"
                    height={36}
                    formatter={(value) => <span className="text-xs text-muted-foreground">{value}</span>}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
