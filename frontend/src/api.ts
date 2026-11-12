export type Status =
  | 'new' | 'saved' | 'applied' | 'screening' | 'interview' | 'offer' | 'rejected' | 'ghosted' | 'archived'
export type WorkMode = 'onsite' | 'hybrid' | 'remote' | 'unknown'

export const STATUSES: { value: Status; label: string; tone: string }[] = [
  { value: 'saved', label: 'Saved', tone: 'bg-slate-500/15 text-slate-700 dark:text-slate-300' },
  { value: 'applied', label: 'Applied', tone: 'bg-blue-500/15 text-blue-700 dark:text-blue-300' },
  { value: 'screening', label: 'Screening', tone: 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-300' },
  { value: 'interview', label: 'Interview', tone: 'bg-violet-500/15 text-violet-700 dark:text-violet-300' },
  { value: 'offer', label: 'Offer', tone: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300' },
  { value: 'rejected', label: 'Rejected', tone: 'bg-rose-500/15 text-rose-700 dark:text-rose-300' },
  { value: 'ghosted', label: 'Ghosted', tone: 'bg-amber-500/15 text-amber-700 dark:text-amber-300' },
  { value: 'archived', label: 'Archived', tone: 'bg-zinc-500/15 text-zinc-600 dark:text-zinc-400' },
  { value: 'new', label: 'New', tone: 'bg-indigo-500/15 text-indigo-700 dark:text-indigo-300' },
]
export const statusInfo = (s: string) => STATUSES.find((x) => x.value === s) ?? STATUSES[0]

export const WORK_MODES: { value: WorkMode; label: string }[] = [
  { value: 'onsite', label: 'On-site' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'remote', label: 'Remote' },
  { value: 'unknown', label: 'Unknown' },
]

export interface JobEvent { id: number; kind: string; text: string; created_at: string }

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
  created_at: string
  updated_at: string
}

export interface Job extends JobSummary {
  description: string
  notes: string
  contact: string
  parse_issues: string
  events: JobEvent[]
}

export interface Stats {
  by_status: Record<string, number>
  by_source: Record<string, number>
  applied_total: number
  responded: number
  response_rate: number
  follow_ups_due: number
}

export class AuthError extends Error {}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: 'include',
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
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
  jobs: (params: { status?: Status[]; q?: string } = {}) => {
    const sp = new URLSearchParams()
    params.status?.forEach((s) => sp.append('status', s))
    if (params.q) sp.set('q', params.q)
    return req<JobSummary[]>(`/jobs?${sp}`)
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
}

export const isDue = (d: string | null) => !!d && d <= new Date().toISOString().slice(0, 10)
export const fmtDate = (d: string | null) =>
  d ? new Date(d).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : ''
