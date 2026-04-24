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

import { PremiumCard } from "@/components/layout/PremiumCard";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const DEFAULT_COLOR = "#4F46E5";

export function SimpleBarChart({
  title,
  description,
  data,
  dataKey,
  nameKey,
  loading,
  color = DEFAULT_COLOR,
  className,
  maxHeight = 280,
  onBarClick,
}: {
  title: string;
  description?: string;
  data: Record<string, unknown>[];
  dataKey: string;
  nameKey: string;
  loading?: boolean;
  color?: string;
  className?: string;
  maxHeight?: number;
  onBarClick?: (row: Record<string, unknown>) => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={cn(className)}
    >
      <PremiumCard className="overflow-hidden backdrop-blur-sm">
        <div className="border-b border-border/60 bg-gradient-to-r from-indigo-500/[0.06] to-transparent p-6">
          <h3 className="text-lg font-semibold text-foreground">{title}</h3>
          {description ? <p className="mt-1 text-sm text-gray-500 dark:text-muted-foreground">{description}</p> : null}
        </div>
        <div className="p-6">
          {loading ? (
            <Skeleton className="w-full rounded-xl" style={{ height: maxHeight }} />
          ) : data.length === 0 ? (
            <p className="flex items-center justify-center text-sm text-gray-500 dark:text-muted-foreground" style={{ height: maxHeight }}>
              Not enough data for this chart.
            </p>
          ) : (
            <div style={{ height: maxHeight }} className="w-full min-h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border/50" vertical={false} />
                  <XAxis
                    dataKey={nameKey}
                    tick={{ fontSize: 11 }}
                    interval={0}
                    angle={-28}
                    textAnchor="end"
                    height={70}
                    className="text-muted-foreground"
                  />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} className="text-muted-foreground" />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 12,
                      border: "1px solid hsl(var(--border))",
                      background: "hsl(var(--card))",
                      maxWidth: 280,
                    }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const row = payload[0].payload as Record<string, unknown>;
                      const label = String(row[nameKey] ?? "");
                      const val = row[dataKey];
                      return (
                        <div className="space-y-1 p-1 text-xs">
                          <p className="font-semibold text-foreground">{label}</p>
                          <p className="tabular-nums text-muted-foreground">{String(val ?? "—")}</p>
                          <p className="leading-snug text-muted-foreground">
                            Bar height reflects the selected metric for this row in the current analytics response.
                          </p>
                          {onBarClick ? (
                            <p className="pt-1 font-medium text-primary">Click bar to drill down</p>
                          ) : null}
                        </div>
                      );
                    }}
                  />
                  <Bar dataKey={dataKey} radius={[6, 6, 0, 0]} maxBarSize={48}>
                    {data.map((row, i) => (
                      <Cell
                        key={i}
                        fill={color}
                        fillOpacity={0.85 - (i % 3) * 0.08}
                        style={{ cursor: onBarClick ? "pointer" : undefined }}
                        onClick={() => onBarClick?.(row)}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </PremiumCard>
    </motion.div>
  );
}
