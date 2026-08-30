import { motion } from 'framer-motion'
import { useDashboardStats, usePoolStatus, useActivityStats } from '../../hooks/useApi'
import { Card, SectionTitle, Skeleton, HeaderBadge } from '../ui/GlassPanel'
import { timeAgo, formatNumber } from '../../lib/utils'
import { Activity, CircleAlert, CheckCircle2, Wallet } from 'lucide-react'
import {
  AreaChart, Area, CartesianGrid, XAxis, YAxis, ResponsiveContainer, Tooltip,
} from 'recharts'

const stagger = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.05 } },
}
const rise = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.32, ease: [0.22, 1, 0.36, 1] } },
}

const fmtTime = (t: number) =>
  new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

function TrafficTooltip({ active, payload, label }: {
  active?: boolean
  payload?: Array<{ dataKey?: string | number; value?: number }>
  label?: number
}) {
  if (!active || !payload?.length || label == null) return null
  const req = payload.find((p) => p.dataKey === 'requests')?.value ?? 0
  const tok = payload.find((p) => p.dataKey === 'tokens')?.value ?? 0
  return (
    <div
      className="rounded-lg px-3 py-2.5 text-[11px] font-mono"
      style={{
        background: '#0a0a0a',
        border: '1px solid rgba(255,255,255,0.14)',
        boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
      }}
    >
      <div className="text-[10px] text-neutral-600 uppercase tracking-wider mb-1.5">{fmtTime(label)}</div>
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-[2px] shrink-0 bg-neutral-200" />
          <span className="text-neutral-500">requests</span>
          <span className="ml-auto text-white font-semibold tabular-nums">{Number(req).toLocaleString()}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-[2px] shrink-0 bg-neutral-500" />
          <span className="text-neutral-500">tokens</span>
          <span className="ml-auto text-white font-semibold tabular-nums">{Number(tok).toLocaleString()}</span>
        </div>
      </div>
    </div>
  )
}

function TrafficChart({ series }: { series: { t: number; requests: number; tokens: number }[] }) {
  const empty = !series.some((p) => p.requests > 0 || p.tokens > 0)
  return (
    <div className="relative h-[220px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={series} margin={{ top: 8, right: 6, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="gradReq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#e5e5e5" stopOpacity={0.14} />
              <stop offset="100%" stopColor="#e5e5e5" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="gradTok" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#525252" stopOpacity={0.16} />
              <stop offset="100%" stopColor="#525252" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="rgba(255,255,255,0.05)" />
          <XAxis
            dataKey="t"
            tickFormatter={fmtTime}
            tick={{ fill: '#525252', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            tickMargin={8}
            minTickGap={50}
            height={26}
          />
          <YAxis
            yAxisId="req"
            orientation="left"
            allowDecimals={false}
            domain={[0, (dataMax: number) => Math.max(Math.ceil(dataMax * 1.2), 2)]}
            tick={{ fill: '#525252', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={28}
          />
          <YAxis
            yAxisId="tok"
            orientation="right"
            domain={[0, (dataMax: number) => Math.max(Math.ceil(dataMax * 1.15), 1)]}
            tickFormatter={(v: number) => formatNumber(v)}
            tick={{ fill: '#525252', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={36}
          />
          <Tooltip
            content={<TrafficTooltip />}
            cursor={{ stroke: 'rgba(255,255,255,0.18)', strokeWidth: 1 }}
            isAnimationActive={false}
          />
          <Area
            yAxisId="tok"
            type="monotone"
            dataKey="tokens"
            stroke="#737373"
            strokeWidth={1.5}
            fill="url(#gradTok)"
            dot={false}
            activeDot={{ r: 3, fill: '#a3a3a3', stroke: '#000', strokeWidth: 1.5 }}
            isAnimationActive={false}
          />
          <Area
            yAxisId="req"
            type="monotone"
            dataKey="requests"
            stroke="#e5e5e5"
            strokeWidth={1.75}
            fill="url(#gradReq)"
            dot={false}
            activeDot={{ r: 3, fill: '#fafafa', stroke: '#000', strokeWidth: 1.5 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
      {empty && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span className="text-[11px] text-neutral-600">No traffic in the last hour</span>
        </div>
      )}
    </div>
  )
}

function QuotaOverview() {
  const { data: pool } = usePoolStatus()
  const accounts = [...(pool?.accounts ?? [])].sort(
    (a, b) => (b.quota_used ?? 0) - (a.quota_used ?? 0),
  )

  if (!accounts.length) {
    return (
      <p className="text-[12px] text-neutral-600 py-6 text-center">No accounts in the pool.</p>
    )
  }

  return (
    <div className="space-y-4">
      {accounts.map((acc) => {
        const total = acc.quota_total ?? 0
        const used = acc.quota_used ?? (total && acc.quota_remaining != null ? total - acc.quota_remaining : 0)
        const remaining = acc.quota_remaining ?? (total - used)
        const pct = total > 0 ? Math.min(used / total, 1) : 0
        const exhausted = acc.is_quota_exceeded || (total > 0 && remaining <= 0)

        return (
          <div key={acc.id} className="space-y-1.5">
            <div className="flex items-center justify-between text-xs gap-2">
              <span className="flex items-center gap-2 text-neutral-300 font-medium min-w-0">
                <span className="truncate">{acc.name}</span>
                {acc.plan_name && <span className="chip chip-muted shrink-0">{acc.plan_name}</span>}
              </span>
              <span className="text-neutral-500 tabular-nums shrink-0">
                {total > 0 ? (
                  <>
                    <span className="text-neutral-200 font-medium">{Math.round(used)}</span> used
                    <span className="mx-1.5 text-neutral-700">·</span>
                    <span className={exhausted ? 'text-white font-semibold' : ''}>{Math.round(remaining)} left</span>
                  </>
                ) : (
                  'quota not fetched'
                )}
              </span>
            </div>
            <div className="h-[5px] rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
              <div
                className="h-full rounded-full transition-[width] duration-700 ease-out"
                style={{ width: `${pct * 100}%`, background: exhausted ? '#525252' : '#e5e5e5' }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function Dashboard() {
  const { data: stats, isLoading, error } = useDashboardStats()
  const { data: pool } = usePoolStatus()
  const { data: activity } = useActivityStats()

  const withQuota = (pool?.accounts ?? []).filter((a) => a.quota_total != null && a.quota_total > 0)
  const creditsTotal = withQuota.reduce((s, a) => s + (a.quota_total ?? 0), 0)
  const creditsLeft = withQuota.reduce((s, a) => s + (a.quota_remaining ?? 0), 0)
  const creditsPct = creditsTotal > 0 ? Math.min(creditsLeft / creditsTotal, 1) : 0

  const series = activity?.series ?? []
  const windowReq = activity?.window.requests ?? 0
  const windowCr = activity?.window.credits ?? 0

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-6">
      <motion.div variants={rise} className="flex items-end justify-between">
        <div>
          <h1 className="text-[24px] font-bold text-white tracking-tight">Dashboard</h1>
          <p className="text-sm text-neutral-500 mt-1">Credits, failures, traffic</p>
        </div>
        <HeaderBadge pulse>Live</HeaderBadge>
      </motion.div>

      {isLoading ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-[96px]" />)}
        </div>
      ) : error ? (
        <Card className="p-6 text-center text-neutral-400 text-sm">{error.message}</Card>
      ) : stats ? (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <motion.div variants={rise}>
              <Card className="p-5 h-full">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-neutral-500">
                    Credits left
                  </span>
                  <Wallet size={13} className="text-neutral-600" />
                </div>
                <div className="text-[28px] leading-none font-bold text-white tabular-nums tracking-tight">
                  {Math.round(creditsLeft).toLocaleString()}
                </div>
                <div className="mt-1.5 text-[11px] text-neutral-500">
                  {creditsTotal > 0
                    ? `of ${Math.round(creditsTotal).toLocaleString()}`
                    : 'quota not fetched'}
                </div>
                {creditsTotal > 0 && (
                  <div className="mt-3 h-[4px] rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.07)' }}>
                    <div
                      className="h-full rounded-full bg-neutral-200"
                      style={{ width: `${creditsPct * 100}%` }}
                    />
                  </div>
                )}
              </Card>
            </motion.div>

            <motion.div variants={rise}>
              <Card className="p-5 h-full">
                <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-neutral-500 mb-2">
                  Pool
                </div>
                <div className="text-[28px] leading-none font-bold text-white tabular-nums tracking-tight">
                  {stats.available_now ?? 0}
                  <span className="text-[15px] font-medium text-neutral-500">
                    {' / '}{stats.total_accounts ?? 0}
                  </span>
                </div>
                <div className="mt-1.5 text-[11px] text-neutral-500">
                  {(stats.accounts_in_cooldown ?? 0) === 0
                    && (stats.accounts_exhausted ?? 0) === 0
                    && (stats.available_now ?? 0) === (stats.total_accounts ?? 0) ? (
                    'all available'
                  ) : (
                    <>
                      <span className="text-neutral-300">{stats.available_now ?? 0}</span> available
                      {(stats.accounts_in_cooldown ?? 0) > 0 && (
                        <>
                          <span className="mx-1.5 text-neutral-700">·</span>
                          <span className="text-neutral-300">{stats.accounts_in_cooldown}</span> cooldown
                        </>
                      )}
                      {(stats.accounts_exhausted ?? 0) > 0 && (
                        <>
                          <span className="mx-1.5 text-neutral-700">·</span>
                          <span className="text-neutral-300">{stats.accounts_exhausted}</span> exhausted
                        </>
                      )}
                    </>
                  )}
                </div>
              </Card>
            </motion.div>

            <motion.div variants={rise}>
              <Card className="p-5 h-full">
                <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-neutral-500 mb-2">
                  Last hour
                </div>
                <div className="text-[28px] leading-none font-bold text-white tabular-nums tracking-tight">
                  {windowReq.toLocaleString()}
                  <span className="text-[13px] font-medium text-neutral-500 ml-2">req</span>
                </div>
                <div className="mt-1.5 text-[11px] text-neutral-500 tabular-nums">
                  {windowCr.toLocaleString()} credits
                </div>
              </Card>
            </motion.div>
          </div>

          <motion.div variants={rise}>
            <Card className="p-5">
              <SectionTitle
                icon={<Activity size={13} className="text-neutral-400" />}
                right={
                  <span className="flex items-center gap-4 text-[10px] text-neutral-500">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-[2px] bg-neutral-200" />
                      requests
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-[2px] bg-neutral-500" />
                      tokens
                    </span>
                    <span className="text-neutral-700 font-mono">60 min</span>
                  </span>
                }
              >
                Traffic
              </SectionTitle>
              {series.length > 0 ? (
                <TrafficChart series={series} />
              ) : (
                <div className="h-[220px] flex items-center justify-center text-xs text-neutral-500">
                  No traffic in the last hour
                </div>
              )}
            </Card>
          </motion.div>

          <div className="grid lg:grid-cols-2 gap-4">
            <motion.div variants={rise}>
              <Card className="p-5 h-full">
                <SectionTitle icon={<CircleAlert size={13} className="text-neutral-400" />}>
                  Recent errors
                </SectionTitle>
                {stats.recent_errors.length > 0 ? (
                  <div className="space-y-2 max-h-[280px] overflow-y-auto pr-1">
                    {stats.recent_errors.slice(0, 12).map((err, i) => (
                      <div
                        key={`${err.account_id}-${i}`}
                        className="flex items-start gap-3 px-3 py-2.5 rounded-lg"
                        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-medium text-neutral-200 truncate">{err.account_name}</span>
                            <span className="text-[10px] text-neutral-600 shrink-0">{timeAgo(err.at)}</span>
                          </div>
                          <p className="text-[11px] text-neutral-500 mt-0.5 line-clamp-2 font-mono">{err.message}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-10 text-center">
                    <CheckCircle2 size={18} className="text-neutral-500 mb-2" />
                    <p className="text-sm text-neutral-400">No sticky errors</p>
                  </div>
                )}
              </Card>
            </motion.div>

            <motion.div variants={rise}>
              <Card className="p-5 h-full">
                <SectionTitle icon={<Wallet size={13} className="text-neutral-400" />}>
                  Quota by account
                </SectionTitle>
                <QuotaOverview />
              </Card>
            </motion.div>
          </div>
        </>
      ) : null}
    </motion.div>
  )
}
