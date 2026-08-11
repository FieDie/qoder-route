import { useState, Suspense } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { NavLink, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Dashboard } from './Dashboard'
import { AccountManager } from '../accounts/AccountManager'
import { WORKER_ENABLED, WorkerPage } from '../../lib/features'
import { Logs } from '../logs/Logs'
import { Settings } from '../settings/Settings'
import { Status } from '../status/Status'
import { LayoutDashboard, Users, TerminalSquare, ScrollText, Settings as SettingsIcon, Activity, Menu, X } from 'lucide-react'

const NAV: { path: string; label: string; icon: React.ReactNode; hint: string }[] = [
  { path: '/dashboard', label: 'Dashboard', icon: <LayoutDashboard size={16} />, hint: 'Overview' },
  { path: '/accounts', label: 'Accounts', icon: <Users size={16} />, hint: 'Pool' },
  ...(WORKER_ENABLED
    ? [{ path: '/worker', label: 'Worker', icon: <TerminalSquare size={16} />, hint: 'Trials' }]
    : []),
  { path: '/status', label: 'Status', icon: <Activity size={16} />, hint: 'Models' },
  { path: '/logs', label: 'Logs', icon: <ScrollText size={16} />, hint: 'Activity' },
  { path: '/settings', label: 'Settings', icon: <SettingsIcon size={16} />, hint: 'Config' },
]

function Logo() {
  return (
    <div className="flex items-center gap-3">
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
        style={{
          background: '#fafafa',
          boxShadow: '0 0 0 1px rgba(255,255,255,0.1), 0 2px 8px rgba(0,0,0,0.4)',
        }}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#000" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" />
        </svg>
      </div>
      <div className="leading-tight">
        <div className="text-[14px] font-semibold text-white tracking-tight">QoderRoute</div>
        <div className="text-[9px] font-medium text-neutral-600 uppercase tracking-[0.14em]">Pool Manager</div>
      </div>
    </div>
  )
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation()
  return (
    <nav className="space-y-0.5">
      {NAV.map((item) => {
        const active = location.pathname.startsWith(item.path)
        return (
          <NavLink key={item.path} to={item.path} onClick={onNavigate} className="relative w-full group block">
            {active && (
              <motion.span
                layoutId="nav-pill"
                className="absolute inset-0 rounded-lg"
                style={{
                  background: 'rgba(255,255,255,0.08)',
                  border: '1px solid rgba(255,255,255,0.1)',
                }}
                transition={{ type: 'spring', damping: 32, stiffness: 420 }}
              />
            )}
            <span
              className={`relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13px] transition-colors duration-150 ${
                active ? 'text-white' : 'text-neutral-500 group-hover:text-neutral-300'
              }`}
            >
              {item.icon}
              <span className="font-medium">{item.label}</span>
              <span className={`ml-auto text-[10px] ${active ? 'text-neutral-500' : 'text-neutral-700 group-hover:text-neutral-600'}`}>
                {item.hint}
              </span>
            </span>
          </NavLink>
        )
      })}
    </nav>
  )
}

function StatusFooter() {
  return (
    <div
      className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg"
      style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}
    >
      <span className="pulse-dot w-1.5 h-1.5 rounded-full text-white" style={{ backgroundColor: '#fafafa' }} />
      <div className="min-w-0 leading-tight">
        <div className="text-[11px] font-medium text-neutral-400">API online</div>
        <div className="text-[10px] text-neutral-600 font-mono truncate">localhost:8010</div>
      </div>
    </div>
  )
}

export function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  // Key page transitions by top-level section only, so sub-routes like
  // /accounts/available → /accounts/exhausted update in place.
  const sectionKey = '/' + (location.pathname.split('/')[1] ?? '')

  return (
    <div className="min-h-screen flex" style={{ background: '#000' }}>
      <div className="mesh-bg" />

      {/* Desktop sidebar */}
      <aside
        className="hidden lg:flex flex-col w-[240px] shrink-0 sticky top-0 h-screen"
        style={{
          background: 'rgba(255,255,255,0.01)',
          borderRight: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        <div className="p-5 pb-4">
          <Logo />
        </div>
        <div className="flex-1 px-3 py-2">
          <NavItems />
        </div>
        <div className="p-4">
          <StatusFooter />
        </div>
      </aside>

      {/* Mobile top bar */}
      <div
        className="lg:hidden fixed top-0 inset-x-0 z-40"
        style={{
          background: 'rgba(0, 0, 0, 0.85)',
          backdropFilter: 'blur(16px)',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
        }}
      >
        <div className="flex items-center justify-between px-4 py-3">
          <Logo />
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="icon-btn text-neutral-300">
            {sidebarOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
      </div>

      {/* Mobile drawer */}
      <AnimatePresence>
        {sidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-30 lg:hidden"
            style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)' }}
            onClick={() => setSidebarOpen(false)}
          >
            <motion.div
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', damping: 32, stiffness: 340 }}
              className="absolute left-0 top-0 bottom-0 w-[240px] p-3 pt-20 flex flex-col"
              style={{ background: '#050505', borderRight: '1px solid rgba(255,255,255,0.08)' }}
              onClick={(e) => e.stopPropagation()}
            >
              <NavItems onNavigate={() => setSidebarOpen(false)} />
              <div className="mt-auto">
                <StatusFooter />
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Content */}
      <main className="flex-1 min-w-0 pt-14 lg:pt-0">
        <div className="max-w-[1080px] mx-auto px-5 lg:px-10 py-8 lg:py-10">
          <AnimatePresence mode="wait">
            <motion.div
              key={sectionKey}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.16, ease: 'easeOut' }}
            >
              <Routes location={location}>
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/accounts" element={<Navigate to="/accounts/available" replace />} />
                <Route path="/accounts/:tab" element={<AccountManager />} />
                {WorkerPage && (
                  <Route
                    path="/worker"
                    element={
                      <Suspense fallback={null}>
                        <WorkerPage />
                      </Suspense>
                    }
                  />
                )}
                <Route path="/status" element={<Status />} />
                <Route path="/logs" element={<Logs />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<Navigate to="/dashboard" replace />} />
              </Routes>
            </motion.div>
          </AnimatePresence>
        </div>
      </main>
    </div>
  )
}