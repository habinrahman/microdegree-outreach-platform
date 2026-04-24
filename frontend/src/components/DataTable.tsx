import type { HTMLAttributes, ReactNode } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PremiumCard } from "@/components/layout/PremiumCard";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export type ColumnDef<T> = {
  id: string;
  header: ReactNode;
  className?: string;
  cell: (row: T) => React.ReactNode;
};

export function DataTable<T>({
  columns,
  data,
  getRowKey,
  getRowProps,
  loading,
  emptyMessage = "No data.",
  emptyState,
  className,
}: {
  columns: ColumnDef<T>[];
  data: T[] | null | undefined;
  getRowKey: (row: T, index: number) => string;
  /** Merge into each `<TableRow>` (e.g. id, className, data-*) for deep-link highlight. */
  getRowProps?: (row: T, index: number) => HTMLAttributes<HTMLTableRowElement>;
  loading?: boolean;
  emptyMessage?: string;
  /** Rich empty state (card, actions). When set, overrides emptyMessage for the zero-row case. */
  emptyState?: ReactNode;
  className?: string;
}) {
  if (loading) {
    const colCount = Math.max(1, columns?.length ?? 1);
    return (
      <PremiumCard className={cn("overflow-hidden p-0 shadow-sm transition-all duration-300 hover:shadow-md", className)}>
        <div className="overflow-x-auto max-h-[min(70vh,720px)] overflow-y-auto bg-card">
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-card">
              <TableRow className="hover:bg-transparent border-border">
                {(columns || []).map((c) => (
                  <TableHead key={c.id} className={cn("text-muted-foreground font-medium", c.className)}>
                    {c.header}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {Array.from({ length: 10 }).map((_, r) => (
                <TableRow key={`sk-${r}`} className="border-border">
                  {Array.from({ length: colCount }).map((__, c) => (
                    <TableCell key={`sk-${r}-${c}`}>
                      <Skeleton className={cn("h-4 w-full", c === 0 ? "max-w-[220px]" : "max-w-[280px]")} />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </PremiumCard>
    );
  }

  const rows = data ?? [];

  return (
    <PremiumCard className={cn("overflow-hidden p-0 shadow-sm transition-all duration-300 hover:shadow-md", className)}>
      <div className="overflow-x-auto max-h-[min(70vh,720px)] overflow-y-auto bg-card">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-card">
            <TableRow className="hover:bg-transparent border-border">
              {(columns || []).map((c) => (
                <TableHead key={c.id} className={cn("text-muted-foreground font-medium", c.className)}>
                  {c.header}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="p-0">
                  {emptyState ? (
                    <div className="p-6">{emptyState}</div>
                  ) : (
                    <div className="flex h-24 items-center justify-center text-center text-muted-foreground">
                      {emptyMessage}
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ) : (
              (rows || []).map((row, i) => {
                const rowProps = getRowProps?.(row, i);
                const { className: rowClassName, ...rowRest } = rowProps ?? {};
                return (
                  <TableRow
                    key={getRowKey(row, i)}
                    {...rowRest}
                    className={cn("border-border hover:bg-muted/50 transition", rowClassName)}
                  >
                    {(columns || []).map((c) => (
                      <TableCell key={c.id} className={c.className}>
                        {c.cell(row)}
                      </TableCell>
                    ))}
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>
    </PremiumCard>
  );
}
