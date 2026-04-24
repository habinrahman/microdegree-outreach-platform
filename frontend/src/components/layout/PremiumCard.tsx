import { forwardRef } from "react";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/** Enterprise card shell: rounded-xl, shadow, hover lift, transition-all duration-300 */
export const PremiumCard = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "rounded-xl border border-border/80 bg-card text-card-foreground shadow-sm transition-all duration-300",
        "hover:shadow-md",
        className
      )}
      {...props}
    />
  )
);
PremiumCard.displayName = "PremiumCard";
