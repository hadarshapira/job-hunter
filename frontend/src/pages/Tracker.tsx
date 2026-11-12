import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isDue, statusInfo, STATUSES, type JobSummary, type Status } from '../api'
import { Empty, PageTitle } from '../components'

// Pipeline order. Open stages are shown as sections; closed ones are folded away at the bottom.
const OPEN: Status[] = ['saved', 'applied', 'screening', 'interview', 'offer']
const CLOSED: Status[] = ['rejected', 'ghosted']
const MOVE_TO = STATUSES.filter((s) => s.value !== 'new')

const daysSince = (iso: string) => Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000))
const ago = (d: number) => (d === 0 ? 'today' : d === 1 ? 'yesterday' : `${d} days ago`)

/** The one thing worth knowing next about this application. */
function nextInfo(j: JobSummary): { text: string; tone?: 'warn' } {
  if (isDue(j.follow_up_on)) return { text: 'Follow up today', tone: 'warn' }
  if (j.status === 'saved') return { text: `Saved ${ago(daysSince(j.created_at))}` }
  if (j.status === 'applied' && j.applied_at) {
    const d = daysSince(j.applied_at)
    return { text: `Applied ${ago(d)}`, tone: d >= 14 ? 'warn' : undefined }
  }
  return { text: `Updated ${ago(daysSince(j.updated_at))}` }
}

function PipelineBar({ counts, total }: { counts: Record<string, number>; total: number }) {
  if (!total) return null
  return (
    <div className="flex h-2.5 overflow-hidden rounded-full bg-surface-2" role="img" aria-label="Pipeline by stage">
      {[...OPEN, ...CLOSED].map((s) =>
        counts[s] ? <div key={s} className={`tone-solid tone-${s}`} style={{ width: `${(counts[s] / total) * 100}%` }} /> : null,
      )}
    </div>
  )
}

function Row({ job, onMove }: { job: JobSummary; onMove: (s: Status) => void }) {
  const info = statusInfo(job.status)
  const next = nextInfo(job)
  return (
    <li className="flex items-center gap-3 px-4 py-3">
      <Link to={`/jobs/${job.id}`} className="min-w-0 flex-1">
        <div className="truncate font-medium">{job.title}</div>
        <div className="truncate text-sm text-muted">{[job.company, job.location.split(',')[0]].filter(Boolean).join(' · ')}</div>
        <div className={`mt-0.5 text-xs ${next.tone === 'warn' ? 'font-medium text-warn' : 'text-muted'}`}>{next.text}</div>
      </Link>
      {/* Stage changer: looks like the status pill, opens the phone's native picker */}
      <label className="relative shrink-0">
        <span className="sr-only">Stage for {job.title}</span>
        <select
          className={`pill cursor-pointer appearance-none py-1.5 pr-6 pl-3 text-xs ${info.tone}`}
          value={job.status}
          onChange={(e) => onMove(e.target.value as Status)}
        >
          {MOVE_TO.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </select>
        <span aria-hidden className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 text-[10px] opacity-70">▼</span>
      </label>
    </li>
  )
}

function Section({ status, jobs, onMove }: { status: Status; jobs: JobSummary[]; onMove: (id: number, s: Status) => void }) {
  const info = statusInfo(status)
  return (
    <section className="card overflow-hidden">
      <h2 className="flex items-center gap-2 border-b border-line px-4 py-2.5 text-sm font-medium">
        <span className={`h-2.5 w-2.5 rounded-full tone-solid tone-${status}`} />
        {info.label}
        <span className="text-muted">{jobs.length}</span>
      </h2>
      <ul className="divide-y divide-line">
        {jobs.map((j) => <Row key={j.id} job={j} onMove={(s) => onMove(j.id, s)} />)}
      </ul>
    </section>
  )
}

export default function Tracker() {
  const qc = useQueryClient()
  const [filter, setFilter] = useState<Status | 'open'>('open')
  const jobs = useQuery({ queryKey: ['jobs', 'tracker'], queryFn: () => api.jobs({ status: [...OPEN, ...CLOSED] }) })
  const move = useMutation({
    mutationFn: ({ id, status }: { id: number; status: Status }) => api.updateJob(id, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    },
  })
  const onMove = (id: number, status: Status) => move.mutate({ id, status })

  if (jobs.isPending) return <Empty>Loading…</Empty>
  if (jobs.isError) return <Empty>Error: {jobs.error.message}</Empty>

  const all = jobs.data
  const counts: Record<string, number> = {}
  for (const j of all) counts[j.status] = (counts[j.status] ?? 0) + 1
  const byStatus = (s: Status) => all.filter((j) => j.status === s)
  const openTotal = OPEN.reduce((n, s) => n + (counts[s] ?? 0), 0)
  const closedTotal = CLOSED.reduce((n, s) => n + (counts[s] ?? 0), 0)
  const due = all.filter((j) => isDue(j.follow_up_on))
  const shown = filter === 'open' ? OPEN : [filter]

  const chip = (value: Status | 'open', label: string, n: number) => (
    <button
      key={value}
      onClick={() => setFilter(value)}
      aria-pressed={filter === value}
      className={`rounded-full border px-3 py-1.5 text-sm ${filter === value ? 'border-primary bg-primary text-on-primary' : 'border-line'}`}
    >
      {label} <span className={filter === value ? 'opacity-80' : 'text-muted'}>{n}</span>
    </button>
  )

  return (
    <div className="mx-auto max-w-3xl">
      <PageTitle>Tracker</PageTitle>

      {all.length === 0 ? (
        <Empty>
          Nothing tracked yet. Save jobs from <Link to="/" className="text-primary underline">New for you</Link> or{' '}
          <Link to="/add" className="text-primary underline">add a job link</Link>.
        </Empty>
      ) : (
        <div className="grid gap-4">
          <div className="card grid gap-3 p-4">
            <div className="flex items-baseline justify-between text-sm">
              <span><b className="text-lg">{openTotal}</b> in progress</span>
              {due.length > 0 && <span className="font-medium text-warn">⏰ {due.length} follow-up{due.length > 1 ? 's' : ''} due</span>}
            </div>
            <PipelineBar counts={counts} total={openTotal + closedTotal} />
            {/* Stage filter: wraps onto more lines instead of scrolling sideways */}
            <div className="flex flex-wrap gap-2">
              {chip('open', 'All', openTotal)}
              {OPEN.map((s) => chip(s, statusInfo(s).label, counts[s] ?? 0))}
            </div>
          </div>

          {shown.map((s) => (byStatus(s).length ? <Section key={s} status={s} jobs={byStatus(s)} onMove={onMove} /> : null))}
          {filter !== 'open' && !byStatus(filter).length && <Empty>No jobs at the {statusInfo(filter).label} stage.</Empty>}
          {filter === 'open' && openTotal === 0 && <Empty>No applications in progress.</Empty>}

          {filter === 'open' && closedTotal > 0 && (
            <details className="card overflow-hidden">
              <summary className="cursor-pointer px-4 py-3 text-sm text-muted">Closed: {closedTotal} (rejected or no reply)</summary>
              <ul className="divide-y divide-line border-t border-line">
                {CLOSED.flatMap(byStatus).map((j) => <Row key={j.id} job={j} onMove={(s) => onMove(j.id, s)} />)}
              </ul>
            </details>
          )}
          {move.isError && <p className="text-sm text-danger">{move.error.message}</p>}
        </div>
      )}
    </div>
  )
}
