import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, WORK_MODES, type WorkMode } from '../api'
import { PageTitle } from '../components'

export default function AddJob() {
  const qc = useQueryClient()
  const nav = useNavigate()
  const [params] = useSearchParams()
  // Android share sheets often put the link inside "text" instead of "url"
  const shared = params.get('url') || params.get('text')?.match(/https?:\/\/\S+/)?.[0] || ''
  const [url, setUrl] = useState(shared)
  const [manual, setManual] = useState(false)
  const [form, setForm] = useState({ title: '', company: '', location: '', work_mode: 'unknown' as WorkMode, url: '', description: '' })

  const done = (id: number, note?: string) => {
    qc.invalidateQueries({ queryKey: ['jobs'] })
    nav(`/jobs/${id}`, { state: { note } })
  }

  const importJob = useMutation({
    mutationFn: api.importJob,
    onSuccess: (r) =>
      done(
        r.job.id,
        r.duplicate
          ? 'You already have this job. Opened the existing one.'
          : r.complete
            ? undefined
            : "This page didn't include full job details. Please check the title, company and location.",
      ),
  })
  const createJob = useMutation({ mutationFn: api.createJob, onSuccess: (j) => done(j.id) })

  // Shared from another app (Android share sheet) or pasted into ?url=
  useEffect(() => {
    if (shared) importJob.mutate(shared)
  }, [])

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.value })

  return (
    <>
      <PageTitle>Add a job</PageTitle>

      <form
        className="card p-4"
        onSubmit={(e) => {
          e.preventDefault()
          importJob.mutate(url.trim())
        }}
      >
        <label className="mb-1.5 block text-sm font-medium">Paste a job link</label>
        <p className="mb-3 text-xs text-zinc-500">LinkedIn, Greenhouse, Lever, Comeet, company career pages… any link.</p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input className="input" type="url" inputMode="url" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} required />
          <button className="btn-primary shrink-0" disabled={importJob.isPending}>
            {importJob.isPending ? 'Importing…' : 'Import'}
          </button>
        </div>
        {importJob.isError && <p className="mt-2 text-sm text-rose-500">{importJob.error.message}</p>}
      </form>

      <button className="mt-4 text-sm text-indigo-500 underline" onClick={() => setManual(!manual)}>
        {manual ? 'Hide manual form' : 'Or enter the details manually'}
      </button>

      {manual && (
        <form
          className="card mt-3 grid gap-3 p-4 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            createJob.mutate({ ...form, url: form.url || null })
          }}
        >
          <input className="input sm:col-span-2" placeholder="Job title *" value={form.title} onChange={set('title')} required />
          <input className="input" placeholder="Company" value={form.company} onChange={set('company')} />
          <input className="input" placeholder="Location (city)" value={form.location} onChange={set('location')} />
          <select className="input" value={form.work_mode} onChange={set('work_mode')}>
            {WORK_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
          <input className="input" placeholder="Link (optional)" value={form.url} onChange={set('url')} />
          <textarea className="input min-h-32 sm:col-span-2" placeholder="Job description" value={form.description} onChange={set('description')} />
          {createJob.isError && <p className="text-sm text-rose-500 sm:col-span-2">{createJob.error.message}</p>}
          <button className="btn-primary sm:col-span-2" disabled={createJob.isPending}>Save job</button>
        </form>
      )}
    </>
  )
}
