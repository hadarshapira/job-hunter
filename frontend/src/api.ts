export type Status =
  | 'new' | 'saved' | 'applied' | 'screening' | 'interview' | 'offer' | 'rejected' | 'ghosted' | 'archived'
export type WorkMode = 'onsite' | 'hybrid' | 'remote' | 'unknown'

export const STATUSES: { value: Status; label: string; tone: string }[] = [
  { value: 'saved', label: 'Saved', tone: 'tone-saved' },
  { value: 'applied', label: 'Applied', tone: 'tone-applied' },
  { value: 'screening', label: 'Screening', tone: 'tone-screening' },
  { value: 'interview', label: 'Interview', tone: 'tone-interview' },
  { value: 'offer', label: 'Offer', tone: 'tone-offer' },
  { value: 'rejected', label: 'Rejected', tone: 'tone-rejected' },
  { value: 'ghosted', label: 'Ghosted', tone: 'tone-ghosted' },
  { value: 'archived', label: 'Archived', tone: 'tone-archived' },
  { value: 'new', label: 'New', tone: 'tone-new' },
]
export const statusInfo = (s: string) => STATUSES.find((x) => x.value === s) ?? STATUSES[0]

export const WORK_MODES: { value: WorkMode; label: string }[] = [
  { value: 'onsite', label: 'On-site' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'remote', label: 'Remote' },
  { value: 'unknown', label: 'Unknown' },
]

export const SOURCES: { value: string; label: string; searchable: boolean; hint: string }[] = [
  { value: 'linkedin', label: 'LinkedIn', searchable: true, hint: "LinkedIn's public job search in Israel: every title you look for, past week, with full descriptions" },
  { value: 'jsearch', label: 'Web search', searchable: true, hint: 'Google for Jobs: Indeed, Glassdoor, company sites and some LinkedIn (limited monthly quota)' },
  { value: 'greenhouse', label: 'Greenhouse', searchable: true, hint: 'Career pages of companies that use Greenhouse' },
  { value: 'lever', label: 'Lever', searchable: true, hint: 'Career pages of companies that use Lever' },
  { value: 'ashby', label: 'Ashby', searchable: true, hint: 'Career pages of companies that use Ashby' },
  { value: 'link', label: 'Your links', searchable: false, hint: '' },
  { value: 'manual', label: 'Added by you', searchable: false, hint: '' },
  { value: 'email', label: 'From Gmail', searchable: false, hint: '' },
]
export const sourceLabel = (s: string) => SOURCES.find((x) => x.value === s)?.label ?? s

export interface JobEvent { id: number; kind: string; text: string; url: string | null; created_at: string }

export interface JobSummary {
  id: number
  title: string
  company: string
  location: string
  work_mode: WorkMode
  source: string
  status: Status
  salary: string | null
  url: string | null
  posted_at: string | null
  applied_at: string | null
  follow_up_on: string | null
  distance_km: number | null
  match_score: number | null
  created_at: string
  updated_at: string
}

export interface Job extends JobSummary {
  description: string
  notes: string
  contact: string
  parse_issues: string
  match: Match | null
  match_at: string | null
  ai_match: AIMatch | null
  events: JobEvent[]
}

/** Claude's grade (services/ai_match.py). stale = the CV, settings or job changed since; a new grade is on its way. */
export interface AIMatch {
  score: number | null
  verdict?: 'strong' | 'good' | 'stretch' | 'poor'
  summary?: string
  strengths?: string[]
  gaps?: string[]
  dealbreakers?: string[]
  error?: string
  model?: string
  graded_at: string
  stale?: boolean
}

export interface MatchPart { key: string; label: string; weight: number; score: number | null; detail: string }
export interface MatchSkill { skill: string; need: 'required' | 'nice'; status: 'have' | 'similar' | 'missing'; via: string | null }
export interface Match {
  score: number | null
  parts: MatchPart[]
  skills: MatchSkill[]
  required_years: number | null
  your_years: number | null
  notes: string[]
}

export interface Profile {
  skills: string[]
  years_experience: number | null
  ai_notes: string
  cv_filename: string
  cv_uploaded_at: string | null
  cv_years_guess: number | null
  known_skills: string[]
  rescored: number | null
}

export interface SearchSettings {
  home_label: string
  home_found: string | null
  home_lat: number | null
  home_lon: number | null
  work_modes: ('onsite' | 'hybrid' | 'remote')[]
  max_km_onsite: number
  max_km_hybrid: number
  title_keywords: string[]
  exclude_keywords: string[]
  senior_only: boolean
  sources: string[]
  ai_grading: boolean
  ai_available: boolean
}

export interface Company { id: number; ats: string; slug: string; name: string; mine: boolean; ok: boolean; last_error: string }

export interface CollectStatus {
  running: boolean
  last_started: string | null
  last_finished: string | null
  last_added: number | null
  last_errors: string[]
  jsearch_enabled: boolean
  jsearch_quota_left: number | null
  last_stats: {
    sources: Record<string, Partial<Record<'found' | 'added' | 'already_have' | 'title' | 'location' | 'duplicate', number>>>
    linkedin: { linkedin_found?: number; linkedin_title_skip?: number; linkedin_read?: number; linkedin_deferred?: number }
  } | null
}

export interface Stats {
  new: number
  by_status: Record<string, number>
  by_source: Record<string, number>
  applied_total: number
  responded: number
  response_rate: number
  follow_ups_due: number
}

export interface GmailStatus {
  configured: boolean
  connected: boolean
  email: string
  connected_at: string | null
  last_sync_at: string | null
  last_error: string
  label: string
}
export type GmailKind = 'confirmation' | 'rejection' | 'interview'
export interface GmailMessage {
  id: number
  sender: string
  subject: string
  received_at: string | null
  kind: GmailKind
  action: 'status_changed' | 'created_job' | 'no_change' | 'unmatched' | 'undone'
  job_id: number | null
  job_title: string
  job_company: string
  company_guess: string
  title_guess: string
  moved: boolean
  link: string
}

export class AuthError extends Error {}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: 'include',
    ...init,
    // FormData (file upload) sets its own multipart Content-Type
    headers: { ...(typeof init.body === 'string' ? { 'Content-Type': 'application/json' } : {}), ...(init.headers ?? {}) },
  })
  if (res.status === 401) throw new AuthError('Not logged in')
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* not JSON */ }
    throw new Error(detail)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

const json = (body: unknown) => JSON.stringify(body)

export interface User {
  id: number
  email: string
  name: string
  picture: string | null
  has_password: boolean
  google_linked: boolean
}

export interface AuthConfig { google_client_id: string | null; signup_enabled: boolean }

export const api = {
  me: () => req<User>('/auth/me'),
  authConfig: () => req<AuthConfig>('/auth/config'),
  login: (email: string, password: string) => req<User>('/auth/login', { method: 'POST', body: json({ email, password }) }),
  signup: (email: string, password: string, name: string) =>
    req<User>('/auth/signup', { method: 'POST', body: json({ email, password, name }) }),
  google: (credential: string) => req<User>('/auth/google', { method: 'POST', body: json({ credential }) }),
  logout: () => req('/auth/logout', { method: 'POST' }),
  jobs: (params: { status?: Status[]; q?: string; sort?: 'recent' | 'match'; source?: string } = {}) => {
    const sp = new URLSearchParams()
    params.status?.forEach((s) => sp.append('status', s))
    if (params.q) sp.set('q', params.q)
    if (params.sort) sp.set('sort', params.sort)
    if (params.source) sp.set('source', params.source)
    return req<JobSummary[]>(`/jobs?${sp}`)
  },
  jobSources: (params: { status?: Status[]; q?: string } = {}) => {
    const sp = new URLSearchParams()
    params.status?.forEach((s) => sp.append('status', s))
    if (params.q) sp.set('q', params.q)
    return req<Record<string, number>>(`/jobs/sources?${sp}`)
  },
  job: (id: number) => req<Job>(`/jobs/${id}`),
  createJob: (body: Partial<Job>) => req<Job>('/jobs', { method: 'POST', body: json(body) }),
  importJob: (url: string) =>
    req<{ job: Job; duplicate: boolean; complete: boolean }>('/jobs/import', { method: 'POST', body: json({ url }) }),
  reimportJob: (id: number) =>
    req<{ job: Job; duplicate: boolean; complete: boolean }>(`/jobs/${id}/reimport`, { method: 'POST' }),
  updateJob: (id: number, body: Partial<Job>) => req<Job>(`/jobs/${id}`, { method: 'PATCH', body: json(body) }),
  addNote: (id: number, text: string) => req<Job>(`/jobs/${id}/notes`, { method: 'POST', body: json({ text }) }),
  deleteJob: (id: number) => req<void>(`/jobs/${id}`, { method: 'DELETE' }),
  stats: () => req<Stats>('/stats'),
  settings: () => req<SearchSettings>('/settings'),
  saveSettings: (s: SearchSettings) => req<SearchSettings>('/settings', { method: 'PUT', body: json(s) }),
  companies: () => req<Company[]>('/companies'),
  addCompany: (board: string, name = '') => req<Company>('/companies', { method: 'POST', body: json({ board, name }) }),
  removeCompany: (id: number) => req<void>(`/companies/${id}`, { method: 'DELETE' }),
  collectStatus: () => req<CollectStatus>('/collect'),
  rematch: (id: number) => req<Job>(`/jobs/${id}/match`, { method: 'POST' }),
  aiMatch: (id: number) => req<Job>(`/jobs/${id}/ai-match`, { method: 'POST' }),
  profile: () => req<Profile>('/profile'),
  saveProfile: (p: Pick<Profile, 'skills' | 'years_experience' | 'ai_notes'>) => req<Profile>('/profile', { method: 'PUT', body: json(p) }),
  uploadCv: (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return req<Profile>('/profile/cv', { method: 'POST', body: fd })
  },
  gmailStatus: () => req<GmailStatus>('/gmail/status'),
  gmailSync: () => req<{ checked: number; job_emails: number; updated: number; unmatched: number; error: string }>('/gmail/sync', { method: 'POST' }),
  gmailDisconnect: () => req<void>('/gmail/disconnect', { method: 'POST' }),
  gmailMessages: () => req<GmailMessage[]>('/gmail/messages'),
  gmailAssign: (id: number, jobId: number) => req<GmailMessage>(`/gmail/messages/${id}/assign`, { method: 'POST', body: json({ job_id: jobId }) }),
  gmailUndo: (id: number) => req<GmailMessage>(`/gmail/messages/${id}/undo`, { method: 'POST' }),
  collectNow: () => req<{ started: boolean; detail?: string }>('/collect', { method: 'POST' }),
}

export const isDue = (d: string | null) => !!d && d <= new Date().toISOString().slice(0, 10)
export const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : ''
