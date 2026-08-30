import { motion, AnimatePresence } from 'framer-motion'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  ScrollText,
  Trash2,
  Pause,
  Play,
  Search,
  X,
  Copy,
  Check,
  Users,
} from 'lucide-react'
import { Card, HeaderBadge, SectionTitle, Skeleton } from '../ui/GlassPanel'
import type { LogEvent, LogOutcome, RequestSummary } from '../../types'

const BASE = ''

type ViewMode = 'requests' | 'pool'
type RequestRow = RequestSummary & { events: LogEvent[] }

/** Result column — HTTP-ish status for the request outcome. */
const RESULT_STATUS: Record<string, string> = {
  ok: '200 OK',
  quota: '402 QUOTA',
  queue: '503 QUEUE',
  rate_limit: '429',
  infra: '503',
  account: '502',
}

const POOL_ACTION_LABEL: Record<string, string> = {
  added: 'ADDED',
  removed: 'REMOVED',
  parked: 'PARKED',
  auto_deleted: 'AUTO-DEL',
  cooldown: 'COOLDOWN',
  restored: 'RESTORED',
}

function fmtTs(ts: number) {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('en-GB', { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0')
}

function fmtDur(ms: number | null | undefined) {
  if (ms == null || !Number.isFinite(ms)) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtCredits(n: number | null | undefined) {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

/** Infer action for legacy pool lines that predate the structured field. */
function poolActionOf(e: LogEvent): string | undefined {
  if (e.action) return e.action
  const m = (e.message || '').toLowerCase()
  if (m.includes('auto-deleted')) return 'auto_deleted'
  if (m.includes('parked')) return 'parked'
  if (m.includes('added')) return 'added'
  if (m.includes('removed') || m.includes('deleted')) return 'removed'
  if (m.includes('cooldown')) return 'cooldown'
  if (m.includes('restored')) return 'restored'
  return undefined
}

/** One status mark for the Result column (and rare non-ok callouts elsewhere). */
function ResultStatus({ outcome, live }: { outcome?: string; live?: boolean }) {
  if (live && outcome !== 'ok') {
    return (
      <span className="chip chip-muted text-neutral-300">
        <span className="pulse-dot w-1.5 h-1.5 rounded-full bg-neutral-300" />
        live
      </span>
    )
  }
  const label = outcome ? RESULT_STATUS[outcome] : null
  if (!label) return <span className="text-neutral-700">—</span>
  if (outcome === 'ok') return <span className="chip chip-solid">{label}</span>
  return <span className="chip chip-outline">{label}</span>
}

function PoolActionChip({ action }: { action?: string }) {
  if (!action) return <span className="text-neutral-700">—</span>
  const label = POOL_ACTION_LABEL[action] || action.toUpperCase()
  if (action === 'added' || action === 'restored') {
    return <span className="chip chip-solid">{label}</span>
  }
  if (action === 'removed' || action === 'auto_deleted' || action === 'parked') {
    return <span className="chip chip-outline">{label}</span>
  }
  return <span className="chip chip-muted">{label}</span>
}

function applyEvent(row: RequestRow, e: LogEvent): RequestRow {
  const terminal = e.phase === 'done' || e.phase === 'error'
  const events = row.events.some((x) => x.seq === e.seq)
    ? row.events
    : [...row.events, e].sort((a, b) => a.seq - b.seq)
  return {
    ...row,
    last_ts: e.ts,
    level: e.level,
    message: e.message,
    dialect: e.dialect ?? row.dialect,
    model: e.model ?? row.model,
    account_id: e.account_id ?? row.account_id,
    account_name: e.account_name ?? row.account_name,
    phase: e.phase ?? row.phase,
    outcome: e.outcome ?? row.outcome,
    prompt_tokens: e.prompt_tokens ?? row.prompt_tokens,
    completion_tokens: e.completion_tokens ?? row.completion_tokens,
    total_tokens: e.total_tokens ?? row.total_tokens,
    credits: e.credits ?? row.credits,
    latency_ms: e.latency_ms ?? row.latency_ms,
    first_token_ms: e.first_token_ms ?? row.first_token_ms,
    thinking_chars: e.thinking_chars ?? row.thinking_chars,
    tool_calls: e.tool_calls ?? row.tool_calls,
    finish_reason: e.finish_reason ?? row.finish_reason,
    live: terminal ? false : true,
    events,
  }
}

function buildRows(seed: RequestSummary[], events: LogEvent[]): RequestRow[] {
  const map = new Map<string, RequestRow>()
  for (const s of seed) {
    map.set(s.request_id, { ...s, events: [] })
  }
  for (const e of events) {
    if (!e.request_id) continue
    const prev = map.get(e.request_id) ?? {
      request_id: e.request_id,
      ts: e.ts,
      last_ts: e.ts,
      live: true,
      events: [],
    }
    map.set(e.request_id, applyEvent(prev, e))
  }
  return [...map.values()].sort((a, b) => (b.last_ts || 0) - (a.last_ts || 0))
}

function matchesSearch(hay: string, q: string) {
  return !q || hay.toLowerCase().includes(q)
}

function phaseCount(events: LogEvent[], phase: string) {
  return events.filter((e) => e.phase === phase).length
}

const HEAD_GRID =
  'hidden md:grid md:grid-cols-[88px_minmax(104px,0.85fr)_minmax(110px,1fr)_minmax(100px,1fr)_64px_72px_64px_64px]'
const ROW_GRID =
  'grid grid-cols-[minmax(0,1fr)_auto] md:grid-cols-[88px_minmax(104px,0.85fr)_minmax(110px,1fr)_minmax(100px,1fr)_64px_72px_64px_64px]'

const POOL_HEAD =
  'hidden md:grid md:grid-cols-[88px_minmax(100px,0.7fr)_minmax(0,1fr)]'
const POOL_ROW =
  'grid grid-cols-1 md:grid-cols-[88px_minmax(100px,0.7fr)_minmax(0,1fr)]'

function poolDetail(e: LogEvent): string {
  const name = e.account_name || (e.account_id != null ? `id ${e.account_id}` : '')
  const reason = e.reason?.trim()
  const message = e.message?.trim()
  if (reason) {
    if (name && !reason.toLowerCase().includes(name.toLowerCase())) {
      return `${name} · ${reason}`
    }
    return reason
  }
  return message || name || '—'
}

export function Logs() {
  const [params, setParams] = useSearchParams()
  const accountFilter = params.get('account')
  const selectedId = params.get('request')
  const outcomeFilter = (params.get('outcome') || '') as LogOutcome | ''
  const modelFilter = params.get('model') || ''
  const view: ViewMode = params.get('view') === 'pool' ? 'pool' : 'requests'
  const [query, setQuery] = useState(params.get('q') || '')
  const [paused, setPaused] = useState(false)
  const [copied, setCopied] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [events, setEvents] = useState<LogEvent[]>([])
  const [seed, setSeed] = useState<RequestSummary[]>([])
  /** 1 = toward Pool (enter from right), -1 = toward Requests (enter from left). */
  const [slideDir, setSlideDir] = useState(1)
  /** Keeps the 2-col shell mounted through the drawer exit animation. */
  const [drawerShell, setDrawerShell] = useState(false)
  const [drawerRow, setDrawerRow] = useState<RequestRow | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const evtSourceRef = useRef<EventSource | null>(null)
  const lastSeqRef = useRef(0)
  const queryClient = useQueryClient()

  const setParam = useCallback((key: string, value: string | null) => {
    const next = new URLSearchParams(params)
    if (value == null || value === '') next.delete(key)
    else next.set(key, value)
    setParams(next, { replace: true })
  }, [params, setParams])

  const setView = useCallback((next: ViewMode) => {
    if (next === view) return
    const order: Record<ViewMode, number> = { requests: 0, pool: 1 }
    setSlideDir(order[next] > order[view] ? 1 : -1)
    const p = new URLSearchParams(params)
    if (next === 'requests') p.delete('view')
    else p.set('view', next)
    if (next === 'pool') p.delete('request')
    setParams(p, { replace: true })
  }, [params, setParams, view])

  // Tear down drawer shell immediately when leaving Requests (no mid-layout flash).
  useLayoutEffect(() => {
    if (view !== 'requests') {
      setDrawerShell(false)
      setDrawerRow(null)
    }
  }, [view])

  const { data: initial, isLoading } = useQuery<{ logs: LogEvent[]; requests: RequestSummary[] }>({
    queryKey: ['logs-initial'],
    queryFn: async () => {
      const res = await fetch(`${BASE}/api/logs?limit=500`)
      if (!res.ok) throw new Error('Failed to load logs')
      return res.json()
    },
    staleTime: 0,
  })

  useEffect(() => {
    if (!initial) return
    setEvents(initial.logs || [])
    setSeed(initial.requests || [])
    lastSeqRef.current = initial.logs?.[initial.logs.length - 1]?.seq ?? 0
  }, [initial])

  useEffect(() => {
    if (paused) {
      evtSourceRef.current?.close()
      evtSourceRef.current = null
      return
    }
    const es = new EventSource(`${BASE}/api/logs/stream`)
    evtSourceRef.current = es
    es.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data) as LogEvent
        if (evt.seq <= lastSeqRef.current) return
        lastSeqRef.current = evt.seq
        setEvents((prev) => [...prev.slice(-1500), evt])
      } catch { /* keepalive */ }
    }
    return () => {
      es.close()
      evtSourceRef.current = null
    }
  }, [paused])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      const typing = tag === 'INPUT' || tag === 'TEXTAREA'
      if (e.key === '/' && !typing) {
        e.preventDefault()
        searchRef.current?.focus()
      }
      if (e.key === 'Escape') {
        if (selectedId) setParam('request', null)
        else if (query) setQuery('')
        else if (document.activeElement === searchRef.current) searchRef.current?.blur()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId, query, setParam])

  const rows = useMemo(() => buildRows(seed, events), [seed, events])

  const q = query.trim().toLowerCase()
  const accountId = accountFilter && Number.isFinite(Number(accountFilter))
    ? Number(accountFilter)
    : null

  // Resolve display name for ?account= — PATs get a new id after delete/re-add,
  // so filter must also match historical rows that still carry the old id.
  const accountChipName = useMemo(() => {
    if (accountId == null) return undefined
    return (
      rows.find((r) => r.account_id === accountId)?.account_name
      || events.find((e) => e.source === 'pool' && e.account_id === accountId)?.account_name
      || undefined
    )
  }, [accountId, rows, events])

  const matchesAccount = useCallback((account_id?: number | null, account_name?: string | null) => {
    if (accountId == null) return true
    if (account_id === accountId) return true
    if (accountChipName && account_name && account_name === accountChipName) return true
    return false
  }, [accountId, accountChipName])

  const filteredRows = useMemo(() => {
    return rows.filter((r) => {
      if (!matchesAccount(r.account_id, r.account_name)) return false
      if (modelFilter && r.model !== modelFilter) return false
      if (outcomeFilter && r.outcome !== outcomeFilter) return false
      if (!q) return true
      return matchesSearch(
        [r.request_id, r.account_name, r.model, r.message, r.outcome, r.dialect].join(' '),
        q,
      )
    })
  }, [rows, matchesAccount, modelFilter, outcomeFilter, q])

  const poolEvents = useMemo(() => {
    return events
      .filter((e) => e.source === 'pool')
      .filter((e) => {
        if (!matchesAccount(e.account_id, e.account_name)) return false
        if (!q) return true
        const action = poolActionOf(e)
        return matchesSearch(
          [e.account_name, e.account_id, action, e.reason, e.message].join(' '),
          q,
        )
      })
      .slice()
      .sort((a, b) => b.ts - a.ts)
  }, [events, matchesAccount, q])

  const stats = useMemo(() => {
    let ok = 0
    let fail = 0
    let liveN = 0
    let credits = 0
    for (const r of filteredRows) {
      if (r.live) liveN += 1
      else if (r.outcome === 'ok') ok += 1
      else if (r.outcome) fail += 1
      credits += r.credits || 0
    }
    return { ok, fail, liveN, credits }
  }, [filteredRows])

  const selected = selectedId ? rows.find((r) => r.request_id === selectedId) : undefined
  const showDrawer = view === 'requests' && Boolean(selected)

  useLayoutEffect(() => {
    if (selected && view === 'requests') {
      setDrawerRow(selected)
      setDrawerShell(true)
    }
  }, [selected, view])

  const clear = async () => {
    if (clearing) return
    setClearing(true)
    try {
      const res = await fetch(`${BASE}/api/logs`, { method: 'DELETE' })
      if (!res.ok) throw new Error('clear failed')
      setEvents([])
      setSeed([])
      setDrawerShell(false)
      setDrawerRow(null)
      if (selectedId) setParam('request', null)
      // Keep lastSeq so any late/replayed pre-clear SSE lines are skipped;
      // the next real push has a higher seq and still lands.
      queryClient.setQueryData(['logs-initial'], { logs: [], requests: [] })
    } catch {
      /* keep current view */
    } finally {
      setClearing(false)
    }
  }

  const copyId = async (id: string) => {
    try {
      await navigator.clipboard.writeText(id)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1200)
    } catch { /* ignore */ }
  }

  const emptyHint = accountId != null
    ? 'No requests for this account in the current window.'
    : 'Send a chat request through the pool — outcomes land here.'

  const poolEmptyHint = accountId != null
    ? 'No pool events for this account in the current window.'
    : 'Add, delete, park, or refresh accounts — lifecycle events land here.'

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-[24px] font-bold text-white tracking-tight">Logs</h1>
          <p className="text-sm text-neutral-500 mt-1">
            {view === 'requests'
              ? 'Request timeline — pool, swaps, outcomes'
              : 'Pool lifecycle — add, park, delete, cooldown'}
          </p>
          {/* Always reserve one stats line so the header height doesn't jump. */}
          <p className="text-[11px] font-mono text-neutral-600 mt-2 tabular-nums min-h-[16px]">
            {view === 'requests' && filteredRows.length > 0 ? (
              <>
                {stats.liveN > 0 && <span>{stats.liveN} live · </span>}
                {stats.ok} ok
                {stats.fail > 0 && <span> · {stats.fail} failed</span>}
                {stats.credits > 0 && <span> · {fmtCredits(stats.credits)} cr</span>}
              </>
            ) : view === 'pool' && poolEvents.length > 0 ? (
              <>{poolEvents.length} event{poolEvents.length === 1 ? '' : 's'}</>
            ) : (
              '\u00a0'
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative grid grid-cols-2 rounded-lg border border-white/[0.08] p-0.5 bg-white/[0.02]">
            {(['requests', 'pool'] as const).map((id) => {
              const active = view === id
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => setView(id)}
                  className={`relative px-2.5 py-1 text-center text-[11px] font-semibold uppercase tracking-[0.08em] rounded-md transition-colors ${
                    active ? 'text-black' : 'text-neutral-500 hover:text-neutral-300'
                  }`}
                >
                  {active && (
                    <motion.span
                      layoutId="logs-view-pill"
                      className="absolute inset-0 rounded-md bg-white"
                      transition={{ type: 'spring', damping: 32, stiffness: 420 }}
                    />
                  )}
                  <span className="relative z-[1]">{id === 'requests' ? 'Requests' : 'Pool'}</span>
                </button>
              )
            })}
          </div>
          <button onClick={() => setPaused(!paused)} className="icon-btn" title={paused ? 'Resume' : 'Pause'}>
            {paused ? <Play size={14} /> : <Pause size={14} />}
          </button>
          <button
            onClick={clear}
            disabled={clearing}
            className="icon-btn disabled:opacity-40"
            title="Clear logs"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <div className="relative flex-1 min-w-0">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-600" />
          <input
            ref={searchRef}
            className="input pl-8 h-9 text-[13px]"
            placeholder="Search  ·  /"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {accountId != null && (
          <button
            onClick={() => setParam('account', null)}
            className="chip chip-solid shrink-0"
          >
            {accountChipName || `account ${accountId}`}
            <X size={10} />
          </button>
        )}
      </div>

      <div className={drawerShell ? 'lg:grid lg:grid-cols-[1fr_320px] lg:gap-4' : ''}>
        <Card className="overflow-hidden lg:self-start">
          <div className="px-5 pt-5">
            <SectionTitle
              icon={
                view === 'pool'
                  ? <Users size={13} className="text-neutral-400" />
                  : <ScrollText size={13} className="text-neutral-400" />
              }
              right={
                <HeaderBadge pulse={!paused}>
                  {paused ? 'Paused' : 'Live'}
                  <span className="text-neutral-600">·</span>
                  {view === 'pool' ? poolEvents.length : filteredRows.length}
                </HeaderBadge>
              }
            >
              {view === 'pool' ? 'Pool' : 'Requests'}
            </SectionTitle>
          </div>

          <motion.div
            key={view}
            initial={{ opacity: 0, x: slideDir * 10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.16, ease: 'easeOut' }}
          >
                {view === 'pool' ? (
                  isLoading && poolEvents.length === 0 ? (
                    <div className="px-5 pb-5 space-y-3">
                      {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12" />)}
                    </div>
                  ) : poolEvents.length === 0 ? (
                    <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
                      <div
                        className="w-11 h-11 rounded-xl flex items-center justify-center mb-3 text-neutral-500"
                        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}
                      >
                        <Users size={18} />
                      </div>
                      <p className="text-sm font-medium text-neutral-200">No pool events yet</p>
                      <p className="text-xs text-neutral-500 mt-1 max-w-xs">{poolEmptyHint}</p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <div
                        className={`${POOL_HEAD} gap-4 px-5 py-2.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-neutral-600`}
                        style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}
                      >
                        <span>Time</span>
                        <span>Action</span>
                        <span>Detail</span>
                      </div>
                      {poolEvents.map((e) => {
                        const action = poolActionOf(e)
                        const detail = poolDetail(e)
                        return (
                          <div
                            key={e.seq}
                            className={`${POOL_ROW} w-full items-center gap-x-4 gap-y-1 px-5 py-3.5`}
                            style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}
                          >
                            <div className="min-w-0 space-y-1 md:contents">
                              <div className="font-mono text-[11px] tabular-nums text-neutral-500">
                                {fmtTs(e.ts)}
                              </div>
                              <div className="inline-flex items-center md:mt-0">
                                <PoolActionChip action={action} />
                              </div>
                              <div className="text-[12px] text-neutral-400 truncate" title={detail}>
                                {detail}
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )
                ) : isLoading && filteredRows.length === 0 ? (
                  <div className="px-5 pb-5 space-y-3">
                    {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12" />)}
                  </div>
                ) : filteredRows.length === 0 ? (
                  <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
                    <div
                      className="w-11 h-11 rounded-xl flex items-center justify-center mb-3 text-neutral-500"
                      style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}
                    >
                      <ScrollText size={18} />
                    </div>
                    <p className="text-sm font-medium text-neutral-200">No requests yet</p>
                    <p className="text-xs text-neutral-500 mt-1 max-w-xs">{emptyHint}</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <div
                      className={`${HEAD_GRID} gap-4 px-5 py-2.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-neutral-600`}
                      style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}
                    >
                      <span>Time</span>
                      <span>Result</span>
                      <span>Model</span>
                      <span>Account</span>
                      <span className="text-right">Tok</span>
                      <span className="text-right">Credits</span>
                      <span className="text-right">TTFT</span>
                      <span className="text-right">Total</span>
                    </div>
                    {filteredRows.map((r) => {
                      const active = r.request_id === selectedId
                      const swaps = phaseCount(r.events, 'swap')
                      const retries = phaseCount(r.events, 'retry')
                      return (
                        <button
                          key={r.request_id}
                          type="button"
                          onClick={() => setParam('request', active ? null : r.request_id)}
                          title={r.request_id}
                          className={`${ROW_GRID} w-full text-left items-center gap-x-4 gap-y-1.5 px-5 py-3.5 transition-colors ${
                            active ? 'bg-white/[0.04]' : 'hover:bg-white/[0.02]'
                          }`}
                          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}
                        >
                          <div className="min-w-0 md:contents">
                            <div className="font-mono text-[11px] tabular-nums text-neutral-500">
                              {fmtTs(r.last_ts || r.ts)}
                            </div>
                            <div className="inline-flex items-center gap-1.5 flex-wrap mt-1.5 md:mt-0">
                              <ResultStatus outcome={r.outcome} live={r.live} />
                              {swaps > 0 && (
                                <span className="text-[10px] font-mono text-neutral-600">swap×{swaps}</span>
                              )}
                              {retries > 0 && (
                                <span className="text-[10px] font-mono text-neutral-600">retry×{retries}</span>
                              )}
                            </div>
                            <div className="font-mono text-[12px] text-neutral-200 truncate mt-1 md:mt-0">
                              {r.model || '—'}
                            </div>
                            <div className="text-[12px] text-neutral-400 truncate md:mt-0">
                              {r.account_name || r.account_id || '—'}
                            </div>
                          </div>
                          <div className="hidden md:block text-right tabular-nums text-[12px] text-neutral-400">
                            {r.completion_tokens?.toLocaleString() || '—'}
                          </div>
                          <div className="hidden md:block text-right tabular-nums text-[12px] text-neutral-300">
                            {fmtCredits(r.credits)}
                          </div>
                          <div className="hidden md:block text-right tabular-nums text-[12px] text-neutral-500">
                            {fmtDur(r.first_token_ms)}
                          </div>
                          <div className="text-right tabular-nums text-[11px] md:text-[12px] font-mono md:font-sans text-neutral-500 md:text-neutral-400">
                            {fmtDur(r.latency_ms)}
                          </div>
                        </button>
                      )
                    })}
                  </div>
                )}
          </motion.div>
        </Card>

        <AnimatePresence
          onExitComplete={() => {
            if (!showDrawer) {
              setDrawerShell(false)
              setDrawerRow(null)
            }
          }}
        >
          {showDrawer && drawerRow && (
            <motion.div
              key="timeline-drawer"
              initial={{ opacity: 0, x: 28 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 16 }}
              transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
              className="h-full min-h-0"
            >
              <Card className="p-5 h-full flex flex-col">
                <SectionTitle
                  right={
                    <button onClick={() => setParam('request', null)} className="icon-btn w-7 h-7" title="Close">
                      <X size={12} />
                    </button>
                  }
                >
                  Timeline
                </SectionTitle>
                <div className="space-y-3 mb-4 shrink-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-[12px] text-white">{drawerRow.model || '—'}</span>
                    {drawerRow.dialect && (
                      <span className="chip chip-muted">{drawerRow.dialect}</span>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-2.5 text-[11px]">
                    <Meta label="Account" value={String(drawerRow.account_name || drawerRow.account_id || '—')} />
                    <div>
                      <div className="text-[10px] uppercase tracking-[0.1em] text-neutral-600 font-semibold">Request</div>
                      <button
                        onClick={() => copyId(drawerRow.request_id)}
                        className="mt-0.5 flex items-center gap-1 font-mono text-[11px] text-neutral-200 hover:text-white"
                        title="Copy request id"
                      >
                        <span className="truncate">{drawerRow.request_id}</span>
                        {copied ? <Check size={10} /> : <Copy size={10} className="text-neutral-600 shrink-0" />}
                      </button>
                    </div>
                    <Meta label="Tokens" value={drawerRow.completion_tokens?.toLocaleString() || '—'} />
                    <Meta label="Credits" value={fmtCredits(drawerRow.credits)} />
                    <Meta label="First token" value={fmtDur(drawerRow.first_token_ms)} />
                    <Meta label="Duration" value={fmtDur(drawerRow.latency_ms)} />
                    {drawerRow.finish_reason && <Meta label="Finish" value={drawerRow.finish_reason} />}
                    {drawerRow.tool_calls ? <Meta label="Tools" value={String(drawerRow.tool_calls)} /> : null}
                  </div>
                </div>
                <div className="flex-1 min-h-0 overflow-y-auto -mx-1">
                  {drawerRow.events.length === 0 ? (
                    <p className="text-[11px] text-neutral-600 leading-relaxed px-1">
                      Restored after a restart — the live timeline is gone, the summary stayed.
                    </p>
                  ) : (
                    drawerRow.events.map((e, i) => (
                      <div key={e.seq} className="flex gap-2.5 py-1.5 px-1">
                        <div className="flex flex-col items-center w-3 shrink-0 pt-1.5">
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              e.phase === 'done' ? 'bg-white' : e.phase === 'error' ? 'bg-neutral-300' : 'bg-neutral-600'
                            }`}
                          />
                          {i < drawerRow.events.length - 1 && (
                            <span className="w-px flex-1 bg-white/10 mt-1 min-h-[12px]" />
                          )}
                        </div>
                        <div className="min-w-0 flex-1 pb-1">
                          <div className="flex items-center gap-1.5">
                            {e.phase && (
                              <span className="text-[10px] uppercase tracking-[0.1em] text-neutral-500 font-semibold">
                                {e.phase}
                              </span>
                            )}
                            {e.outcome && e.outcome !== 'ok' && <ResultStatus outcome={e.outcome} />}
                            <span className="ml-auto text-neutral-700 tabular-nums font-mono text-[10px]">{fmtTs(e.ts)}</span>
                          </div>
                          <div className={`text-[12px] ${
                            e.level === 'error' ? 'text-neutral-100' : e.level === 'warn' ? 'text-neutral-300' : 'text-neutral-400'
                          }`}>
                            {e.message}
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </Card>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.1em] text-neutral-600 font-semibold">{label}</div>
      <div className="text-neutral-200 mt-0.5 truncate">{value}</div>
    </div>
  )
}
