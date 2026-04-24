import { useQuery } from '@tanstack/react-query'
import { formatApiError } from '@/api/client'
import { fetchApiJson } from '@/api/http'
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import CampaignTable from '@/CampaignTable'

/** Safe empty check: null, [], or {} — avoids Object.keys on null. */
function isEmptyData(data) {
  if (data == null) return true
  if (Array.isArray(data)) return data.length === 0
  if (typeof data === 'object') return Object.keys(data).length === 0
  return false
}

export default function Dashboard() {
  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['analytics', 'summary'],
    queryFn: () => fetchApiJson('/analytics/summary'),
    retry: 1,
    retryDelay: 1500,
  })

  if (isPending) {
    return (
      <div className="mx-auto w-full max-w-5xl px-4 py-8 text-left">
        <header className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
        </header>
        <div role="status">Loading...</div>
        <CampaignTable />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="mx-auto w-full max-w-5xl px-4 py-8 text-left">
        <header className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
        </header>
        <div>Error loading data</div>
        <p className="mt-2 text-sm text-muted-foreground">
          {formatApiError(error)}
        </p>
        <button
          type="button"
          onClick={() => refetch()}
          className="mt-3 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Retry
        </button>
        <CampaignTable />
      </div>
    )
  }

  if (isEmptyData(data)) {
    return (
      <div className="mx-auto w-full max-w-5xl px-4 py-8 text-left">
        <header className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
        </header>
        <div className="text-muted-foreground">No data available</div>
        <CampaignTable />
      </div>
    )
  }

  const summary = data

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 text-left">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Placement Outreach — metrics from{' '}
          <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
            /analytics/summary
          </code>
        </p>
      </header>

      <ul className="mb-10 grid list-none grid-cols-1 gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3">
        <li>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Students Registered</CardDescription>
              <CardTitle className="text-3xl tabular-nums">
                {summary.students ?? '—'}
              </CardTitle>
            </CardHeader>
          </Card>
        </li>
        <li>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>HR Contacts</CardDescription>
              <CardTitle className="text-3xl tabular-nums">
                {summary.hrs ?? '—'}
              </CardTitle>
            </CardHeader>
          </Card>
        </li>
        <li>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Emails Sent</CardDescription>
              <CardTitle className="text-3xl tabular-nums">
                {summary.emails_sent ?? '—'}
              </CardTitle>
            </CardHeader>
          </Card>
        </li>
        <li>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Success Rate</CardDescription>
              <CardTitle className="text-3xl tabular-nums">
                {summary.success_rate != null
                  ? `${summary.success_rate}%`
                  : '—'}
              </CardTitle>
            </CardHeader>
          </Card>
        </li>
        <li>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Total Replies</CardDescription>
              <CardTitle className="text-3xl tabular-nums">
                {summary.total_replies ?? summary.replied ?? '—'}
              </CardTitle>
            </CardHeader>
          </Card>
        </li>
        <li>
          <Card>
            <CardHeader className="pb-2">
              <CardDescription>Blocked HR (campaigns)</CardDescription>
              <CardTitle className="text-3xl tabular-nums">
                {summary.blocked_hr_count ??
                  summary.total_blocked ??
                  '—'}
              </CardTitle>
            </CardHeader>
          </Card>
        </li>
      </ul>
      {isFetching && !isPending && (
        <p className="mb-4 text-xs text-muted-foreground">Refreshing…</p>
      )}

      <CampaignTable />
    </div>
  )
}
