import { Link } from 'react-router-dom'
import { fmtDate, isDue, sourceLabel, statusInfo, WORK_MODES, type JobSummary } from './api'

export function StatusPill({ status }: { status: string }) {
  const s = statusInfo(status)
  return <span className={`pill ${s.tone}`}>{s.label}</span>
}

/** Grade bands: 75+ strong, 55-74 worth a look, below 55 weak */
export const matchTone = (score: number) =>
  score >= 75 ? 'bg-ok/15 text-ok border-ok/40' : score >= 55 ? 'bg-warn/15 text-warn border-warn/40' : 'bg-danger/10 text-danger border-danger/30'
export const matchWord = (score: number) => (score >= 75 ? 'Strong match' : score >= 55 ? 'Partial match' : 'Weak match')

export function MatchBadge({ score, large = false }: { score: number | null; large?: boolean }) {
  if (score == null) return null
  return (
    <span
      title={`${matchWord(score)} for your profile`}
      className={`inline-grid shrink-0 place-items-center rounded-full border font-semibold tabular-nums ${matchTone(score)} ${large ? 'h-16 w-16 text-2xl' : 'h-9 w-9 text-sm'}`}
    >
      {score}
    </span>
  )
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
        <div className="flex shrink-0 items-center gap-2">
          {!compact && job.status !== 'new' && <StatusPill status={job.status} />}
          <MatchBadge score={job.match_score} />
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted">
        {mode && job.work_mode !== 'unknown' && <span className="pill bg-surface-2">{mode.label}</span>}
        {job.distance_km != null && <span className="pill bg-surface-2">📍 {Math.round(job.distance_km)} km</span>}
        {job.salary && <span className="pill bg-surface-2">{job.salary}</span>}
        {due && <span className="pill bg-warn/15 text-warn">Follow up {fmtDate(job.follow_up_on)}</span>}
        {!compact && <span className="ml-auto">{sourceLabel(job.source)}</span>}
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
