import { Link } from 'react-router-dom'
import { fmtDate, isDue, statusInfo, WORK_MODES, type JobSummary } from './api'

export function StatusPill({ status }: { status: string }) {
  const s = statusInfo(status)
  return <span className={`pill ${s.tone}`}>{s.label}</span>
}

const SOURCE_LABEL: Record<string, string> = {
  jsearch: 'Web search',
  greenhouse: 'Career page',
  lever: 'Career page',
  ashby: 'Career page',
  link: 'Your link',
  manual: 'Added by you',
}

export function JobCard({ job, compact = false }: { job: JobSummary; compact?: boolean }) {
  const mode = WORK_MODES.find((m) => m.value === job.work_mode)
  const due = isDue(job.follow_up_on)
  return (
    <Link to={`/jobs/${job.id}`} className="card block p-4 transition hover:border-primary/60">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-medium">{job.title}</div>
          <div className="truncate text-sm text-muted">
            {[job.company, job.location].filter(Boolean).join(' · ') || 'Unknown company'}
          </div>
        </div>
        {!compact && <StatusPill status={job.status} />}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted">
        {mode && job.work_mode !== 'unknown' && <span className="pill bg-surface-2">{mode.label}</span>}
        {job.distance_km != null && <span className="pill bg-surface-2">📍 {Math.round(job.distance_km)} km</span>}
        {job.salary && <span className="pill bg-surface-2">{job.salary}</span>}
        {due && <span className="pill bg-warn/15 text-warn">Follow up {fmtDate(job.follow_up_on)}</span>}
        {!compact && <span className="ml-auto">{SOURCE_LABEL[job.source] ?? job.source}</span>}
      </div>
    </Link>
  )
}

export function PageTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h1 className="text-2xl font-semibold tracking-tight">{children}</h1>
      {right}
    </div>
  )
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="card p-8 text-center text-sm text-muted">{children}</div>
}
