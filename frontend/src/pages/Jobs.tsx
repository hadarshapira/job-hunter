import { useQuery } from '@tanstack/react-query'
import { useDeferredValue, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, isDue, STATUSES, type Status } from '../api'
import { Empty, JobCard, PageTitle } from '../components'

const FILTERS: { label: string; statuses?: Status[] }[] = [
  { label: 'Active', statuses: ['new', 'saved', 'applied', 'screening', 'interview', 'offer'] },
  { label: 'All' },
  ...STATUSES.filter((s) => s.value !== 'new').map((s) => ({ label: s.label, statuses: [s.value] })),
]

export default function Jobs() {
  const [filter, setFilter] = useState(0)
  const [q, setQ] = useState('')
  const query = useDeferredValue(q)
  const jobs = useQuery({
    queryKey: ['jobs', filter, query],
    queryFn: () => api.jobs({ status: FILTERS[filter].statuses, q: query || undefined }),
  })
  const due = jobs.data?.filter((j) => isDue(j.follow_up_on)) ?? []

  return (
    <>
      <PageTitle right={<Link to="/add" className="btn-primary hidden md:inline-flex">+ Add job</Link>}>Jobs</PageTitle>
      <input className="input mb-3" placeholder="Search title or company…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
        {FILTERS.map((f, i) => (
          <button
            key={f.label}
            onClick={() => setFilter(i)}
            className={`pill shrink-0 border px-3 py-1.5 text-sm ${i === filter ? 'border-indigo-600 bg-indigo-600 text-white' : 'border-zinc-300 dark:border-zinc-700'}`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {due.length > 0 && (
        <div className="mb-4 rounded-2xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          ⏰ {due.length} follow-up{due.length > 1 ? 's' : ''} due: {due.map((j) => j.company || j.title).join(', ')}
        </div>
      )}

      {jobs.isPending && <Empty>Loading…</Empty>}
      {jobs.isError && <Empty>Error: {jobs.error.message}</Empty>}
      {jobs.data?.length === 0 && (
        <Empty>
          No jobs here yet. <Link to="/add" className="text-indigo-500 underline">Paste a job link</Link> to get started.
        </Empty>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {jobs.data?.map((j) => <JobCard key={j.id} job={j} />)}
      </div>
    </>
  )
}
