import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight } from "lucide-react";

type Props = {
  page: number;
  /** When set (e.g. client-side slice), show “of N”. Omit for unknown total (API pages). */
  totalPages?: number;
  hasNext: boolean;
  hasPrev: boolean;
  onPageChange: (page: number) => void;
  disabled?: boolean;
  className?: string;
  /** Shown when total row count is unknown (server pages). */
  pageSize?: number;
};

export function ListPagination({
  page,
  totalPages,
  hasNext,
  hasPrev,
  onPageChange,
  disabled,
  className,
  pageSize,
}: Props) {
  const canPrev = hasPrev && page > 1;
  const canNext = hasNext;

  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-sm",
        className
      )}
    >
      <div className="text-muted-foreground">
        <span className="font-medium text-foreground">Page {page}</span>
        {totalPages != null && totalPages > 1 ? (
          <span className="ml-1">of {totalPages}</span>
        ) : hasNext ? (
          <span className="ml-1 text-xs">· more available</span>
        ) : null}
        {pageSize ? (
          <span className="ml-2 text-xs">· {pageSize} per page</span>
        ) : null}
      </div>
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 gap-1 px-2"
          disabled={disabled || !canPrev}
          onClick={() => onPageChange(page - 1)}
          aria-label="Previous page"
        >
          <ChevronLeft className="h-4 w-4" />
          Prev
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 gap-1 px-2"
          disabled={disabled || !canNext}
          onClick={() => onPageChange(page + 1)}
          aria-label="Next page"
        >
          Next
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
