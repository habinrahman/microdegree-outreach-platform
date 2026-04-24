import { useQuery } from '@tanstack/react-query'
import { formatApiError } from '@/api/client'
import { fetchApiJson } from '@/api/http'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

function shortStudentId(id) {
  if (!id || typeof id !== 'string') return '—'
  return id.length > 10 ? `${id.slice(0, 8)}…` : id
}

function displayTime(row) {
  return row.sent_at || row.created_at || row.scheduled_at || '—'
}

/** For campaign rows: array expected; empty array = no data. */
function isEmptyData(data) {
  if (data == null) return true
  if (Array.isArray(data)) return data.length === 0
  if (typeof data === 'object') return Object.keys(data).length === 0
  return true
}

export default function CampaignTable() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['campaigns', { limit: 50 }],
    queryFn: async () => {
      const json = await fetchApiJson('/campaigns', { limit: 50 })
      return Array.isArray(json) ? json : []
    },
    retry: 1,
    retryDelay: 1500,
  })

  if (isPending) {
    return (
      <div className="mt-10">
        <div role="status">Loading...</div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="mt-10">
        <h2 className="mb-2 text-lg font-semibold tracking-tight">Campaigns</h2>
        <div>Error loading data</div>
        <p className="mt-2 text-sm text-muted-foreground" role="alert">
          {formatApiError(error)}
        </p>
        <button
          type="button"
          onClick={() => refetch()}
          className="mt-3 rounded-md border border-input bg-background px-3 py-1.5 text-sm hover:bg-accent"
        >
          Retry
        </button>
      </div>
    )
  }

  if (isEmptyData(data)) {
    return (
      <div className="mt-10">
        <h2 className="mb-2 text-lg font-semibold tracking-tight">Campaigns</h2>
        <div className="text-muted-foreground">No data available</div>
      </div>
    )
  }

  const rows = data

  return (
    <div className="mt-10">
      <h2 className="mb-4 text-lg font-semibold tracking-tight">Campaigns</h2>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Student</TableHead>
              <TableHead>Company</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Reply Status</TableHead>
              <TableHead>Time</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row, idx) => (
              <TableRow key={row.id ?? `campaign-${idx}`}>
                <TableCell
                  className="font-mono text-xs"
                  title={row.student_id}
                >
                  {shortStudentId(row.student_id)}
                </TableCell>
                <TableCell>{row.company ?? '—'}</TableCell>
                <TableCell>{row.hr_email ?? '—'}</TableCell>
                <TableCell>{row.status ?? '—'}</TableCell>
                <TableCell>{row.reply_status ?? '—'}</TableCell>
                <TableCell className="whitespace-nowrap font-mono text-xs">
                  {displayTime(row)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
