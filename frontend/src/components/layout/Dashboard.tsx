import { useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { useDashboardStats, usePoolStatus, useActivityStats } from '../../hooks/useApi'
import { useCountUp } from '../../hooks/useCountUp'
import { Card, SectionTitle, Skeleton, HeaderBadge } from '../ui/GlassPanel'
import { timeAgo, formatNumber } from '../../lib/utils'
import { Users, Zap, Activity, Database, CircleAlert, Gauge, CheckCircle2, Wallet, BarChart3 } from 'lucide-react'
import {
  AreaChart, Area, CartesianGrid, XAxis, YAxis, ResponsiveContainer,
} from 'recharts'
import type { ActivityPoint, ModelUsage } from '../../types'

const stagger = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.06 } },
}
const rise = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] } },
}

const fmtTime = (t: number) =>
  new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })



/* ── KPI card with an optional sub-line and footer visualization ── */
function StatCard({
  label,
  value,
  icon,
  sub,
  children,
}: {
  label: string
  value: number
  icon: React.ReactNode
  sub?: React.ReactNode
  children?: React.ReactNode
}) {
  const animated = useCountUp(value, 900)
  const display = Math.round(animated).toLocaleString()

  return (
    <motion.div variants={rise}>
      <Card className="p-5 h-full">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-neutral-500">{label}</span>
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center"
            style={{ background: 'rgba(255,255,255,0.06)', color: '#d4d4d4', border: '1px solid rgba(255,255,255,0.08)' }}
          >
            {icon}
          </div>
        </div>
        <div className="text-[30px] leading-none font-bold text-white tabular-nums tracking-tight">
          {display}
        </div>
        {sub && <div className="mt-2 text-[11px] text-neutral-500">{sub}</div>}
        {children}
      </Card>
    </motion.div>
  )
}

/* ── Credits card: big number + wide remaining bar with % at the tip ── */
function CreditsCard({ left, total }: { left: number; total: number }) {
  const animatedLeft = useCountUp(left, 900)
  const pct = total > 0 ? Math.min(left / total, 1) : 0

  return (
    <motion.div variants={rise}>
      <Card className="p-5 h-full">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-neutral-500">Credits Left</span>
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center"
            style={{ background: 'rgba(255,255,255,0.06)', color: '#d4d4d4', border: '1px solid rgba(255,255,255,0.08)' }}
          >
            <Wallet size={14} />
          </div>
        </div>
        <div className="text-[30px] leading-none font-bold text-white tabular-nums tracking-tight">
          {Math.round(animatedLeft).toLocaleString()}
        </div>
        <div className="mt-2 text-[11px] text-neutral-500">
          {total > 0 ? `of ${Math.round(total).toLocaleString()} credits` : 'quota not fetched'}
        </div>
        {total > 0 && (
          <div className="mt-3.5 flex items-center gap-2.5">
            <div className="h-[7px] flex-1 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.07)' }}>
              <motion.div
                className="h-full rounded-full"
                style={{ background: '#e5e5e5' }}
                initial={{ width: 0 }}
                animate={{ width: `${pct * 100}%` }}
                transition={{ duration: 0.9, ease: 'easeOut' }}
              />
            </div>
            <span className="text-[11px] font-semibold text-neutral-300 tabular-nums shrink-0">
              {Math.round(pct * 100)}%
            </span>
          </div>
        )}
      </Card>
    </motion.div>
  )
}

/* ── Usage by model: smooth animated rows, same language as quota bars ── */
function ModelUsageList({ data }: { data: ModelUsage[] }) {
  if (!data.length) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-center">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center mb-3"
          style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}
        >
          <BarChart3 size={19} className="text-neutral-400" />
        </div>
        <p className="text-sm font-medium text-neutral-300">No model traffic yet</p>
        <p className="text-[11px] text-neutral-600 mt-1">Requests from the last hour will appear here</p>
      </div>
    )
  }

  const max = Math.max(...data.map((m) => m.requests), 1)

  return (
    <div className="space-y-4 pt-1">
      {data.map((m, i) => (
        <motion.div
          key={m.model}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.06 }}
          className="space-y-1.5"
        >
          <div className="flex items-center justify-between text-xs">
            <span className="text-neutral-300 font-medium">{m.display}</span>
            <span className="text-neutral-500 tabular-nums">
              <span className="text-neutral-200 font-medium">{m.requests}</span> req
              <span className="mx-1.5 text-neutral-700">·</span>
              {formatNumber(m.tokens)} tok
              <span className="mx-1.5 text-neutral-700">·</span>
              {m.credits.toLocaleString()} cr
            </span>
          </div>
          <div className="h-[5px] rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
            <motion.div
              className="h-full rounded-full"
              style={{ background: '#e5e5e5' }}
              initial={{ width: 0 }}
              animate={{ width: `${(m.requests / max) * 100}%` }}
              transition={{ duration: 0.7, ease: 'easeOut', delay: 0.1 + i * 0.06 }}
            />
          </div>
        </motion.div>
      ))}
    </div>
  )
}

/* ── Traffic area chart (requests + tokens, last 60 min) ──
   Custom hover layer driven by native mouse events: line + tooltip track
   the cursor 1:1 (no snapping, no transition lag). Plot insets below must
   match the chart margins + axis widths. */
const PLOT_LEFT = 6 + 26   // margin.left + left YAxis width
const PLOT_RIGHT = 6 + 36  // margin.right + right YAxis width
const PLOT_TOP = 12        // margin.top
const CHART_H = 240
const PLOT_BOTTOM = CHART_H - 26  // XAxis height

function TrafficChart({ series, empty }: { series: ActivityPoint[]; empty: boolean }) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const lineRef = useRef<HTMLDivElement>(null)
  const tipRef = useRef<HTMLDivElement>(null)
  const dotReqRef = useRef<HTMLDivElement>(null)
  const dotTokRef = useRef<HTMLDivElement>(null)
  const [activeIdx, setActiveIdx] = useState<number | null>(null)

  // mirror the YAxis domain functions below so dot y-positions match the curves
  const maxReq = series.reduce((m, p) => Math.max(m, p.requests), 0)
  const maxTok = series.reduce((m, p) => Math.max(m, p.tokens), 0)
  const reqMax = Math.max(Math.ceil(maxReq * 1.2), 2)
  const tokMax = Math.max(Math.ceil(maxTok * 1.15), 1)

  const setHoverVisible = (v: boolean) => {
    if (lineRef.current) lineRef.current.style.opacity = v ? '1' : '0'
    if (tipRef.current) tipRef.current.style.opacity = v ? '1' : '0'
    if (dotReqRef.current) dotReqRef.current.style.opacity = v ? '1' : '0'
    if (dotTokRef.current) dotTokRef.current.style.opacity = v ? '1' : '0'
  }

  const onMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const wrap = wrapRef.current
    if (!wrap || series.length < 2) return
    const rect = wrap.getBoundingClientRect()
    const x = e.clientX - rect.left
    const left = PLOT_LEFT
    const right = rect.width - PLOT_RIGHT
    if (x < left - 4 || x > right + 4) {
      setHoverVisible(false)
      setActiveIdx(null)
      return
    }
    const cx = Math.min(Math.max(x, left), right)
    const i = Math.round(((cx - left) / Math.max(right - left, 1)) * (series.length - 1))
    // snap to the data point's x — the indicator stays anchored to points,
    // the CSS transition on transform makes the hop between them glide
    const px = left + (i / (series.length - 1)) * (right - left)

    if (lineRef.current) {
      lineRef.current.style.transform = `translateX(${px}px)`
    }
    const plotH = PLOT_BOTTOM - PLOT_TOP
    if (dotReqRef.current) {
      const y = PLOT_TOP + plotH * (1 - series[i].requests / reqMax)
      dotReqRef.current.style.transform = `translate(${px}px, ${y}px) translate(-50%, -50%)`
    }
    if (dotTokRef.current) {
      const y = PLOT_TOP + plotH * (1 - series[i].tokens / tokMax)
      dotTokRef.current.style.transform = `translate(${px}px, ${y}px) translate(-50%, -50%)`
    }
    if (tipRef.current) {
      const tipW = 150
      const lx = px + 14 + tipW > rect.width ? px - 14 - tipW : px + 14
      tipRef.current.style.transform = `translate(${Math.round(lx)}px, 8px)`
    }
    setHoverVisible(true)
    setActiveIdx((prev) => (prev === i ? prev : i))
  }

  const onMouseLeave = () => {
    setHoverVisible(false)
    setActiveIdx(null)
  }

  const pt = activeIdx != null && activeIdx >= 0 && activeIdx < series.length ? series[activeIdx] : null

  return (
    <div ref={wrapRef} className="relative h-[240px]" onMouseMove={onMouseMove} onMouseLeave={onMouseLeave}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={series}
          margin={{ top: 12, right: 6, bottom: 0, left: 6 }}
        >
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
            width={26}
          />
          <YAxis
            yAxisId="tok"
            orientation="right"
            domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.15)]}
            tickFormatter={(v: number) => formatNumber(v)}
            tick={{ fill: '#525252', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={36}
          />
          {/* tokens behind, requests in front — fills don't mud each other */}
          <Area
            yAxisId="tok"
            type="monotone"
            dataKey="tokens"
            name="tokens"
            stroke="#737373"
            strokeWidth={1.5}
            fill="url(#gradTok)"
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
          <Area
            yAxisId="req"
            type="monotone"
            dataKey="requests"
            name="requests"
            stroke="#e5e5e5"
            strokeWidth={1.75}
            fill="url(#gradReq)"
            dot={false}
            activeDot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>

      {/* cursor line — anchored to points, glides between them */}
      <div
        ref={lineRef}
        className="absolute top-[8px] bottom-[26px] w-px pointer-events-none"
        style={{
          background: 'rgba(255,255,255,0.22)',
          opacity: 0,
          transition: 'transform 90ms ease-out, opacity 120ms',
        }}
      />

      {/* point markers on the curves */}
      <div
        ref={dotTokRef}
        className="absolute top-0 left-0 w-[7px] h-[7px] rounded-full pointer-events-none"
        style={{
          background: '#a3a3a3',
          border: '1.5px solid #000',
          opacity: 0,
          transition: 'transform 90ms ease-out, opacity 120ms',
        }}
      />
      <div
        ref={dotReqRef}
        className="absolute top-0 left-0 w-[7px] h-[7px] rounded-full pointer-events-none"
        style={{
          background: '#fafafa',
          border: '1.5px solid #000',
          opacity: 0,
          transition: 'transform 90ms ease-out, opacity 120ms',
        }}
      />

      {/* tooltip — anchored to points, glides between them */}
      <div
        ref={tipRef}
        className="absolute top-0 left-0 w-[150px] pointer-events-none rounded-lg px-3 py-2.5 text-[11px] font-mono"
        style={{
          background: '#0a0a0a',
          border: '1px solid rgba(255,255,255,0.14)',
          boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
          opacity: 0,
          transition: 'transform 90ms ease-out, opacity 120ms',
        }}
      >
        {pt && (
          <>
            <div className="text-[10px] text-neutral-600 uppercase tracking-wider mb-1.5">{fmtTime(pt.t)}</div>
            <div className="space-y-1">
              <div className="flex items-center">
                <span className="w-2 h-2 rounded-[2px] shrink-0" style={{ background: '#e5e5e5' }} />
                <span className="text-neutral-500 ml-2">requests</span>
                <span className="ml-auto text-white font-semibold tabular-nums">{pt.requests.toLocaleString()}</span>
              </div>
              <div className="flex items-center">
                <span className="w-2 h-2 rounded-[2px] shrink-0" style={{ background: '#737373' }} />
                <span className="text-neutral-500 ml-2">tokens</span>
                <span className="ml-auto text-white font-semibold tabular-nums">{pt.tokens.toLocaleString()}</span>
              </div>
            </div>
          </>
        )}
      </div>

      {empty && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span className="text-[11px] text-neutral-600">No traffic in the last hour</span>
        </div>
      )}
    </div>
  )
}



/* ── Donut (monochrome) ── */
function PoolDonut({ available, error, inactive }: { available: number; error: number; inactive: number }) {
  const total = Math.max(available + error + inactive, 1)
  const radius = 56
  const circumference = 2 * Math.PI * radius

  const segments = [
    { value: available, color: '#fafafa', label: 'Available' },
    { value: error, color: '#737373', label: 'Error' },
    { value: inactive, color: '#2e2e2e', label: 'Inactive' },
  ].filter((s) => s.value > 0)

  let offset = 0
  const pct = Math.round((available / total) * 100)

  return (
    <div className="flex items-center gap-8">
      <div className="relative shrink-0">
        <svg width="148" height="148" viewBox="0 0 148 148" className="-rotate-90">
          <circle cx="74" cy="74" r={radius} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="10" />
          {segments.map((seg, i) => {
            const len = (seg.value / total) * circumference
            const dash = `${len} ${circumference - len}`
            const currentOffset = -offset
            offset += len
            return (
              <motion.circle
                key={i}
                cx="74"
                cy="74"
                r={radius}
                fill="none"
                stroke={seg.color}
                strokeWidth="10"
                strokeLinecap="round"
                strokeDasharray={dash}
                initial={{ strokeDashoffset: currentOffset - circumference }}
                animate={{ strokeDashoffset: currentOffset }}
                transition={{ duration: 0.9, ease: 'easeOut', delay: 0.15 + i * 0.1 }}
              />
            )
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <motion.span
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.45, duration: 0.35 }}
            className="text-xl font-semibold text-white tabular-nums"
          >
            {pct}%
          </motion.span>
          <span className="text-[9px] font-medium text-neutral-500 uppercase tracking-wider">available</span>
        </div>
      </div>

      <div className="space-y-3">
        {[
          { label: 'Available', value: available, swatch: '#fafafa' },
          { label: 'Error', value: error, swatch: '#737373' },
          { label: 'Inactive', value: inactive, swatch: '#2e2e2e' },
        ].map((row, i) => (
          <motion.div
            key={row.label}
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.35 + i * 0.07 }}
            className="flex items-center gap-2.5"
          >
            <span
              className="w-2.5 h-2.5 rounded-[3px]"
              style={{ backgroundColor: row.swatch, border: '1px solid rgba(255,255,255,0.12)' }}
            />
            <span className="text-xs text-neutral-400 w-20">{row.label}</span>
            <span className="text-sm font-semibold text-white tabular-nums">{row.value}</span>
          </motion.div>
        ))}
      </div>
    </div>
  )
}

/* ── Per-account quota overview ── */
function QuotaOverview() {
  const { data: pool } = usePoolStatus()
  const accounts = [...(pool?.accounts ?? [])].sort((a, b) => (b.quota_used ?? 0) - (a.quota_used ?? 0))

  if (!accounts.length) return null

  return (
    <div className="space-y-4">
      {accounts.map((acc, i) => {
        const total = acc.quota_total ?? 0
        const used = acc.quota_used ?? (total && acc.quota_remaining != null ? total - acc.quota_remaining : 0)
        const remaining = acc.quota_remaining ?? (total - used)
        const pct = total > 0 ? Math.min(used / total, 1) : 0
        const exhausted = acc.is_quota_exceeded || (total > 0 && remaining <= 0)

        return (
          <motion.div
            key={acc.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 + i * 0.05 }}
            className="space-y-1.5"
          >
            <div className="flex items-center justify-between text-xs">
              <span className="flex items-center gap-2 text-neutral-300 font-medium">
                {acc.name}
                {acc.plan_name && <span className="chip chip-muted">{acc.plan_name}</span>}
              </span>
              <span className="text-neutral-500 tabular-nums">
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
          </motion.div>
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

  const series = activity?.series ?? []

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-8">
      {/* Header */}
      <motion.div variants={rise} className="flex items-end justify-between">
        <div>
          <h1 className="text-[24px] font-bold text-white tracking-tight">Dashboard</h1>
          <p className="text-sm text-neutral-500 mt-1">Real-time account pool telemetry</p>
        </div>
        <HeaderBadge pulse>Live</HeaderBadge>
      </motion.div>

      {isLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-[100px]" />)}
        </div>
      ) : error ? (
        <Card className="p-6 text-center text-neutral-400 text-sm">{error.message}</Card>
      ) : stats ? (
        <>
          {/* KPI cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              label="Accounts"
              value={stats.total_accounts}
              icon={<Users size={14} />}
              sub={
                stats.accounts_in_cooldown === 0 && stats.available_now === stats.total_accounts ? (
                  'all available'
                ) : (
                  <>
                    <span className="text-neutral-300">{stats.available_now}</span> available
                    <span className="mx-1.5 text-neutral-700">·</span>
                    <span className={stats.accounts_in_cooldown > 0 ? 'text-neutral-200' : ''}>{stats.accounts_in_cooldown}</span> error
                  </>
                )
              }
            />

            <StatCard
              label="Requests"
              value={stats.total_requests}
              icon={<Activity size={14} />}
            />

            <StatCard
              label="Tokens"
              value={stats.total_tokens}
              icon={<Database size={14} />}
            />

            <CreditsCard left={Math.round(creditsLeft)} total={Math.round(creditsTotal)} />
          </div>

          {/* Traffic + usage by model */}
          <div className="grid lg:grid-cols-5 gap-4">
            <motion.div variants={rise} className="lg:col-span-3">
              <Card className="p-5 h-full">
                <SectionTitle
                  icon={<Activity size={13} className="text-neutral-400" />}
                  right={
                    <span className="flex items-center gap-4 text-[10px] text-neutral-500">
                      <span className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-[2px]" style={{ background: '#fafafa' }} />
                        requests
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-[2px]" style={{ background: '#737373' }} />
                        tokens
                      </span>
                      <span className="text-neutral-700 font-mono">60 min</span>
                    </span>
                  }
                >
                  Traffic
                </SectionTitle>
                {!activity?.window.requests ? (
                  <div className="h-[260px] flex items-center justify-center text-xs text-neutral-500">
                    No traffic in the last hour
                  </div>
                ) : (
                  <TrafficChart series={series} empty={false} />
                )}
              </Card>
            </motion.div>

            <motion.div variants={rise} className="lg:col-span-2">
              <Card className="p-5 h-full">
                <SectionTitle
                  icon={<BarChart3 size={13} className="text-neutral-400" />}
                  right={<span className="text-[10px] text-neutral-700 font-mono">60 min</span>}
                >
                  Usage by Model
                </SectionTitle>
                <ModelUsageList data={activity?.by_model ?? []} />
              </Card>
            </motion.div>
          </div>

          {/* Health + errors */}
          <div className="grid lg:grid-cols-5 gap-4">
            <motion.div variants={rise} className="lg:col-span-2">
              <Card className="p-5 h-full">
                <SectionTitle icon={<Gauge size={13} className="text-neutral-400" />}>Pool Health</SectionTitle>
                <PoolDonut
                  available={stats.available_now ?? 0}
                  error={stats.accounts_in_cooldown ?? 0}
                  inactive={Math.max((stats.total_accounts ?? 0) - (stats.available_now ?? 0) - (stats.accounts_in_cooldown ?? 0), 0)}
                />
              </Card>
            </motion.div>

            <motion.div variants={rise} className="lg:col-span-3">
              <Card className="p-5 h-full">
                <SectionTitle icon={<CircleAlert size={13} className="text-neutral-400" />}>Recent Errors</SectionTitle>
                {stats.recent_errors.length > 0 ? (
                  <div className="space-y-2 max-h-[180px] overflow-y-auto pr-1">
                    {stats.recent_errors.slice(0, 8).map((err, i) => (
                      <motion.div
                        key={i}
                        initial={{ opacity: 0, x: -8 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.04 }}
                        className="flex items-start gap-3 px-3 py-2.5 rounded-lg"
                        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-medium text-neutral-200 truncate">{err.account_name}</span>
                            <span className="text-[10px] text-neutral-600 shrink-0">{timeAgo(err.at)}</span>
                          </div>
                          <p className="text-[11px] text-neutral-500 mt-0.5 line-clamp-1 font-mono">{err.message}</p>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center py-8 text-center">
                    <div
                      className="w-11 h-11 rounded-xl flex items-center justify-center mb-3"
                      style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)' }}
                    >
                      <CheckCircle2 size={19} className="text-neutral-300" />
                    </div>
                    <p className="text-sm font-medium text-neutral-200">All systems operational</p>
                    <p className="text-[11px] text-neutral-600 mt-1">No errors in the current window</p>
                  </div>
                )}
              </Card>
            </motion.div>
          </div>

          {/* Quota overview */}
          <motion.div variants={rise}>
            <Card className="p-5">
              <SectionTitle icon={<Gauge size={13} className="text-neutral-400" />}>Quota Overview</SectionTitle>
              <QuotaOverview />
            </Card>
          </motion.div>
        </>
      ) : null}
    </motion.div>
  )
}
