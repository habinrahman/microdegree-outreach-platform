import { Link, useLocation } from "react-router-dom";
import { User } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { breadcrumbsForPath } from "@/lib/routeMeta";
import { ROUTES } from "@/lib/constants";
import { Badge } from "@/components/ui/badge";
import { getHealth, getSchedulerStatus } from "@/api/api";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

type DotState = "ok" | "loading" | "error";

function Dot({ state }: { state: DotState }) {
  return (
    <span
      aria-hidden
      className={cn(
        "h-2 w-2 rounded-full",
        state === "ok"
          ? "bg-emerald-500"
          : state === "loading"
            ? "bg-amber-400 animate-pulse"
            : "bg-red-500"
      )}
    />
  );
}

function timeAgoShort(msAgo: number): string {
  if (!Number.isFinite(msAgo) || msAgo < 0) return "just now";
  const s = Math.floor(msAgo / 1000);
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export function Navbar() {
  const { pathname, search } = useLocation();
  const crumbs = breadcrumbsForPath(pathname, search);
  const [now, setNow] = useState(() => Date.now());

  // Prevent “Updated Xm ago” thrash: tick on a fixed cadence.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  const healthQ = useQuery({
    queryKey: ["health", "header"],
    queryFn: getHealth,
    select: (d) => ({ status: d?.status, db: d?.db }),
    refetchInterval: 30_000,
    refetchIntervalInBackground: true,
  });
  const schedulerQ = useQuery({
    queryKey: ["scheduler", "header"],
    queryFn: getSchedulerStatus,
    select: (d) => ({ scheduler: d?.scheduler }),
    refetchInterval: 30_000,
    refetchIntervalInBackground: true,
  });

  const backendOk = healthQ.data?.status === "ok" && !healthQ.isError;
  const dbOk = healthQ.data?.db === "ok" && !healthQ.isError;
  const schedulerOk =
    String(schedulerQ.data?.scheduler ?? "")
      .toLowerCase()
      .includes("running") && !schedulerQ.isError;

  const lastUpdatedMs =
    Math.max(healthQ.dataUpdatedAt || 0, schedulerQ.dataUpdatedAt || 0) || null;
  const updatedLabel = lastUpdatedMs
    ? `Updated ${timeAgoShort(now - lastUpdatedMs)}`
    : null;
  const isRefetching = (healthQ.isFetching && !healthQ.isLoading) || (schedulerQ.isFetching && !schedulerQ.isLoading);

  const apiDot: DotState = healthQ.isError ? "error" : healthQ.isLoading ? "loading" : backendOk ? "ok" : "error";
  const dbDot: DotState = healthQ.isError ? "error" : healthQ.isLoading ? "loading" : dbOk ? "ok" : "error";
  const schDot: DotState = schedulerQ.isError
    ? "error"
    : schedulerQ.isLoading
      ? "loading"
      : schedulerOk
        ? "ok"
        : "error";

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-4 border-b border-border bg-background/95 px-4 backdrop-blur sm:px-6">
      <Breadcrumb className="min-w-0 flex-1">
        <BreadcrumbList className="flex-nowrap">
          {crumbs.map((c, i) => {
            const isLast = i === crumbs.length - 1;
            return (
              <span key={`${c.label}-${i}`} className="contents">
                {i > 0 ? (
                  <BreadcrumbSeparator className="hidden sm:block" />
                ) : null}
                <BreadcrumbItem className="max-w-[140px] truncate sm:max-w-none">
                  {isLast ? (
                    <BreadcrumbPage className="truncate font-semibold">{c.label}</BreadcrumbPage>
                  ) : c.to ? (
                    <BreadcrumbLink asChild>
                      <Link to={c.to} className="truncate">
                        {c.label}
                      </Link>
                    </BreadcrumbLink>
                  ) : (
                    <span className="truncate text-muted-foreground">{c.label}</span>
                  )}
                </BreadcrumbItem>
              </span>
            );
          })}
        </BreadcrumbList>
      </Breadcrumb>

      <div className="flex shrink-0 items-center gap-2">
        <TooltipProvider>
          <div className="hidden items-center gap-1.5 sm:flex" aria-label="System status indicators">
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge
                  variant="secondary"
                  className="h-8 gap-1.5 px-2 text-[11px] font-medium tabular-nums"
                >
                  <Dot state={apiDot} />
                  API
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                {backendOk ? "Backend operational" : "Backend down / unknown"}
              </TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge
                  variant="secondary"
                  className="h-8 gap-1.5 px-2 text-[11px] font-medium tabular-nums"
                >
                  <Dot state={dbDot} />
                  DB
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                {dbOk ? "Database connected" : "Database down / unknown"}
              </TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Badge
                  variant="secondary"
                  className="h-8 gap-1.5 px-2 text-[11px] font-medium tabular-nums"
                >
                  <Dot state={schDot} />
                  SCH
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                {schedulerOk ? "Scheduler running" : "Scheduler stopped / unknown"}
              </TooltipContent>
            </Tooltip>

            {updatedLabel ? (
              <span
                className={cn(
                  "ml-1 hidden text-[11px] tabular-nums md:inline",
                  isRefetching ? "animate-pulse text-emerald-600 dark:text-emerald-400" : "text-muted-foreground"
                )}
              >
                {isRefetching ? "Updating…" : updatedLabel}
              </span>
            ) : null}
          </div>
        </TooltipProvider>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex shrink-0 items-center gap-2 rounded-full border border-border/80 bg-muted/40 px-2 py-1 pr-3 text-left text-sm transition hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Account menu"
            >
              <Avatar className="h-8 w-8">
                <AvatarFallback className="bg-primary/15 text-primary">
                  <User className="h-4 w-4" />
                </AvatarFallback>
              </Avatar>
              <span className="hidden max-w-[120px] truncate sm:inline font-medium text-foreground">Operator</span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>
              <p className="font-semibold">Local session</p>
              <p className="text-xs font-normal text-muted-foreground">No cloud account — browser only</p>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to={ROUTES.settings}>System status</Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link to={ROUTES.campaigns}>Campaigns</Link>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
