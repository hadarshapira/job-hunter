import { useQuery } from '@tanstack/react-query'
import { api, STATUSES, type User } from '../api'
import { Empty, PageTitle } from '../components'

export default function StatsPage({ user, onLogout }: { user: User; onLogout: () => void }) {
  const stats = useQuery({ queryKey: ['stats'], queryFn: api.stats })
  if (stats.isPending) return <Empty>Loading…</Empty>
  if (stats.isError) return <Empty>Error: {stats.error.message}</Empty>
  const s = stats.data
  const total = Object.values(s.by_status).reduce((a, b) => a + b, 0)
  const max = Math.max(1, ...Object.values(s.by_status))

  const tiles = [
    { label: 'Jobs tracked', value: total },
    { label: 'Applied', value: s.applied_total },
    { label: 'Response rate', value: `${Math.round(s.response_rate * 100)}%` },
    { label: 'Follow-ups due', value: s.follow_ups_due },
  ]

  return (
    <>
      <PageTitle right={<button onClick={onLogout} className="btn-ghost md:hidden">Log out</button>}>Stats</PageTitle>
      <p className="-mt-2 mb-4 text-sm text-muted md:hidden">Signed in as {user.email}</p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="card p-4">
            <div className="text-xs text-muted">{t.label}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">{t.value}</div>
          </div>
        ))}
      </div>

      <div className="card mt-4 p-4">
        <h2 className="mb-3 font-medium">Pipeline</h2>
        <div className="grid gap-2">
          {STATUSES.filter((x) => s.by_status[x.value]).map((x) => (
            <div key={x.value} className="grid grid-cols-[6rem_1fr_2rem] items-center gap-3 text-sm">
              <span>{x.label}</span>
              <div className="h-2.5 rounded-full bg-surface-2">
                <div className={`h-full rounded-full tone-solid tone-${x.value}`} style={{ width: `${(s.by_status[x.value] / max) * 100}%` }} />
              </div>
              <span className="text-right tabular-nums">{s.by_status[x.value]}</span>
            </div>
          ))}
          {total === 0 && <p className="text-sm text-muted">No jobs yet.</p>}
        </div>
      </div>

      <div className="card mt-4 p-4">
        <h2 className="mb-3 font-medium">By source</h2>
        <div className="flex flex-wrap gap-2 text-sm">
          {Object.entries(s.by_source).map(([src, n]) => (
            <span key={src} className="pill bg-surface-2 px-3 py-1">{src}: {n}</span>
          ))}
        </div>
      </div>
    </>
  )
}
