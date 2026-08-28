import { motion } from 'framer-motion'
import type { ReactNode } from 'react'
import { cn } from '../../lib/utils'

/* ── Card ── */
export function Card({ children, className, glow }: { children: ReactNode; className?: string; glow?: boolean }) {
  return (
    <div className={cn('card', className)}>
      {children}
    </div>
  )
}

/* ── Section heading ── */
export function SectionTitle({ icon, children, right }: { icon?: ReactNode; children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-4">
      <h3 className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-neutral-500">
        {icon}
        {children}
      </h3>
      {right}
    </div>
  )
}

/* ── Header badge — small pill shown in page headers (Live, interval, etc.) ── */
export function HeaderBadge({ icon, children, pulse }: { icon?: ReactNode; children: ReactNode; pulse?: boolean }) {
  return (
    <span
      className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11px] font-medium text-neutral-400"
      style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}
    >
      {pulse ? (
        <span className="pulse-dot w-1.5 h-1.5 rounded-full" style={{ backgroundColor: '#d4d4d4', color: '#d4d4d4' }} />
      ) : icon ? (
        <span className="text-neutral-500 flex items-center">{icon}</span>
      ) : null}
      {children}
    </span>
  )
}

/* ── Status badge (monochrome) ── */
type Status = 'active' | 'error'

const STATUS_META: Record<Status, { chip: string; label: string; pulse: boolean; filled: boolean }> = {
  active:   { chip: 'chip-solid',   label: 'Available', pulse: true,  filled: true },
  error:    { chip: 'chip-outline', label: 'Error',     pulse: false, filled: false },
}

export function StatusBadge({ status }: { status: Status }) {
  const meta = STATUS_META[status]
  return (
    <span className={`chip ${meta.chip}`}>
      <svg width="8" height="8" viewBox="0 0 8 8" className={meta.pulse ? 'pulse-dot' : ''}>
        {status === 'error' ? (
          <>
            <path d="M1 1l6 6M7 1L1 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </>
        ) : (
          <circle cx="4" cy="4" r="3" fill={meta.filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.2" />
        )}
      </svg>
      {meta.label}
    </span>
  )
}

/* ── Modal ── */
export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  children: ReactNode
}) {
  if (!open) return null
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0, 0, 0, 0.92)' }}
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.97, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ type: 'spring', damping: 30, stiffness: 400 }}
        className="w-full max-w-md overflow-hidden rounded-2xl"
        style={{
          background: '#0a0a0a',
          border: '1px solid rgba(255,255,255,0.12)',
          boxShadow: '0 32px 80px -16px rgba(0,0,0,0.9), 0 0 0 1px rgba(255,255,255,0.04) inset',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="h-px" style={{ background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent)' }} />
        <div className="p-6">
          <div className="flex items-start justify-between mb-5">
            <div>
              <h2 className="text-[15px] font-semibold text-white tracking-tight">{title}</h2>
              {subtitle && <p className="text-xs text-neutral-500 mt-1">{subtitle}</p>}
            </div>
            <button onClick={onClose} className="icon-btn -mr-1 -mt-1" aria-label="Close">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
          {children}
        </div>
      </motion.div>
    </motion.div>
  )
}

/* ── monochrome switch ── */
export function Switch({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="relative w-9 h-5 rounded-full transition-colors duration-150 disabled:opacity-40 disabled:pointer-events-none shrink-0"
      style={{ background: checked ? '#fafafa' : 'rgba(255,255,255,0.12)' }}
    >
      <span
        className="absolute top-0.5 w-4 h-4 rounded-full transition-all duration-150"
        style={{
          left: checked ? '18px' : '2px',
          background: checked ? '#000' : '#a3a3a3',
        }}
      />
    </button>
  )
}

/* ── Skeleton ── */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('shimmer rounded-xl', className)} />
}

/* ── Empty state ── */
export function EmptyState({ icon, title, hint, action }: { icon: ReactNode; title: string; hint: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-6 text-center">
      <div
        className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4 text-neutral-500"
        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}
      >
        {icon}
      </div>
      <p className="text-sm font-medium text-neutral-200">{title}</p>
      <p className="text-xs text-neutral-500 mt-1 max-w-xs">{hint}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}