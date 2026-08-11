import { motion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ScrollText, Trash2, Pause, Play } from 'lucide-react'
import { Card, SectionTitle } from '../ui/GlassPanel'

const BASE = ''

type LogEvent = {
  seq: number
  ts: number
  level: 'info' | 'warn' | 'error'
  source: string
  message: string
  [key: string]: unknown
}

const LEVEL_COLOR: Record<string, string> = {
  info: 'text-neutral-500',
  warn: 'text-amber-400/80',
  error: 'text-red-400/90',
}

const SOURCE_COLOR: Record<string, string> = {
  chat: 'text-blue-400/70',
  pool: 'text-emerald-400/70',
  worker: 'text-violet-400/70',
}

function fmtTs(ts: number) {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('en-GB', { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0')
}

function fmtExtra(evt: LogEvent): string {
  const skip = new Set(['seq', 'ts', 'level', 'source', 'message'])
  const parts: string[] = []
  for (const [k, v] of Object.entries(evt)) {
    if (skip.has(k) || v === null || v === undefined) continue
    if (typeof v === 'number' && v > 1000) parts.push(`${k}=${Math.round(v).toLocaleString()}`)
    else if (typeof v === 'number' && v < 1 && v > 0) parts.push(`${k}=${v.toFixed(4)}`)
    else parts.push(`${k}=${v}`)
  }
  return parts.length ? ` · ${parts.join(' · ')}` : ''
}

export function Logs() {
  const [paused, setPaused] = useState(false)
  const [events, setEvents] = useState<LogEvent[]>([])
  const [live, setLive] = useState(true)
  const logRef = useRef<HTMLDivElement>(null)
  const evtSourceRef = useRef<EventSource | null>(null)
  const lastSeqRef = useRef(0)

  // initial fetch
  const { data: initial } = useQuery<{ logs: LogEvent[] }>({
    queryKey: ['logs-initial'],
    queryFn: async () => {
      const res = await fetch(`${BASE}/api/logs?limit=200`)
      return res.json()
    },
    staleTime: 0,
  })

  // hydrate from initial fetch
  useEffect(() => {
    if (initial?.logs) {
      setEvents(initial.logs)
      lastSeqRef.current = initial.logs[initial.logs.length - 1]?.seq ?? 0
    }
  }, [initial])

  // live SSE stream
  useEffect(() => {
    if (!live || paused) {
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
        setEvents((prev) => [...prev.slice(-500), evt])
      } catch { /* keepalive or malformed */ }
    }

    return () => {
      es.close()
      evtSourceRef.current = null
    }
  }, [live, paused])

  // autoscroll
  useEffect(() => {
    const el = logRef.current
    if (el && !paused) el.scrollTop = el.scrollHeight
  }, [events.length, paused])

  const clear = () => {
    // Keep lastSeqRef as-is: on SSE reconnect the server replays its buffer,
    // and only the seq filter keeps already-cleared events from reappearing.
    setEvents([])
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] } }}
      className="space-y-6"
    >
      {/* Header */}
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-[24px] font-bold text-white tracking-tight">Logs</h1>
          <p className="text-sm text-neutral-500 mt-1">Router activity stream — requests, thinking, pool events</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPaused(!paused)}
            className="icon-btn"
            title={paused ? 'Resume' : 'Pause'}
          >
            {paused ? <Play size={14} /> : <Pause size={14} />}
          </button>
          <button onClick={clear} className="icon-btn" title="Clear">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Log stream */}
      <Card className="p-5">
        <SectionTitle
          icon={<ScrollText size={13} className="text-neutral-400" />}
          right={
            <span className="flex items-center gap-2 text-[10px] text-neutral-600 font-mono">
              <span className={`w-1.5 h-1.5 rounded-full ${live && !paused ? 'bg-emerald-400 animate-pulse' : 'bg-neutral-600'}`} />
              {live && !paused ? 'LIVE' : 'PAUSED'}
              <span className="text-neutral-700">·</span>
              {events.length} events
            </span>
          }
        >
          Activity Stream
        </SectionTitle>

        <div
          ref={logRef}
          className="rounded-lg overflow-y-auto max-h-[560px] min-h-[300px] p-3 font-mono text-[11px] leading-relaxed"
          style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          {events.length === 0 ? (
            <div className="text-neutral-700">No activity yet — send a request to see logs here.</div>
          ) : (
            events.map((evt) => (
              <div key={evt.seq} className="flex gap-2 py-0.5 hover:bg-white/[0.02] -mx-1 px-1 rounded">
                <span className="text-neutral-700 shrink-0 tabular-nums">{fmtTs(evt.ts)}</span>
                <span className={`shrink-0 w-14 ${SOURCE_COLOR[evt.source] ?? 'text-neutral-500'}`}>
                  {evt.source}
                </span>
                <span className={`${LEVEL_COLOR[evt.level] ?? 'text-neutral-500'}`}>
                  {evt.message}
                  <span className="text-neutral-700">{fmtExtra(evt)}</span>
                </span>
              </div>
            ))
          )}
        </div>
      </Card>
    </motion.div>
  )
}
