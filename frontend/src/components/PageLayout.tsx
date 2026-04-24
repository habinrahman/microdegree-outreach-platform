/**
 * Page chrome only (no shell). Sidebar + Navbar live in AppLayout.
 */
export function PageLayout({
  title,
  subtitle,
  filters,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  filters?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  const showHeader = Boolean(title?.trim() || subtitle || actions);

  return (
    <div className="space-y-6">
      {showHeader ? (
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            {title?.trim() ? (
              <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
            ) : null}
            {subtitle ? (
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{subtitle}</p>
            ) : null}
          </div>
          {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
        </div>
      ) : null}
      {filters ? <div className="space-y-4">{filters}</div> : null}
      <div className="space-y-6">{children}</div>
    </div>
  );
}
