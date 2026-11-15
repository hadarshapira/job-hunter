import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useDeferredValue, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isDue, SOURCES, sourceLabel, type CollectStatus, type JobSummary, type Status } from '../api'
import { Empty, JobCard, PageTitle } from '../components'

// Stages live in the Tracker; here just: what's new, what I kept, what I dismissed
const FILTERS: { label: string; statuses?: Status[] }[] = [
  { label: 'New for you', statuses: ['new'] },
  { label: 'My jobs', statuses: ['saved', 'applied', 'screening', 'interview', 'offer'] },
  { label: 'Not for me', statuses: ['archived'] },
  { label: 'All' },
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
    // Give up waiting after 8 minutes
    if (requestedAt && Date.now() - requestedAt > 480_000) setRequestedAt(null)
  }, [requestedAt, ours, d, qc])

  const s = status.data
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn-primary" disabled={running} onClick={() => start.mutate()}>
          {running ? <><span className="h-4 w-4 animate-spin rounded-full border-2 border-on-primary/40 border-t-on-primary" /> Searching…</> : '🔍 Find jobs now'}
        </button>
        {s?.last_finished && !running && (
          <span className="text-sm text-muted">
            Last search {timeAgo(s.last_finished)}: {s.last_added === 0 ? 'nothing new' : `${s.last_added} new job${s.last_added === 1 ? '' : 's'}`}
          </span>
        )}
      </div>
      {start.isError && <p className="text-sm text-danger">{start.error.message}</p>}
      {running && <p className="text-xs text-muted">Checking LinkedIn, company career pages and the web. LinkedIn is read slowly to avoid being blocked, so this can take a few minutes.</p>}
      {s && !s.jsearch_enabled && <p className="text-xs text-muted">Web search (JSearch) is off; only company career pages are searched.</p>}
      {s?.jsearch_quota_left != null && <p className="text-xs text-muted">Web searches left this month (shared): {s.jsearch_quota_left}</p>}
      {!running && s?.last_stats && <SearchReport stats={s.last_stats} />}
      {!running && s?.last_errors.length ? (
        <details className="text-xs text-warn">
          <summary>{s.last_errors.length} source{s.last_errors.length > 1 ? 's' : ''} had problems</summary>
          <ul className="mt-1 list-inside list-disc">{s.last_errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </details>
      ) : null}
    </div>
  )
}

const SKIP_LABEL: [string, string][] = [
  ['title', 'title not in your list'],
  ['location', 'too far / work mode'],
  ['already_have', 'already in your jobs'],
  ['duplicate', 'same job from another source'],
]

/** What the last search found per source, and why jobs were left out */
function SearchReport({ stats }: { stats: NonNullable<CollectStatus['last_stats']> }) {
  const li = stats.linkedin ?? {}
  const rows = SOURCES.filter((s) => stats.sources[s.value]).map((s) => {
    const n = stats.sources[s.value]
    // LinkedIn jobs with other titles are dropped before their page is read, so add them back here
    const titleSkip = (n.title ?? 0) + (s.value === 'linkedin' ? li.linkedin_title_skip ?? 0 : 0)
    const found = (n.found ?? 0) + (s.value === 'linkedin' ? li.linkedin_title_skip ?? 0 : 0)
    const counts: Record<string, number> = { ...n, title: titleSkip }
    const left = SKIP_LABEL.filter(([k]) => counts[k] > 0).map(([k, label]) => `${counts[k]} ${label}`).join(' · ')
    return { s, found, added: n.added ?? 0, left }
  })
  if (!rows.length) return null
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-muted">Last search report</summary>
      <div className="mt-2 overflow-x-auto rounded-xl border border-line">
        <table className="w-full">
          <thead className="bg-surface-2 text-left text-muted">
            <tr>
              <th className="px-2 py-1.5 font-medium">Source</th>
              <th className="px-2 py-1.5 font-medium">Found</th>
              <th className="px-2 py-1.5 font-medium">New</th>
              <th className="px-2 py-1.5 font-medium">Left out</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.s.value} className="border-t border-line align-top">
                <td className="px-2 py-1.5">{r.s.label}</td>
                <td className="px-2 py-1.5 tabular-nums">{r.found}</td>
                <td className="px-2 py-1.5 font-medium tabular-nums text-ok">{r.added}</td>
                <td className="px-2 py-1.5 text-muted">{r.left || '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {li.linkedin_deferred ? <p className="mt-1 text-muted">{li.linkedin_deferred} more LinkedIn jobs will be read in the next search.</p> : null}
      <p className="mt-1 text-muted">To get more jobs, add titles or widen the distance in <Link to="/settings" className="underline">Settings</Link>.</p>
    </details>
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
  const profile = useQuery({ queryKey: ['profile'], queryFn: api.profile })
  const [filter, setFilter] = useState<number | null>(null)
  // Open on "New for you" when there are new jobs, otherwise on "Active"
  const active = filter ?? (stats.data ? (stats.data.new > 0 ? 0 : 1) : null)
  const [q, setQ] = useState('')
  const query = useDeferredValue(q)
  const [sort, setSortState] = useState<'match' | 'recent'>(() => {
    try { return localStorage.getItem('jobs-sort') === 'recent' ? 'recent' : 'match' } catch { return 'match' }
  })
  const setSort = (s: 'match' | 'recent') => {
    setSortState(s)
    try { localStorage.setItem('jobs-sort', s) } catch { /* private mode */ }
  }
  const [source, setSource] = useState<string | null>(null)
  // Under the 'jobs' key so every place that refreshes the list refreshes the counts too
  const counts = useQuery({
    queryKey: ['jobs', 'sources', active, query],
    queryFn: () => api.jobSources({ status: FILTERS[active!].statuses, q: query || undefined }),
    enabled: active !== null,
  })
  const jobs = useQuery({
    queryKey: ['jobs', active, query, sort, source],
    queryFn: () => api.jobs({ status: FILTERS[active!].statuses, q: query || undefined, sort, source: source ?? undefined }),
    enabled: active !== null,
  })
  const due = jobs.data?.filter((j) => isDue(j.follow_up_on)) ?? []
  const isNew = active === 0

  return (
    <>
      <PageTitle right={<Link to="/add" className="btn-primary hidden md:inline-flex">+ Add job</Link>}>Jobs</PageTitle>
      <input className="input mb-3" placeholder="Search title or company…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="mb-4 flex flex-wrap gap-2">
        {FILTERS.map((f, i) => (
          <button
            key={f.label}
            onClick={() => setFilter(i)}
            aria-pressed={i === active}
            className={`pill border px-3 py-1.5 text-sm ${i === active ? 'border-primary bg-primary text-on-primary' : 'border-line'}`}
          >
            {f.label}
            {i === 0 && stats.data?.new ? <span className="ml-1.5 rounded-full bg-on-primary/20 px-1.5">{stats.data.new}</span> : null}
          </button>
        ))}
        <select
          aria-label="Sort jobs"
          className="ml-auto rounded-full border border-line bg-surface px-3 py-1.5 text-sm"
          value={sort}
          onChange={(e) => setSort(e.target.value as 'match' | 'recent')}
        >
          <option value="match">Best match first</option>
          <option value="recent">Newest first</option>
        </select>
      </div>

      {counts.data && Object.keys(counts.data).length > 0 && (
        <div className="-mt-2 mb-4 flex gap-2 overflow-x-auto pb-1 text-xs">
          {[null, ...SOURCES.map((s) => s.value).filter((v) => counts.data[v] || v === source),
            ...Object.keys(counts.data).filter((v) => !SOURCES.some((s) => s.value === v))].map((v) => {
            const n = v === null ? Object.values(counts.data).reduce((a, b) => a + b, 0) : counts.data[v] ?? 0
            const on = v === source
            return (
              <button
                key={v ?? 'all'}
                onClick={() => setSource(v)}
                aria-pressed={on}
                className={`pill shrink-0 border px-2.5 py-1 ${on ? 'border-primary bg-primary-soft text-primary' : 'border-line text-muted'}`}
              >
                {v === null ? 'All sources' : sourceLabel(v)} <span className="ml-1 tabular-nums opacity-80">{n}</span>
              </button>
            )
          })}
        </div>
      )}

      {profile.data && !profile.data.skills.length && profile.data.years_experience == null && (
        <div className="mb-4 rounded-2xl border border-primary/40 bg-primary-soft p-3 text-sm">
          📄 <Link to="/settings" className="font-medium text-primary underline">Upload your CV</Link> to see a match grade on every job.
        </div>
      )}

      {isNew && (
        <div className="card mb-4 p-4">
          <FindJobsButton />
        </div>
      )}

      {due.length > 0 && (
        <div className="mb-4 rounded-2xl border border-warn/40 bg-warn/10 p-3 text-sm">
          ⏰ {due.length} follow-up{due.length > 1 ? 's' : ''} due: {due.map((j) => j.company || j.title).join(', ')}
        </div>
      )}

      {(jobs.isPending || active === null) && <Empty>Loading…</Empty>}
      {jobs.isError && <Empty>Error: {jobs.error.message}</Empty>}
      {jobs.data?.length === 0 && (
        <Empty>
          {isNew ? (
            <>No new jobs right now. Tune your search in <Link to="/settings" className="text-primary underline">Settings</Link>, or search now.</>
          ) : (
            <>No jobs here yet. <Link to="/add" className="text-primary underline">Paste a job link</Link> to get started.</>
          )}
        </Empty>
      )}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {jobs.data?.map((j) => (
          <div key={j.id} className="min-w-0">
            <JobCard job={j} />
            {j.status === 'new' && <NewJobActions job={j} />}
          </div>
        ))}
      </div>
    </>
  )
}
