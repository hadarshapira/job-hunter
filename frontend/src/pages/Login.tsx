import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

// Minimal typing for Google Identity Services (https://accounts.google.com/gsi/client)
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (o: { client_id: string; callback: (r: { credential: string }) => void; ux_mode?: string }) => void
          renderButton: (el: HTMLElement, o: Record<string, unknown>) => void
        }
      }
    }
  }
}

function loadGoogleScript(): Promise<void> {
  if (window.google?.accounts) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const existing = document.getElementById('gsi-script')
    const s = (existing as HTMLScriptElement) ?? document.createElement('script')
    s.addEventListener('load', () => resolve())
    s.addEventListener('error', () => reject(new Error('Could not load Google sign-in')))
    if (!existing) {
      s.id = 'gsi-script'
      s.src = 'https://accounts.google.com/gsi/client'
      s.async = true
      document.head.appendChild(s)
    }
  })
}

export default function Login() {
  const qc = useQueryClient()
  const config = useQuery({ queryKey: ['auth-config'], queryFn: api.authConfig })
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const googleBtn = useRef<HTMLDivElement>(null)

  const finish = async (p: Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      await p
      await qc.invalidateQueries({ queryKey: ['me'] })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  const clientId = config.data?.google_client_id
  useEffect(() => {
    if (!clientId || !googleBtn.current) return
    let cancelled = false
    loadGoogleScript()
      .then(() => {
        if (cancelled || !window.google || !googleBtn.current) return
        window.google.accounts.id.initialize({ client_id: clientId, callback: (r) => finish(api.google(r.credential)) })
        const dark = window.matchMedia('(prefers-color-scheme: dark)').matches
        window.google.accounts.id.renderButton(googleBtn.current, {
          theme: dark ? 'filled_black' : 'outline',
          size: 'large',
          shape: 'pill',
          text: mode === 'signup' ? 'signup_with' : 'signin_with',
          width: Math.min(googleBtn.current.offsetWidth || 320, 400),
        })
      })
      .catch((e) => setError(e.message))
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, mode])

  const signupAllowed = config.data?.signup_enabled ?? true
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    finish(mode === 'signup' ? api.signup(email, password, name) : api.login(email, password))
  }

  return (
    <div className="grid min-h-dvh place-items-center p-4">
      <div className="card w-full max-w-sm p-6">
        <img src="/icon.svg" alt="" className="mx-auto h-14 w-14" />
        <h1 className="mt-3 text-center text-xl font-semibold">JobHunter</h1>
        <p className="mb-5 text-center text-sm text-muted">
          {mode === 'signup' ? 'Create your account' : 'Sign in to your job search'}
        </p>

        {clientId ? (
          <div ref={googleBtn} className="flex min-h-11 w-full justify-center" />
        ) : (
          <button
            type="button"
            className="flex h-11 w-full items-center justify-center gap-3 rounded-full border border-line bg-surface text-sm font-medium text-ink hover:bg-surface-2"
            onClick={() =>
              setError(
                'Google sign-in is not set up on this server yet. The app owner needs to add GOOGLE_CLIENT_ID to the .env file (see README). You can use email for now.',
              )
            }
          >
            <svg viewBox="0 0 48 48" className="h-5 w-5" aria-hidden>
              <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.3-.4-3.5z" />
              <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
              <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
              <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.2-.1-2.3-.4-3.5z" />
            </svg>
            {mode === 'signup' ? 'Sign up with Google' : 'Sign in with Google'}
          </button>
        )}
        <div className="my-4 flex items-center gap-3 text-xs text-muted">
          <div className="h-px flex-1 bg-line" /> or with email <div className="h-px flex-1 bg-line" />
        </div>

        <form onSubmit={submit} className="grid gap-3">
          {mode === 'signup' && (
            <input className="input" placeholder="Your name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
          )}
          <input
            className="input"
            type="email"
            autoComplete="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <input
            className="input"
            type="password"
            autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
            placeholder={mode === 'signup' ? 'Password (at least 8 characters)' : 'Password'}
            minLength={mode === 'signup' ? 8 : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && <p className="text-sm text-danger">{error}</p>}
          <button className="btn-primary w-full" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'signup' ? 'Create account' : 'Sign in'}
          </button>
        </form>

        {signupAllowed && (
          <p className="mt-4 text-center text-sm text-muted">
            {mode === 'signin' ? 'New here? ' : 'Already have an account? '}
            <button
              className="text-primary underline"
              onClick={() => {
                setMode(mode === 'signin' ? 'signup' : 'signin')
                setError('')
              }}
            >
              {mode === 'signin' ? 'Create an account' : 'Sign in'}
            </button>
          </p>
        )}
      </div>
    </div>
  )
}
