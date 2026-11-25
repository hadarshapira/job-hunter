import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useDeferredValue, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isDue, SOURCES, sourceLabel, type CollectStatus, type CompanyFilter, type JobSummary, type Status } from '../api'
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
      {running && <p className="text-xs text-muted">First checks that the jobs in your list are still open, then searches LinkedIn, company career pages and the web. LinkedIn is read slowly to avoid being blocked, so this can take a few minutes.</p>}
      {s && !s.jsearch_enabled && <p className="text-xs text-muted">Web search (JSearch) is off; only company career pages are searched.</p>}
      {s?.jsearch_quota_left != null && <p className="text-xs text-muted">Web searches left this month (shared): {s.jsearch_quota_left}</p>}
      {!running && s?.last_stats?.closed && <ClosedReport closed={s.last_stats.closed} />}
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

/** Jobs removed from the list because their posting is closed */
function ClosedReport({ closed }: { closed: NonNullable<NonNullable<CollectStatus['last_stats']>['closed']> }) {
  if (!closed.removed) {
    return closed.checked ? <p className="text-xs text-muted">Checked {closed.checked} jobs in your list: all still open.</p> : null
  }
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-muted">
        Removed {closed.removed} closed job{closed.removed === 1 ? '' : 's'} (checked {closed.checked})
      </summary>
      <ul className="mt-1 list-inside list-disc text-muted">
        {closed.removed_jobs.map((j, i) => <li key={i}>{j.title}{j.company ? ` · ${j.company}` : ''}</li>)}
      </ul>
      {closed.linkedin_limited && <p className="mt-1 text-muted">LinkedIn asked to slow down; the rest will be checked next time.</p>}
    </details>
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

/** Short label for the company filter button */
function companyFilterLabel(f: CompanyFilter | undefined) {
  const n = f?.companies.length ?? 0
  if (!f?.mode || !n) return 'Companies'
  const what = n === 1 ? f.companies[0] : `${n} companies`
  return f.mode === 'only' ? `Only ${what}` : `Hiding ${what}`
}

/** Pick companies to see only, or to leave out. Saved on the account right away (phone and desktop share it). */
function CompanyPanel({ statuses, q, onClose }: { statuses?: Status[]; q?: string; onClose: () => void }) {
  const qc = useQueryClient()
  const saved = useQuery({ queryKey: ['company-filter'], queryFn: api.companyFilter })
  const companies = useQuery({
    queryKey: ['jobs', 'companies', statuses, q],
    queryFn: () => api.jobCompanies({ status: statuses, q }),
  })
  const [find, setFind] = useState('')
  const save = useMutation({
    mutationFn: api.saveCompanyFilter,
    onMutate: (f) => { qc.setQueryData<CompanyFilter>(['company-filter'], f) }, // tick boxes instantly
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['company-filter'] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    },
  })
  const f: CompanyFilter = saved.data ?? { mode: '', companies: [] }
  // Mode picked before any company is ticked lives here until the first tick saves it
  const [chosen, setChosen] = useState<'only' | 'hide'>('only')
  const mode = f.mode || chosen
  const setMode = (m: 'only' | 'hide') => {
    setChosen(m)
    if (f.companies.length) save.mutate({ mode: m, companies: f.companies })
  }
  const picked = new Set(f.companies.map((c) => c.toLowerCase()))
  const toggle = (name: string) => {
    const key = name.toLowerCase()
    const next = picked.has(key) ? f.companies.filter((c) => c.toLowerCase() !== key) : [...f.companies, name]
    save.mutate({ mode: next.length ? mode : '', companies: next })
  }
  // Picked companies that have no jobs in this view still appear, so they can be unticked
  const rows = [
    ...(companies.data ?? []),
    ...f.companies.filter((c) => !companies.data?.some((r) => r.name.toLowerCase() === c.toLowerCase())).map((name) => ({ name, count: 0 })),
  ].filter((r) => r.name.toLowerCase().includes(find.trim().toLowerCase()))

  return (
    <div className="card mb-4 p-3 text-sm">
      <div className="mb-2 flex items-center gap-2">
        <div role="group" aria-label="Company filter mode" className="flex rounded-full border border-line p-0.5 text-xs">
          {(['only', 'hide'] as const).map((m) => (
            <button
              key={m}
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-full px-3 py-1 ${mode === m ? 'bg-primary text-on-primary' : 'text-muted'}`}
            >
              {m === 'only' ? 'Show only ticked' : 'Hide ticked'}
            </button>
          ))}
        </div>
        {f.companies.length > 0 && (
          <button className="text-xs text-primary underline" onClick={() => save.mutate({ mode: '', companies: [] })}>Clear</button>
        )}
        <button className="ml-auto text-xs text-muted" onClick={onClose} aria-label="Close company filter">Done</button>
      </div>
      <input className="input mb-2 py-1.5" placeholder="Find a company…" value={find} onChange={(e) => setFind(e.target.value)} />
      {companies.isPending && <p className="text-muted">Loading…</p>}
      {companies.data && rows.length === 0 && <p className="text-muted">No companies here.</p>}
      <ul className="max-h-72 overflow-y-auto">
        {rows.map((r) => (
          <li key={r.name.toLowerCase()}>
            <label className="flex cursor-pointer items-center gap-2 rounded-lg px-1 py-1.5 hover:bg-surface-2">
              <input type="checkbox" checked={picked.has(r.name.toLowerCase())} onChange={() => toggle(r.name)} />
              <span className="min-w-0 flex-1 truncate">{r.name}</span>
              <span className="tabular-nums text-xs text-muted">{r.count}</span>
            </label>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">Saved to your account, so it applies on your phone and computer, in every tab.</p>
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
  const companyFilter = useQuery({ queryKey: ['company-filter'], queryFn: api.companyFilter })
  const [companiesOpen, setCompaniesOpen] = useState(false)
  const companyOn = !!companyFilter.data?.mode && companyFilter.data.companies.length > 0
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
        <button
          onClick={() => setCompaniesOpen((o) => !o)}
          aria-expanded={companiesOpen}
          className={`pill ml-auto max-w-[14rem] truncate border px-3 py-1.5 text-sm ${companyOn ? 'border-primary bg-primary-soft text-primary' : 'border-line'}`}
        >
          🏢 {companyFilterLabel(companyFilter.data)}
        </button>
        <select
          aria-label="Sort jobs"
          className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm"
          value={sort}
          onChange={(e) => setSort(e.target.value as 'match' | 'recent')}
        >
          <option value="match">Best match first</option>
          <option value="recent">Newest first</option>
        </select>
      </div>

      {companiesOpen && active !== null && (
        <CompanyPanel statuses={FILTERS[active].statuses} q={query || undefined} onClose={() => setCompaniesOpen(false)} />
      )}

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
      {jobs.data?.length === 0 && companyOn && (
        <Empty>
          No jobs here with the company filter ({companyFilterLabel(companyFilter.data)}).{' '}
          <button className="text-primary underline" onClick={() => setCompaniesOpen(true)}>Change it</button>
        </Empty>
      )}
      {jobs.data?.length === 0 && !companyOn && (
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
