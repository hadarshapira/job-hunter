import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useDeferredValue, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isDue, STATUSES, type JobSummary, type Status } from '../api'
import { Empty, JobCard, PageTitle } from '../components'

const FILTERS: { label: string; statuses?: Status[] }[] = [
  { label: 'New for you', statuses: ['new'] },
  { label: 'Active', statuses: ['saved', 'applied', 'screening', 'interview', 'offer'] },
  { label: 'All' },
  ...STATUSES.filter((s) => s.value !== 'new').map((s) => ({ label: s.label, statuses: [s.value] })),
]

const timeAgo = (iso: string) => {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const h = Math.round(mins / 60)
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`
}

/** "Find jobs now" with live status. Polls while a search runs, then refreshes the feed. */
export function FindJobsButton() {
  const qc = useQueryClient()
  // Time this browser asked for a search; status rows started before it belong to an older search
  const [requestedAt, setRequestedAt] = useState<number | null>(null)
  const status = useQuery({ queryKey: ['collect'], queryFn: api.collectStatus, refetchInterval: requestedAt ? 3000 : false })
  const start = useMutation({
    mutationFn: api.collectNow,
    onMutate: () => setRequestedAt(Date.now() - 2000),
    onError: () => setRequestedAt(null),
  })

  const d = status.data
  const ours = !!(requestedAt && d?.last_started && new Date(d.last_started).getTime() >= requestedAt)
  const running = start.isPending || !!d?.running || (!!requestedAt && !ours)
  useEffect(() => {
    if (requestedAt && ours && d && !d.running && d.last_finished) {
      setRequestedAt(null)
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    }
    // Give up waiting after 3 minutes
    if (requestedAt && Date.now() - requestedAt > 180_000) setRequestedAt(null)
  }, [requestedAt, ours, d, qc])

  const s = status.data
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-primary" disabled={running} onClick={() => start.mutate()}>
          {running ? <><span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" /> Searching…</> : '🔍 Find jobs now'}
        </button>
        {s?.last_finished && !running && (
          <span className="text-sm text-zinc-500">
            Last search {timeAgo(s.last_finished)}: {s.last_added === 0 ? 'nothing new' : `${s.last_added} new job${s.last_added === 1 ? '' : 's'}`}
          </span>
        )}
      </div>
      {start.isError && <p className="text-sm text-rose-500">{start.error.message}</p>}
      {running && <p className="text-xs text-zinc-500">Checking company career pages and the web. The first search can take about a minute.</p>}
      {s && !s.jsearch_enabled && <p className="text-xs text-zinc-500">Web search (JSearch) is off; only company career pages are searched.</p>}
      {s?.jsearch_quota_left != null && <p className="text-xs text-zinc-500">Web searches left this month (shared): {s.jsearch_quota_left}</p>}
      {!running && s?.last_errors.length ? (
        <details className="text-xs text-amber-600 dark:text-amber-400">
          <summary>{s.last_errors.length} source{s.last_errors.length > 1 ? 's' : ''} had problems</summary>
          <ul className="mt-1 list-inside list-disc">{s.last_errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </details>
      ) : null}
    </div>
  )
}

function NewJobActions({ job }: { job: JobSummary }) {
  const qc = useQueryClient()
  const move = useMutation({
    mutationFn: (status: Status) => api.updateJob(job.id, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    },
  })
  return (
    <div className="mt-1.5 grid grid-cols-2 gap-2">
      <button className="btn-ghost py-2" disabled={move.isPending} onClick={() => move.mutate('archived')}>✕ Not for me</button>
      <button className="btn-primary py-2" disabled={move.isPending} onClick={() => move.mutate('saved')}>★ Save</button>
    </div>
  )
}

export default function Jobs() {
  const stats = useQuery({ queryKey: ['stats'], queryFn: api.stats })
  const [filter, setFilter] = useState<number | null>(null)
  // Open on "New for you" when there are new jobs, otherwise on "Active"
  const active = filter ?? (stats.data ? (stats.data.new > 0 ? 0 : 1) : null)
  const [q, setQ] = useState('')
  const query = useDeferredValue(q)
  const jobs = useQuery({
    queryKey: ['jobs', active, query],
    queryFn: () => api.jobs({ status: FILTERS[active!].statuses, q: query || undefined }),
    enabled: active !== null,
  })
  const due = jobs.data?.filter((j) => isDue(j.follow_up_on)) ?? []
  const isNew = active === 0

  return (
    <>
      <PageTitle right={<Link to="/add" className="btn-primary hidden md:inline-flex">+ Add job</Link>}>Jobs</PageTitle>
      <input className="input mb-3" placeholder="Search title or company…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
        {FILTERS.map((f, i) => (
          <button
            key={f.label}
            onClick={() => setFilter(i)}
            className={`pill shrink-0 border px-3 py-1.5 text-sm ${i === active ? 'border-indigo-600 bg-indigo-600 text-white' : 'border-zinc-300 dark:border-zinc-700'}`}
          >
            {f.label}
            {i === 0 && stats.data?.new ? <span className="ml-1.5 rounded-full bg-white/25 px-1.5">{stats.data.new}</span> : null}
          </button>
        ))}
      </div>

      {isNew && (
        <div className="card mb-4 p-4">
          <FindJobsButton />
        </div>
      )}

      {due.length > 0 && (
        <div className="mb-4 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          ⏰ {due.length} follow-up{due.length > 1 ? 's' : ''} due: {due.map((j) => j.company || j.title).join(', ')}
        </div>
      )}

      {(jobs.isPending || active === null) && <Empty>Loading…</Empty>}
      {jobs.isError && <Empty>Error: {jobs.error.message}</Empty>}
      {jobs.data?.length === 0 && (
        <Empty>
          {isNew ? (
            <>No new jobs right now. Tune your search in <Link to="/settings" className="text-indigo-500 underline">Settings</Link>, or search now.</>
          ) : (
            <>No jobs here yet. <Link to="/add" className="text-indigo-500 underline">Paste a job link</Link> to get started.</>
          )}
        </Empty>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {jobs.data?.map((j) => (
          <div key={j.id}>
            <JobCard job={j} />
            {j.status === 'new' && <NewJobActions job={j} />}
          </div>
        ))}
      </div>
    </>
  )
}
