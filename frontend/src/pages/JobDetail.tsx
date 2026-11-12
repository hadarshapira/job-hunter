import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, STATUSES, WORK_MODES, type Job } from '../api'
import { Empty, StatusPill } from '../components'

const EVENT_ICON: Record<string, string> = { created: '✨', status: '➜', note: '📝', email: '✉️' }

export default function JobDetail() {
  const id = Number(useParams().id)
  const qc = useQueryClient()
  const nav = useNavigate()
  const note = (useLocation().state as { note?: string } | null)?.note
  const job = useQuery({ queryKey: ['job', id], queryFn: () => api.job(id) })

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Partial<Job>>({})
  const [newNote, setNewNote] = useState('')
  const [showDesc, setShowDesc] = useState(false)

  useEffect(() => {
    if (job.data && note && !job.data.company) setEditing(true)
  }, [job.data, note])

  const onSaved = (j: Job) => {
    qc.setQueryData(['job', id], j)
    qc.invalidateQueries({ queryKey: ['jobs'] })
    qc.invalidateQueries({ queryKey: ['stats'] })
  }
  const update = useMutation({ mutationFn: (body: Partial<Job>) => api.updateJob(id, body), onSuccess: onSaved })
  const addNote = useMutation({
    mutationFn: (text: string) => api.addNote(id, text),
    onSuccess: (j) => {
      onSaved(j)
      setNewNote('')
    },
  })
  const reimport = useMutation({ mutationFn: () => api.reimportJob(id), onSuccess: (r) => onSaved(r.job) })
  const remove = useMutation({
    mutationFn: () => api.deleteJob(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
      nav('/')
    },
  })

  if (job.isPending) return <Empty>Loading…</Empty>
  if (job.isError) return <Empty>Error: {job.error.message}</Empty>
  const j = job.data

  const field = (k: keyof Job) => (draft[k] ?? j[k] ?? '') as string
  const setField = (k: keyof Job) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setDraft({ ...draft, [k]: e.target.value })

  return (
    <div className="grid gap-4">
      <Link to="/" className="text-sm text-muted">← Back</Link>
      {note && !j.parse_issues && <div className="rounded-2xl border border-primary/40 bg-primary-soft p-3 text-sm">{note}</div>}
      {j.parse_issues && (
        <div className="rounded-2xl border border-warn/40 bg-warn/10 p-3 text-sm">
          <p className="font-medium">Some details couldn't be read from the job page:</p>
          <ul className="mt-1 list-inside list-disc text-ink/80">
            {j.parse_issues.split('\n').map((i) => <li key={i}>{i}</li>)}
          </ul>
          <div className="mt-3 flex flex-wrap gap-2">
            {j.url && (
              <button className="btn-primary" disabled={reimport.isPending} onClick={() => reimport.mutate()}>
                {reimport.isPending ? 'Retrying…' : 'Retry import'}
              </button>
            )}
            <button className="btn-ghost" onClick={() => setEditing(true)}>Fill in manually</button>
          </div>
          {reimport.isError && <p className="mt-2 text-danger">{reimport.error.message}</p>}
          {reimport.isSuccess && j.parse_issues && <p className="mt-2 text-muted">Still incomplete. This site may need a dedicated reader.</p>}
        </div>
      )}

      <div className="card p-4">
        {editing ? (
          <form
            className="grid gap-3 sm:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault()
              update.mutate(draft, { onSuccess: () => { setEditing(false); setDraft({}) } })
            }}
          >
            <input className="input sm:col-span-2" value={field('title')} onChange={setField('title')} placeholder="Title" required />
            <input className="input" value={field('company')} onChange={setField('company')} placeholder="Company" />
            <input className="input" value={field('location')} onChange={setField('location')} placeholder="Location" />
            <select className="input" value={field('work_mode')} onChange={setField('work_mode')}>
              {WORK_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
            <input className="input" value={field('salary')} onChange={setField('salary')} placeholder="Salary" />
            <textarea className="input min-h-40 sm:col-span-2" value={field('description')} onChange={setField('description')} placeholder="Description" />
            <div className="flex gap-2 sm:col-span-2">
              <button className="btn-primary" disabled={update.isPending}>Save</button>
              <button type="button" className="btn-ghost" onClick={() => { setEditing(false); setDraft({}) }}>Cancel</button>
            </div>
          </form>
        ) : (
          <>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h1 className="text-xl font-semibold">{j.title}</h1>
                <p className="text-muted">{[j.company, j.location].filter(Boolean).join(' · ')}</p>
              </div>
              <StatusPill status={j.status} />
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-sm">
              {j.work_mode !== 'unknown' && <span className="pill bg-surface-2">{WORK_MODES.find((m) => m.value === j.work_mode)?.label}</span>}
              {j.salary && <span className="pill bg-surface-2">{j.salary}</span>}
              {j.posted_at && <span className="pill bg-surface-2">Posted {j.posted_at}</span>}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {j.url && <a href={j.url} target="_blank" rel="noreferrer" className="btn-primary">Open posting ↗</a>}
              <button className="btn-ghost" onClick={() => setEditing(true)}>Edit</button>
              {j.url && !j.parse_issues && (
                <button className="btn-ghost" disabled={reimport.isPending} onClick={() => reimport.mutate()}>
                  {reimport.isPending ? 'Refreshing…' : 'Refresh from link'}
                </button>
              )}
            </div>
          </>
        )}
      </div>

      <div className="card grid gap-3 p-4 sm:grid-cols-3">
        <label className="text-sm">
          <span className="mb-1 block text-muted">Status</span>
          <select className="input" value={j.status} onChange={(e) => update.mutate({ status: e.target.value as Job['status'] })}>
            {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-muted">Follow up on</span>
          <input className="input" type="date" value={j.follow_up_on ?? ''} onChange={(e) => update.mutate({ follow_up_on: e.target.value || null })} />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-muted">Contact / recruiter</span>
          <input
            className="input"
            defaultValue={j.contact}
            key={j.contact}
            placeholder="Name, email, phone"
            onBlur={(e) => e.target.value !== j.contact && update.mutate({ contact: e.target.value })}
          />
        </label>
        {update.isError && <p className="text-sm text-danger sm:col-span-3">{update.error.message}</p>}
      </div>

      {j.description && (
        <div className="card p-4">
          <button className="flex w-full items-center justify-between font-medium" onClick={() => setShowDesc(!showDesc)}>
            Job description <span className="text-muted">{showDesc ? '−' : '+'}</span>
          </button>
          {showDesc && <div className="mt-3 whitespace-pre-line text-sm leading-relaxed text-ink/80">{j.description}</div>}
        </div>
      )}

      <div className="card p-4">
        <h2 className="mb-3 font-medium">Timeline</h2>
        <form
          className="mb-4 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (newNote.trim()) addNote.mutate(newNote)
          }}
        >
          <input className="input" placeholder="Add a note…" value={newNote} onChange={(e) => setNewNote(e.target.value)} />
          <button className="btn-primary shrink-0" disabled={addNote.isPending || !newNote.trim()}>Add</button>
        </form>
        <ol className="grid gap-3">
          {j.events.map((ev) => (
            <li key={ev.id} className="flex gap-3 text-sm">
              <span className="w-5 shrink-0 text-center">{EVENT_ICON[ev.kind] ?? '•'}</span>
              <div className="min-w-0">
                <div className="whitespace-pre-line">{ev.text}</div>
                <div className="text-xs text-muted">{new Date(ev.created_at).toLocaleString()}</div>
              </div>
            </li>
          ))}
        </ol>
      </div>

      <button
        className="justify-self-start text-sm text-danger"
        onClick={() => confirm('Delete this job and its timeline?') && remove.mutate()}
      >
        Delete job
      </button>
    </div>
  )
}
