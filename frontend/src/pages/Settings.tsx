import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, SOURCES, type GmailMessage, type JobSummary, type Profile, type SearchSettings } from '../api'
import { Empty, PageTitle } from '../components'
import { FindJobsButton } from './Jobs'

const MODES = [
  { value: 'onsite', label: 'On-site' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'remote', label: 'Remote' },
] as const

function ChipsInput({ values, onChange, placeholder, suggestions }: { values: string[]; onChange: (v: string[]) => void; placeholder: string; suggestions?: string[] }) {
  const [text, setText] = useState('')
  const add = () => {
    const v = text.trim()
    if (v && !values.some((x) => x.toLowerCase() === v.toLowerCase())) onChange([...values, v])
    setText('')
  }
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-2">
        {values.map((v) => (
          <span key={v} className="pill bg-primary-soft py-1 pr-1 text-sm text-primary">
            {v}
            <button type="button" aria-label={`Remove ${v}`} className="ml-1 rounded-full px-1.5 hover:bg-primary/20" onClick={() => onChange(values.filter((x) => x !== v))}>
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          className="input"
          list={suggestions ? 'chip-suggestions' : undefined}
          placeholder={placeholder}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
        />
        <button type="button" className="btn-ghost shrink-0" onClick={add} disabled={!text.trim()}>Add</button>
        {suggestions && (
          <datalist id="chip-suggestions">
            {suggestions.filter((s) => !values.includes(s)).map((s) => <option key={s} value={s} />)}
          </datalist>
        )}
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const qc = useQueryClient()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const profile = useQuery({ queryKey: ['profile'], queryFn: api.profile })
  const [draft, setDraft] = useState<SearchSettings | null>(null)
  useEffect(() => {
    if (settings.data && !draft) setDraft(settings.data)
  }, [settings.data, draft])

  const save = useMutation({
    mutationFn: api.saveSettings,
    onSuccess: (s) => {
      qc.setQueryData(['settings'], s)
      setDraft(s)
    },
  })

  if (settings.isPending || !draft) return <Empty>Loading…</Empty>
  if (settings.isError) return <Empty>Error: {settings.error.message}</Empty>

  const set = <K extends keyof SearchSettings>(k: K, v: SearchSettings[K]) => setDraft({ ...draft, [k]: v })
  const toggleMode = (m: SearchSettings['work_modes'][number]) =>
    set('work_modes', draft.work_modes.includes(m) ? draft.work_modes.filter((x) => x !== m) : [...draft.work_modes, m])
  const dirty = JSON.stringify(draft) !== JSON.stringify(settings.data)

  return (
    <>
      <PageTitle>Settings</PageTitle>
      <ProfileSection />
      <form
        className="grid gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate(draft)
        }}
      >
        <section className="card grid gap-3 p-4">
          <h2 className="font-medium">Where to search</h2>
          <p className="-mt-2 text-sm text-muted">Choose the sources "Find jobs now" and the daily searches use. Jobs already found stay in your list.</p>
          <div className="grid gap-2">
            {SOURCES.filter((s) => s.searchable).map((s) => {
              const on = draft.sources.includes(s.value)
              return (
                <label key={s.value} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 ${on ? 'border-primary/60 bg-primary-soft/50' : 'border-line'}`}>
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 accent-[var(--primary)]"
                    checked={on}
                    onChange={() => set('sources', on ? draft.sources.filter((x) => x !== s.value) : [...draft.sources, s.value])}
                  />
                  <span className="text-sm">
                    <span className="font-medium">{s.label}</span>
                    <span className="block text-xs text-muted">{s.hint}</span>
                  </span>
                </label>
              )
            })}
          </div>
          {draft.sources.length === 0 && <p className="text-xs text-danger">Choose at least one source.</p>}
        </section>

        <section className="card grid gap-3 p-4">
          <h2 className="font-medium">Where you live</h2>
          <p className="-mt-2 text-sm text-muted">Used only to measure how far each office is from you.</p>
          <input className="input" placeholder="City or address, e.g. Ramat Gan" value={draft.home_label} onChange={(e) => set('home_label', e.target.value)} />
          {draft.home_lat !== null && settings.data?.home_found && !dirty && (
            <p className="text-xs text-ok">✓ Found: {settings.data.home_found}</p>
          )}
          {!draft.home_label && <p className="text-xs text-warn">No home set, so jobs aren't filtered by distance yet.</p>}
        </section>

        <section className="card grid gap-4 p-4">
          <h2 className="font-medium">Work mode and distance</h2>
          <div className="flex flex-wrap gap-2">
            {MODES.map((m) => (
              <button
                type="button"
                key={m.value}
                onClick={() => toggleMode(m.value)}
                aria-pressed={draft.work_modes.includes(m.value)}
                className={`rounded-full border px-4 py-2 text-sm ${draft.work_modes.includes(m.value) ? 'border-primary bg-primary text-on-primary' : 'border-line '}`}
              >
                {draft.work_modes.includes(m.value) ? '✓ ' : ''}{m.label}
              </button>
            ))}
          </div>
          {draft.work_modes.includes('onsite') && (
            <label className="grid gap-1 text-sm">
              <span>On-site jobs up to <b>{draft.max_km_onsite} km</b> from home</span>
              <input type="range" min={5} max={150} step={5} value={draft.max_km_onsite} onChange={(e) => set('max_km_onsite', Number(e.target.value))} className="accent-[var(--primary)]" />
            </label>
          )}
          {draft.work_modes.includes('hybrid') && (
            <label className="grid gap-1 text-sm">
              <span>Hybrid jobs up to <b>{draft.max_km_hybrid} km</b> from home</span>
              <input type="range" min={5} max={150} step={5} value={draft.max_km_hybrid} onChange={(e) => set('max_km_hybrid', Number(e.target.value))} className="accent-[var(--primary)]" />
            </label>
          )}
          {draft.work_modes.includes('remote') && <p className="text-sm text-muted">Remote jobs in Israel are included at any distance.</p>}
        </section>

        <section className="card grid gap-3 p-4">
          <h2 className="font-medium">Job titles to look for</h2>
          <p className="-mt-2 text-sm text-muted">A job matches if its title contains every word of any phrase. The first phrase is also used for the daily web search.</p>
          <ChipsInput values={draft.title_keywords} onChange={(v) => set('title_keywords', v)} placeholder="e.g. data engineer" />
          <label className="mt-1 flex items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-[var(--primary)]" checked={draft.senior_only} onChange={(e) => set('senior_only', e.target.checked)} />
            Only senior roles (Senior, Staff, Lead, Principal…)
          </label>
        </section>

        <section className="card grid gap-3 p-4">
          <h2 className="font-medium">Skip titles with</h2>
          <ChipsInput values={draft.exclude_keywords} onChange={(v) => set('exclude_keywords', v)} placeholder="e.g. junior" />
        </section>

        <section className="card grid gap-3 p-4">
          <h2 className="font-medium">AI match grade</h2>
          <p className="-mt-2 text-sm text-muted">
            Claude reads your CV and each job and grades the fit the way a recruiter would, with the reasons. It replaces the
            keyword grade, takes a few minutes for new jobs, and costs about 1–2 cents per job (graded again only if your CV,
            these settings or the job change). Your CV and the job text are sent to Anthropic.
          </p>
          {draft.ai_available ? (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="h-4 w-4 accent-[var(--primary)]" checked={draft.ai_grading} onChange={(e) => set('ai_grading', e.target.checked)} />
              Grade my jobs with AI
            </label>
          ) : (
            <p className="text-sm text-warn">Not set up on the server yet (ANTHROPIC_API_KEY in .env).</p>
          )}
          {draft.ai_grading && profile.data && !profile.data.cv_filename && (
            <p className="text-sm text-warn">Upload your CV above. Without it the AI has nothing to compare the jobs with.</p>
          )}
        </section>

        {save.isError && <p className="text-sm text-danger">{save.error.message}</p>}
        <div className="sticky bottom-20 z-10 flex items-center gap-3 md:bottom-4">
          <button className="btn-primary shadow-lg" disabled={!dirty || save.isPending}>{save.isPending ? 'Saving…' : 'Save settings'}</button>
          {save.isSuccess && !dirty && <span className="text-sm text-ok">Saved ✓</span>}
        </div>
      </form>

      <section className="card mt-6 grid gap-3 p-4">
        <h2 className="font-medium">Find jobs</h2>
        <p className="-mt-2 text-sm text-muted">The app searches automatically every day at 07:00 and 15:00. Save your settings, then search now to try them.</p>
        <FindJobsButton />
      </section>

      <GmailSection />

      <Companies />
    </>
  )
}

function Companies() {
  const qc = useQueryClient()
  const companies = useQuery({ queryKey: ['companies'], queryFn: api.companies })
  const [board, setBoard] = useState('')
  const add = useMutation({
    mutationFn: () => api.addCompany(board),
    onSuccess: () => {
      setBoard('')
      qc.invalidateQueries({ queryKey: ['companies'] })
    },
  })
  const remove = useMutation({ mutationFn: api.removeCompany, onSuccess: () => qc.invalidateQueries({ queryKey: ['companies'] }) })

  return (
    <section className="card mt-4 grid gap-3 p-4">
      <h2 className="font-medium">Company career pages watched ({companies.data?.length ?? 0})</h2>
      <p className="-mt-2 text-sm text-muted">
        Shared by everyone using this app. Add any company that hires through Greenhouse, Lever or Ashby by pasting its careers link.
      </p>
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault()
          add.mutate()
        }}
      >
        <input className="input" placeholder="https://jobs.lever.co/company" value={board} onChange={(e) => setBoard(e.target.value)} />
        <button className="btn-primary shrink-0" disabled={!board.trim() || add.isPending}>{add.isPending ? 'Checking…' : 'Add company'}</button>
      </form>
      {add.isError && <p className="text-sm text-danger">{add.error.message}</p>}
      <div className="flex flex-wrap gap-2">
        {companies.data?.map((c) => (
          <span key={c.id} title={c.last_error || `${c.ats}: ${c.slug}`} className={`pill gap-1 py-1 text-sm ${c.ok ? 'bg-surface-2' : 'bg-danger/15 text-danger'}`}>
            {!c.ok && '⚠ '}{c.name}
            {c.mine && (
              <button aria-label={`Remove ${c.name}`} className="rounded-full px-1 hover:bg-surface-2" onClick={() => remove.mutate(c.id)}>×</button>
            )}
          </span>
        ))}
      </div>
    </section>
  )
}

function ProfileSection() {
  const qc = useQueryClient()
  const profile = useQuery({ queryKey: ['profile'], queryFn: api.profile })
  const [draft, setDraft] = useState<Pick<Profile, 'skills' | 'years_experience' | 'ai_notes'> | null>(null)
  const [file, setFile] = useState<File | null>(null)
  useEffect(() => {
    if (profile.data && !draft) setDraft({ skills: profile.data.skills, years_experience: profile.data.years_experience, ai_notes: profile.data.ai_notes })
  }, [profile.data, draft])

  const done = (p: Profile) => {
    qc.setQueryData(['profile'], p)
    setDraft({ skills: p.skills, years_experience: p.years_experience, ai_notes: p.ai_notes })
    qc.invalidateQueries({ queryKey: ['jobs'] })
    qc.invalidateQueries({ queryKey: ['job'] })
  }
  const upload = useMutation({ mutationFn: (f: File) => api.uploadCv(f), onSuccess: (p) => { done(p); setFile(null) } })
  const save = useMutation({ mutationFn: api.saveProfile, onSuccess: done })

  if (profile.isPending || !draft) return <section className="card mb-4 p-4 text-sm text-muted">Loading your profile…</section>
  if (profile.isError) return <section className="card mb-4 p-4 text-sm text-danger">{profile.error.message}</section>
  const p = profile.data
  const dirty = JSON.stringify(draft) !== JSON.stringify({ skills: p.skills, years_experience: p.years_experience, ai_notes: p.ai_notes })
  const result = save.data ?? upload.data

  return (
    <section className="card mb-4 grid gap-4 p-4">
      <div>
        <h2 className="font-medium">Your CV and skills</h2>
        <p className="text-sm text-muted">Every job gets a match grade from these. Upload your CV, then check the skills and years it found.</p>
      </div>

      <div className="grid gap-2">
        {p.cv_filename && (
          <p className="text-sm">📄 {p.cv_filename} <span className="text-muted">· uploaded {p.cv_uploaded_at ? new Date(p.cv_uploaded_at).toLocaleDateString() : ''}</span></p>
        )}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <input
            type="file"
            accept=".pdf,.docx,.txt"
            className="text-sm file:mr-3 file:rounded-full file:border file:border-line file:bg-surface-2 file:px-3 file:py-1.5 file:text-sm file:text-ink"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <button type="button" className="btn-primary shrink-0" disabled={!file || upload.isPending} onClick={() => file && upload.mutate(file)}>
            {upload.isPending ? 'Reading CV…' : p.cv_filename ? 'Upload new CV' : 'Upload CV'}
          </button>
        </div>
        <p className="text-xs text-muted">PDF, Word (.docx) or text.{p.skills.length ? ' A new CV replaces the skills list below.' : ''}</p>
        {upload.isError && <p className="text-sm text-danger">{upload.error.message}</p>}
      </div>

      <label className="grid gap-1 text-sm">
        <span className="font-medium">Years of professional experience</span>
        <input
          type="number"
          min={0}
          max={50}
          className="input w-28"
          value={draft.years_experience ?? ''}
          onChange={(e) => setDraft({ ...draft, years_experience: e.target.value === '' ? null : Number(e.target.value) })}
        />
        {p.cv_years_guess != null && p.cv_years_guess !== draft.years_experience && (
          <span className="text-xs text-muted">Your CV's dates suggest about {p.cv_years_guess} years.</span>
        )}
      </label>

      <div className="grid gap-2">
        <span className="text-sm font-medium">Your skills ({draft.skills.length})</span>
        <ChipsInput
          values={draft.skills}
          onChange={(skills) => setDraft({ ...draft, skills })}
          placeholder="Add a skill, e.g. Airflow"
          suggestions={p.known_skills}
        />
        <p className="text-xs text-muted">Add skills you know that your CV doesn't mention, and remove any it got wrong.</p>
      </div>

      <label className="grid gap-1 text-sm">
        <span className="font-medium">About me, for the AI grade</span>
        <textarea
          className="input min-h-28"
          maxLength={3000}
          placeholder="e.g. Grade me by my last data engineering role. I want mid / senior hands-on roles, not team lead."
          value={draft.ai_notes}
          onChange={(e) => setDraft({ ...draft, ai_notes: e.target.value })}
        />
        <span className="text-xs text-muted">The AI follows these when it grades: what to count, what to ignore, which roles you want. Changing them re-grades your open jobs.</span>
      </label>

      {save.isError && <p className="text-sm text-danger">{save.error.message}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate(draft)}>
          {save.isPending ? 'Saving…' : 'Save profile'}
        </button>
        {result?.rescored != null && !dirty && <span className="text-sm text-ok">✓ Saved. {result.rescored} job{result.rescored === 1 ? '' : 's'} re-graded.</span>}
      </div>
    </section>
  )
}

const CONNECT_RESULT: Record<string, [string, boolean]> = {
  connected: ['Gmail connected. Job emails from the last 14 days and from now on will be handled.', true],
  cancelled: ['Gmail was not connected (cancelled in Google).', false],
  missing_permission: ["Google didn't give permission to manage your email. Connect again and leave the Gmail box ticked.", false],
  expired: ['The connection took too long. Please try again.', false],
  wrong_user: ['You were signed in to JobHunter as someone else. Please try again.', false],
  failed: ['Google refused the connection. Please try again.', false],
}

const KIND_LABEL: Record<GmailMessage['kind'], string> = {
  confirmation: '📨 Application received',
  rejection: '✕ Rejection',
  interview: '🎉 Interview',
}

function actionText(m: GmailMessage, label: string) {
  const job = m.job_id ? `${m.job_title} · ${m.job_company}` : ''
  const moved = m.moved ? ` · moved to ${label}` : ''
  switch (m.action) {
    case 'status_changed': return `Updated ${job}${moved}`
    case 'created_job': return `Added ${job} as Applied${moved}`
    case 'no_change': return `${job}: status already further along${moved}`
    case 'undone': return 'Undone'
    default: return 'Not sure which job: pick it below'
  }
}

function GmailSection() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const result = params.get('gmail')
  const status = useQuery({ queryKey: ['gmail'], queryFn: api.gmailStatus })
  const connected = !!status.data?.connected
  const messages = useQuery({ queryKey: ['gmail-messages'], queryFn: api.gmailMessages, enabled: connected })
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['gmail'] })
    qc.invalidateQueries({ queryKey: ['gmail-messages'] })
    qc.invalidateQueries({ queryKey: ['jobs'] })
    qc.invalidateQueries({ queryKey: ['job'] })
  }
  const sync = useMutation({ mutationFn: api.gmailSync, onSuccess: refresh })
  const disconnect = useMutation({ mutationFn: api.gmailDisconnect, onSuccess: refresh })
  const undo = useMutation({ mutationFn: api.gmailUndo, onSuccess: refresh })

  useEffect(() => {
    if (result) document.getElementById('gmail')?.scrollIntoView({ behavior: 'smooth' })
  }, [result])

  if (status.isPending) return null
  if (status.isError) return <section className="card mt-6 p-4 text-sm text-danger">{status.error.message}</section>
  const s = status.data
  const notice = result ? CONNECT_RESULT[result] : undefined

  return (
    <section id="gmail" className="card mt-6 grid gap-3 p-4">
      <div>
        <h2 className="font-medium">Gmail</h2>
        <p className="text-sm text-muted">
          Reads new mail in your Inbox every 10 minutes (the first check also reads the last 14 days). &ldquo;We got your application&rdquo; marks the job Applied and rejections mark it Rejected; both
          emails move to the <b>{s.label}</b> label. Interview invitations mark the job Interview and stay in your Inbox. Other mail isn&rsquo;t touched or saved.
        </p>
      </div>
      {notice && (
        <div className={`flex items-start justify-between gap-2 rounded-xl p-3 text-sm ${notice[1] ? 'bg-ok/10 text-ok' : 'bg-danger/10 text-danger'}`}>
          <span>{notice[0]}</span>
          <button type="button" className="shrink-0 text-muted" onClick={() => { params.delete('gmail'); setParams(params, { replace: true }) }}>✕</button>
        </div>
      )}
      {!s.configured ? (
        <p className="text-sm text-warn">Gmail isn&rsquo;t set up on the server yet (GOOGLE_CLIENT_SECRET in .env).</p>
      ) : !connected ? (
        <a href="/api/gmail/connect" className="btn-primary w-fit">Connect Gmail</a>
      ) : (
        <>
          <p className="text-sm">
            ✓ Connected as <b>{s.email}</b>
            <span className="text-muted"> · last check {s.last_sync_at ? new Date(s.last_sync_at).toLocaleString() : 'not yet'}</span>
          </p>
          {s.last_error && (
            <p className="text-sm text-danger">
              {s.last_error} {s.last_error.includes('Connect Gmail again') && <a href="/api/gmail/connect" className="underline">Connect again</a>}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="btn-primary" disabled={sync.isPending} onClick={() => sync.mutate()}>
              {sync.isPending ? 'Checking…' : 'Check now'}
            </button>
            <button type="button" className="btn-ghost" disabled={disconnect.isPending}
              onClick={() => confirm('Disconnect Gmail? The app will stop reading your email and forget its list of handled job emails (job statuses stay as they are).') && disconnect.mutate()}>
              Disconnect
            </button>
            {sync.data && !sync.data.error && (
              <span className="text-sm text-muted">
                {sync.data.job_emails ? `${sync.data.job_emails} job email${sync.data.job_emails > 1 ? 's' : ''} found` : 'No new job emails'}
              </span>
            )}
          </div>
          {sync.isError && <p className="text-sm text-danger">{sync.error.message}</p>}
          {!!messages.data?.length && (
            <div className="grid gap-2">
              <h3 className="text-sm font-medium">Recent job emails</h3>
              <ul className="grid gap-2">
                {messages.data.map((m) => (
                  <li key={m.id} className="rounded-xl border border-line p-3 text-sm">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                      <span className="font-medium">{KIND_LABEL[m.kind]}</span>
                      <span className="text-xs text-muted">{m.received_at ? new Date(m.received_at).toLocaleString() : ''}</span>
                    </div>
                    <div className="truncate">&ldquo;{m.subject}&rdquo;</div>
                    <div className="truncate text-xs text-muted">{m.sender}</div>
                    <div className={`mt-1 text-xs ${m.action === 'unmatched' ? 'text-warn' : 'text-muted'}`}>{actionText(m, s.label)}</div>
                    <div className="mt-1 flex flex-wrap gap-3 text-xs">
                      {m.link && <a href={m.link} target="_blank" rel="noreferrer" className="text-primary underline">Open in Gmail</a>}
                      {['status_changed', 'created_job', 'no_change'].includes(m.action) && (
                        <button type="button" className="text-primary underline" disabled={undo.isPending}
                          onClick={() => confirm('Undo? The email goes back to the Inbox and the job goes back to its old status.') && undo.mutate(m.id)}>
                          Undo
                        </button>
                      )}
                    </div>
                    {m.action === 'unmatched' && <AssignJob message={m} onDone={refresh} />}
                  </li>
                ))}
              </ul>
              {undo.isError && <p className="text-sm text-danger">{undo.error.message}</p>}
            </div>
          )}
        </>
      )}
    </section>
  )
}

function AssignJob({ message, onDone }: { message: GmailMessage; onDone: () => void }) {
  const jobs = useQuery({ queryKey: ['jobs', 'all-for-email'], queryFn: () => api.jobs() })
  const [jobId, setJobId] = useState('')
  const assign = useMutation({ mutationFn: () => api.gmailAssign(message.id, Number(jobId)), onSuccess: onDone })
  const guess = message.company_guess.toLowerCase()
  const first = (j: JobSummary) => (guess && j.company.toLowerCase().includes(guess) ? 0 : 1)
  const list = [...(jobs.data ?? [])].sort((a, b) => first(a) - first(b) || a.company.localeCompare(b.company))
  return (
    <div className="mt-2 flex flex-col gap-2 sm:flex-row">
      <select className="input min-w-0 flex-1" value={jobId} onChange={(e) => setJobId(e.target.value)}>
        <option value="">Which job is this about?</option>
        {list.map((j) => <option key={j.id} value={j.id}>{j.company} · {j.title}</option>)}
      </select>
      <button type="button" className="btn-primary shrink-0" disabled={!jobId || assign.isPending} onClick={() => assign.mutate()}>
        {assign.isPending ? 'Saving…' : 'Link to job'}
      </button>
      {assign.isError && <p className="text-sm text-danger">{assign.error.message}</p>}
    </div>
  )
}
