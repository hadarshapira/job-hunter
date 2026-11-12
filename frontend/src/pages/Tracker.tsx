import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, STATUSES, type JobSummary, type Status } from '../api'
import { JobCard, PageTitle } from '../components'

const COLUMNS: Status[] = ['saved', 'applied', 'screening', 'interview', 'offer', 'rejected', 'ghosted']

export default function Tracker() {
  const qc = useQueryClient()
  const jobs = useQuery({ queryKey: ['jobs', 'tracker'], queryFn: () => api.jobs({ status: COLUMNS }) })
  const move = useMutation({
    mutationFn: ({ id, status }: { id: number; status: Status }) => api.updateJob(id, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
    },
  })

  const byStatus = (s: Status) => (jobs.data ?? []).filter((j) => j.status === s)

  return (
    <>
      <PageTitle>Tracker</PageTitle>
      {/* Swipe sideways between columns on the phone; all columns visible on desktop */}
      <div className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-4 md:mx-0 md:px-0">
        {COLUMNS.map((s) => {
          const info = STATUSES.find((x) => x.value === s)!
          const items = byStatus(s)
          return (
            <section key={s} className="w-[85vw] max-w-xs shrink-0 snap-start rounded-2xl bg-zinc-100 p-3 md:w-64 dark:bg-zinc-900/60">
              <h2 className="mb-3 flex items-center justify-between text-sm font-medium">
                <span className={`pill ${info.tone}`}>{info.label}</span>
                <span className="text-zinc-500">{items.length}</span>
              </h2>
              <div className="grid gap-2">
                {items.map((j) => <TrackerCard key={j.id} job={j} onMove={(status) => move.mutate({ id: j.id, status })} />)}
                {items.length === 0 && <p className="py-6 text-center text-xs text-zinc-500">Empty</p>}
              </div>
            </section>
          )
        })}
      </div>
    </>
  )
}

function TrackerCard({ job, onMove }: { job: JobSummary; onMove: (s: Status) => void }) {
  return (
    <div className="grid gap-1.5">
      <JobCard job={job} compact />
      <select
        aria-label="Move to"
        className="rounded-lg border border-zinc-300 bg-transparent px-2 py-1 text-xs dark:border-zinc-700"
        value=""
        onChange={(e) => e.target.value && onMove(e.target.value as Status)}
      >
        <option value="">Move to…</option>
        {STATUSES.filter((s) => s.value !== job.status && s.value !== 'new').map((s) => (
          <option key={s.value} value={s.value}>{s.label}</option>
        ))}
      </select>
    </div>
  )
}
