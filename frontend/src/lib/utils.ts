import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatNumber(num: number): string {
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M'
  if (num >= 1_000) return (num / 1_000).toFixed(1) + 'K'
  return num.toString()
}

/** Backend sends naive UTC datetimes without an offset marker ("2026-08-11T10:00:00").
 *  Bare ISO strings parse as LOCAL time in JS — append Z so they read as UTC. */
function parseUtc(dateStr: string): number {
  if (/[zZ]|[+-]\d{2}:?\d{2}$/.test(dateStr)) return new Date(dateStr).getTime()
  return new Date(dateStr + 'Z').getTime()
}

export function timeAgo(dateStr: string | null): string {
  if (!dateStr) return 'Never'
  const now = Date.now()
  const date = parseUtc(dateStr)
  const diff = now - date
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

/** Plan end info from a Qoder epoch (ms; seconds tolerated).
 *  Returns display label + days left, or null when unknown. */
export function planEndInfo(epoch: number | null): { label: string; daysLeft: number } | null {
  if (epoch == null || !isFinite(epoch) || epoch <= 0) return null
  const ms = epoch < 1e12 ? epoch * 1000 : epoch
  const daysLeft = Math.ceil((ms - Date.now()) / 86400000)
  const dateStr = new Date(ms).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
  return { label: dateStr, daysLeft }
}

export function getModelColor(level: string): string {
  const colors: Record<string, string> = {
    qmodel_preview: '#818cf8',
    qmodel_38max: '#818cf8',
    qmodel_latest: '#6366f1',
    qmodel: '#4f46e5',
    kmodel_latest: '#2dd4bf',
    kmodel: '#14b8a6',
    gm51model: '#f59e0b',
    dmodel: '#ef4444',
    dfmodel: '#f97316',
    mmodel: '#a855f7',
  }
  return colors[level] || '#6b7280'
}
