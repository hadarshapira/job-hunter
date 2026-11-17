import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, STATUSES, statusInfo, WORK_MODES, type Job, type Match } from '../api'
import { Empty, MatchBadge, matchWord } from '../components'

// One-tap move to the usual next stage
const NEXT_STEP: Partial<Record<Job['status'], { to: Job['status']; label: string }>> = {
  new: { to: 'saved', label: '★ Save' },
  saved: { to: 'applied', label: '✓ Mark as applied' },
  applied: { to: 'screening', label: '→ Screening' },
  screening: { to: 'interview', label: '→ Interview' },
  interview: { to: 'offer', label: '🎉 Got an offer' },
}

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
              <label className="shrink-0">
                <span className="sr-only">Status</span>
                <select
                  className={`pill cursor-pointer appearance-none border-0 py-1.5 pl-3 pr-7 text-sm font-medium ${statusInfo(j.status).tone}`}
                  style={{ backgroundImage: 'linear-gradient(45deg, transparent 50%, currentColor 50%), linear-gradient(135deg, currentColor 50%, transparent 50%)', backgroundPosition: 'right 12px center, right 8px center', backgroundSize: '4px 4px', backgroundRepeat: 'no-repeat' }}
                  value={j.status}
                  disabled={update.isPending}
                  onChange={(e) => update.mutate({ status: e.target.value as Job['status'] })}
                >
                  {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </label>
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-sm">
              {j.work_mode !== 'unknown' && <span className="pill bg-surface-2">{WORK_MODES.find((m) => m.value === j.work_mode)?.label}</span>}
              {j.salary && <span className="pill bg-surface-2">{j.salary}</span>}
              {j.posted_at && <span className="pill bg-surface-2">Posted {j.posted_at}</span>}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {NEXT_STEP[j.status] && (
                <button className="btn-primary" disabled={update.isPending} onClick={() => update.mutate({ status: NEXT_STEP[j.status]!.to })}>
                  {NEXT_STEP[j.status]!.label}
                </button>
              )}
              {j.status !== 'archived' && j.status !== 'rejected' && (
                <button className="btn-ghost" disabled={update.isPending} onClick={() => update.mutate({ status: j.status === 'new' ? 'archived' : 'rejected' })}>
                  {j.status === 'new' ? '✕ Not for me' : '✕ Rejected'}
                </button>
              )}
              {j.url && <a href={j.url} target="_blank" rel="noreferrer" className={NEXT_STEP[j.status] ? 'btn-ghost' : 'btn-primary'}>Open posting ↗</a>}
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

      <MatchCard job={j} onSaved={onSaved} />

      <div className="card grid gap-3 p-4 sm:grid-cols-2">
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
        {update.isError && <p className="text-sm text-danger sm:col-span-2">{update.error.message}</p>}
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
                {ev.url && <a href={ev.url} target="_blank" rel="noreferrer" className="text-xs text-primary underline">Open in Gmail</a>}
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

const SKILL_STATUS = {
  have: { icon: '✓', label: 'You have it', cls: 'text-ok' },
  similar: { icon: '≈', label: 'Similar', cls: 'text-warn' },
  missing: { icon: '✗', label: 'Missing', cls: 'text-danger' },
} as const

const VERDICT = { strong: 'Strong fit', good: 'Good fit', stretch: 'A stretch', poor: 'Poor fit' } as const

function MatchCard({ job, onSaved }: { job: Job; onSaved: (j: Job) => void }) {
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const recalc = useMutation({ mutationFn: () => api.rematch(job.id), onSuccess: onSaved })
  const askAi = useMutation({ mutationFn: () => api.aiMatch(job.id), onSuccess: onSaved })
  const ai = job.ai_match
  const aiCurrent = ai && ai.score != null && !ai.stale
  const aiAvailable = settings.data?.ai_available

  const aiButton = aiAvailable && (
    <button className="btn-ghost shrink-0" disabled={askAi.isPending} onClick={() => askAi.mutate()}>
      {askAi.isPending ? 'AI is reading…' : aiCurrent ? '↻ Ask AI again' : '✨ Grade with AI'}
    </button>
  )
  const aiProblems = (
    <>
      {askAi.isError && <p className="text-sm text-danger">{askAi.error.message}</p>}
      {ai?.error && !ai.stale && <p className="text-sm text-warn">AI grade: {ai.error}</p>}
    </>
  )

  if (aiCurrent) {
    return (
      <div className="card grid gap-4 p-4">
        <div className="flex items-center gap-4">
          <MatchBadge score={ai.score} large />
          <div className="min-w-0 flex-1">
            <h2 className="font-medium">{ai.verdict ? VERDICT[ai.verdict] : matchWord(ai.score!)}</h2>
            <p className="text-xs text-muted">AI grade · {new Date(ai.graded_at).toLocaleDateString()}</p>
          </div>
          {aiButton}
        </div>
        {aiProblems}
        {ai.summary && <p className="text-sm">{ai.summary}</p>}
        <AiList title="Deal-breakers" items={ai.dealbreakers} icon="⛔" cls="text-danger" />
        <AiList title="Why it fits" items={ai.strengths} icon="✓" cls="text-ok" />
        <AiList title="Gaps" items={ai.gaps} icon="✗" cls="text-warn" />
        {job.match && (
          <details className="rounded-xl border border-line p-3">
            <summary className="cursor-pointer text-sm text-muted">
              Keyword check: {job.match.score ?? '–'} (the quick rule-based grade)
            </summary>
            <div className="mt-3 grid gap-4">
              <RuleDetails m={job.match} />
            </div>
          </details>
        )}
      </div>
    )
  }

  const m = job.match
  const recalcButton = (
    <button className="btn-ghost shrink-0" disabled={recalc.isPending} onClick={() => recalc.mutate()}>
      {recalc.isPending ? 'Calculating…' : m ? '↻ Recalculate' : 'Calculate match'}
    </button>
  )
  const aiNote = ai?.stale ? (
    <p className="text-sm text-muted">Your CV, settings or this job changed since the AI graded it. A new AI grade is on its way (a few minutes).</p>
  ) : (
    settings.data?.ai_grading && !ai && <p className="text-sm text-muted">The AI grade for this job is on its way (a few minutes).</p>
  )

  if (!m) {
    return (
      <div className="card grid gap-3 p-4">
        <h2 className="font-medium">How well you match</h2>
        <p className="text-sm text-muted">
          Add your CV and skills in <Link to="/settings" className="text-primary underline">Settings</Link> to see a match grade
          and which skills fit or are missing.
        </p>
        <div className="flex flex-wrap gap-2">{recalcButton}{aiButton}</div>
        {recalc.isSuccess && !recalc.data.match && <p className="text-sm text-warn">No profile yet. Upload your CV in Settings first.</p>}
        {recalc.isError && <p className="text-sm text-danger">{recalc.error.message}</p>}
        {aiProblems}
      </div>
    )
  }

  const req = m.skills.filter((r) => r.need === 'required')
  return (
    <div className="card grid gap-4 p-4">
      <div className="flex items-center gap-4">
        <MatchBadge score={m.score} large />
        <div className="min-w-0 flex-1">
          <h2 className="font-medium">{m.score != null ? matchWord(m.score) : 'Not enough information'}</h2>
          <p className="text-sm text-muted">
            {req.length > 0
              ? `You have ${req.filter((r) => r.status === 'have').length} of ${req.length} required skills`
              : 'Based on your CV, skills and search settings'}
          </p>
        </div>
        <div className="flex shrink-0 flex-col gap-2">{recalcButton}{aiButton}</div>
      </div>
      {recalc.isError && <p className="text-sm text-danger">{recalc.error.message}</p>}
      {aiProblems}
      {aiNote}
      <RuleDetails m={m} />
    </div>
  )
}

function AiList({ title, items, icon, cls }: { title: string; items?: string[]; icon: string; cls: string }) {
  if (!items?.length) return null
  return (
    <div>
      <h3 className="mb-1 text-sm font-medium">{title}</h3>
      <ul className="grid gap-1 text-sm">
        {items.map((s) => (
          <li key={s} className="flex gap-2">
            <span className={cls}>{icon}</span>
            <span>{s}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** The rule-based grade: the five parts and the skills table. */
function RuleDetails({ m }: { m: Match }) {
  const count = (s: keyof typeof SKILL_STATUS) => m.skills.filter((r) => r.status === s).length
  return (
    <>
      <div className="grid gap-2.5">
        {m.parts.map((p) => (
          <div key={p.key} className="grid gap-1 text-sm">
            <div className="flex items-baseline justify-between gap-3">
              <span className="font-medium">{p.label}</span>
              <span className="tabular-nums text-muted">{p.score ?? '–'}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
              {p.score != null && (
                <div className={`h-full rounded-full ${p.score >= 75 ? 'bg-ok' : p.score >= 55 ? 'bg-warn' : 'bg-danger'}`} style={{ width: `${p.score}%` }} />
              )}
            </div>
            <span className="text-xs text-muted">{p.detail}</span>
          </div>
        ))}
      </div>

      {m.skills.length > 0 && (
        <div>
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-medium">Skills this job asks for</h3>
            <span className="text-xs text-muted">
              <span className="text-ok">✓ {count('have')} fit</span> · <span className="text-warn">≈ {count('similar')} similar</span> ·{' '}
              <span className="text-danger">✗ {count('missing')} missing</span>
            </span>
          </div>
          <div className="overflow-hidden rounded-xl border border-line">
            <table className="w-full text-sm">
              <thead className="bg-surface-2 text-left text-xs text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Skill</th>
                  <th className="px-3 py-2 font-medium">Needed</th>
                  <th className="px-3 py-2 font-medium">Your CV</th>
                </tr>
              </thead>
              <tbody>
                {m.skills.map((r) => {
                  const st = SKILL_STATUS[r.status]
                  return (
                    <tr key={r.skill} className="border-t border-line">
                      <td className="px-3 py-2">{r.skill}</td>
                      <td className="px-3 py-2 text-muted">{r.need === 'required' ? 'Required' : 'Nice to have'}</td>
                      <td className={`px-3 py-2 ${st.cls}`}>
                        {st.icon} {r.status === 'similar' && r.via ? `You know ${r.via}` : st.label}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {m.notes.map((n) => <p key={n} className="text-xs text-muted">{n}</p>)}
      <p className="text-xs text-muted">
        Grade = skills 50% · experience 15% · seniority 15% · role 10% · location 10%. Parts with no data are left out.
        Edit your skills in <Link to="/settings" className="text-primary underline">Settings</Link>.
      </p>
    </>
  )
}
