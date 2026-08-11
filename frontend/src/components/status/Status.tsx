import { motion } from 'framer-motion'
import { Activity, CircleAlert, Gauge, Timer, Clock3 } from 'lucide-react'
import { Card, SectionTitle, Skeleton, StatusBadge, EmptyState } from '../ui/GlassPanel'
import { useModelStatus } from '../../hooks/useApi'
import { timeAgo } from '../../lib/utils'
import type { ModelStatus } from '../../types'

const stagger = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.05 } },
}
const rise = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.22, 1, 0.36, 1] } },
}

function ModelCard({ m }: { m: ModelStatus }) {
  return (
    <motion.div variants={rise} layout>
      <Card className="p-5 h-full">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-semibold text-white tracking-tight truncate">{m.display}</div>
            <div className="text-[10px] text-neutral-600 font-mono mt-0.5 truncate">{m.model}</div>
          </div>
          <StatusBadge status={m.alive ? 'active' : 'error'} />
        </div>

        <div className="mt-4 flex items-end justify-between gap-3">
          {m.alive ? (
            <div>
              <div className="text-[26px] leading-none font-bold text-white tabular-nums tracking-tight">
                {m.tps.toFixed(1)}
              </div>
              <div className="text-[10px] text-neutral-600 uppercase tracking-wider mt-1">tok / sec</div>
            </div>
          ) : (
            <div className="text-[11px] text-neutral-600">no signal</div>
          )}
          <div className="text-right text-[11px] text-neutral-500 tabular-nums space-y-0.5">
            <div>{m.tokens} tok · {m.latency_ms} ms</div>
            <div className="text-neutral-600">{timeAgo(m.at ? new Date(m.at * 1000).toISOString() : null)}</div>
          </div>
        </div>

        {m.is_queued && (
          <div
            className="mt-3 px-3 py-2 rounded-lg text-[11px] font-semibold text-amber-400 flex items-center gap-2"
            style={{ background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.25)' }}
          >
            <Clock3 size={12} />
            model queued upstream (10605) — retry later
          </div>
        )}

        {m.error && !m.is_queued && (
          <div
            className="mt-3 px-3 py-2 rounded-lg text-[11px] font-mono text-neutral-300 line-clamp-2"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)' }}
          >
            {m.error}
          </div>
        )}
      </Card>
    </motion.div>
  )
}

export function Status() {
  const { data, isLoading } = useModelStatus()

  const models = data?.models ?? []
  const alive = models.filter((m) => m.alive).length
  const queued = models.filter((m) => !m.alive && m.is_queued).length
  const total = models.length

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-6">
      {/* Header */}
      <motion.div variants={rise} className="flex items-end justify-between">
        <div>
          <h1 className="text-[24px] font-bold text-white tracking-tight">Status</h1>
          <p className="text-sm text-neutral-500 mt-1">Model health probes — a short "Hello!" ping per model</p>
        </div>
        <div className="chip chip-outline">
          <Timer size={11} />
          {data?.enabled ? `every ${data.interval_minutes} min` : 'probing off'}
        </div>
      </motion.div>

      {isLoading ? (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => <Skeleton key={i} className="h-[140px]" />)}
        </div>
      ) : !data || data.models.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Activity size={20} />}
            title="No probes yet"
            hint={
              data?.enabled
                ? 'Waiting for the first probe cycle. It runs shortly after startup.'
                : 'Probing is disabled. Enable it in Settings to start measuring model health.'
            }
          />
        </Card>
      ) : (
        <>
          {/* Summary strip */}
          <motion.div variants={rise}>
            <Card className="px-5 py-4 flex items-center justify-between">
              <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.1em] text-neutral-500">
                <Gauge size={13} className="text-neutral-400" />
                Models
              </div>
              <div className="text-[11px] text-neutral-500 tabular-nums">
                <span className="text-neutral-100 font-semibold">{alive}</span> alive
                {queued > 0 && (
                  <>
                    <span className="mx-1.5 text-neutral-700">·</span>
                    <span className="text-amber-400 font-semibold">{queued}</span>
                    <span className="text-amber-400/70"> queued</span>
                  </>
                )}
                <span className="mx-1.5 text-neutral-700">·</span>
                <span className={total - alive - queued > 0 ? 'text-neutral-200 font-semibold' : ''}>{total - alive - queued}</span> error
                {data?.last_run && (
                  <>
                    <span className="mx-1.5 text-neutral-700">·</span>
                    last run {timeAgo(new Date(data.last_run * 1000).toISOString())}
                  </>
                )}
              </div>
            </Card>
          </motion.div>

          {/* Model cards */}
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.models.map((m) => <ModelCard key={m.model} m={m} />)}
          </div>
        </>
      )}
    </motion.div>
  )
}
