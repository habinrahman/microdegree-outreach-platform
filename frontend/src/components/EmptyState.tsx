import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export function EmptyState({
  icon: Icon,
  title,
  description,
  className,
  children,
}: {
  icon: LucideIcon;
  title: string;
  description?: string;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-border/70 bg-gradient-to-b from-muted/30 to-transparent px-6 py-14 text-center",
        className
      )}
    >
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted/60 text-muted-foreground">
        <Icon className="h-7 w-7" aria-hidden />
      </div>
      <p className="mt-4 text-base font-semibold text-foreground">{title}</p>
      {description ? (
        <p className="mt-2 max-w-md text-sm text-muted-foreground leading-relaxed">{description}</p>
      ) : null}
      {children ? <div className="mt-6 flex flex-wrap justify-center gap-2">{children}</div> : null}
    </div>
  );
}
