import { useQuery, useQueryClient } from '@tanstack/react-query'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, AuthError } from './api'
import AddJob from './pages/AddJob'
import JobDetail from './pages/JobDetail'
import Jobs from './pages/Jobs'
import Login from './pages/Login'
import SettingsPage from './pages/Settings'
import StatsPage from './pages/Stats'
import Tracker from './pages/Tracker'

const NAV = [
  { to: '/', label: 'Jobs', icon: 'M4 6h16M4 12h16M4 18h10' },
  { to: '/tracker', label: 'Tracker', icon: 'M4 5h4v14H4zM10 5h4v9h-4zM16 5h4v6h-4z' },
  { to: '/add', label: 'Add', icon: 'M12 5v14M5 12h14' },
  { to: '/stats', label: 'Stats', icon: 'M5 19V11M12 19V5M19 19v-6' },
  { to: '/settings', label: 'Settings', icon: 'M4 7h10M18 7h2M4 17h4M12 17h8M14 4v6M8 14v6' },
]

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  )
}

export default function App() {
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })

  if (me.isPending) return <div className="grid h-dvh place-items-center text-zinc-500">Loading…</div>
  if (me.error instanceof AuthError) return <Login />
  if (me.isError)
    return (
      <div className="grid h-dvh place-items-center p-6 text-center">
        <div>
          <p className="font-medium">Can't reach the JobHunter server.</p>
          <p className="mt-1 text-sm text-zinc-500">Is Docker running? ({String(me.error.message)})</p>
          <button className="btn-primary mt-4" onClick={() => me.refetch()}>Retry</button>
        </div>
      </div>
    )

  const logout = async () => {
    await api.logout()
    qc.clear()
    qc.invalidateQueries({ queryKey: ['me'] })
  }

  return (
    <div className="min-h-dvh md:flex">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 flex-col border-r border-zinc-200 p-4 md:flex dark:border-zinc-800">
        <div className="mb-6 flex items-center gap-2 px-2 text-lg font-semibold">
          <img src="/icon.svg" className="h-7 w-7" alt="" /> JobHunter
        </div>
        <nav className="flex flex-col gap-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-3 py-2 text-sm ${isActive ? 'bg-indigo-600 text-white' : 'hover:bg-zinc-100 dark:hover:bg-zinc-800'}`
              }
            >
              <Icon d={n.icon} /> {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto flex items-center gap-3 px-2">
          {me.data.picture ? (
            <img src={me.data.picture} alt="" referrerPolicy="no-referrer" className="h-8 w-8 rounded-full" />
          ) : (
            <div className="grid h-8 w-8 place-items-center rounded-full bg-indigo-600 text-sm font-medium text-white">
              {(me.data.name || me.data.email)[0].toUpperCase()}
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm">{me.data.name || me.data.email}</div>
            <button onClick={logout} className="text-xs text-zinc-500 hover:text-zinc-300">Log out</button>
          </div>
        </div>
      </aside>

      <main className="mx-auto w-full max-w-5xl px-4 pb-28 pt-[max(1rem,env(safe-area-inset-top))] md:px-8 md:pb-10 md:pt-8">
        <Routes>
          <Route path="/" element={<Jobs />} />
          <Route path="/tracker" element={<Tracker />} />
          <Route path="/add" element={<AddJob />} />
          <Route path="/stats" element={<StatsPage user={me.data} onLogout={logout} />} />
          <Route path="/jobs/:id" element={<JobDetail />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>

      {/* Phone bottom bar */}
      <nav className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-5 border-t border-zinc-200 bg-white/90 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden dark:border-zinc-800 dark:bg-zinc-950/90">
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === '/'}
            className={({ isActive }) =>
              `flex flex-col items-center gap-1 py-2.5 text-[11px] ${isActive ? 'text-indigo-500' : 'text-zinc-500'}`
            }
          >
            <Icon d={n.icon} />
            {n.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
