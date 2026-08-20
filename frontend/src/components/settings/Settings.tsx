import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Activity, Check, ChevronDown, Network, TerminalSquare, Users } from 'lucide-react'
import { Card, SectionTitle, Switch, Skeleton, EmptyState } from '../ui/GlassPanel'
import { useModelCatalog, useSettings, useUpdateSettings } from '../../hooks/useApi'
import { WORKER_ENABLED } from '../../lib/features'
import type { AppSettings, ModelCatalogEntry, QoderInferBase } from '../../types'

const QODER_ROUTES: { value: QoderInferBase; label: string }[] = [
  { value: 'api1', label: 'api1.qoder.sh' },
  { value: 'api2', label: 'api2.qoder.sh' },
  { value: 'api3', label: 'api3.qoder.sh' },
]

const PROBE_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: 'Off' },
  { value: 5, label: 'Every 5 min' },
  { value: 10, label: 'Every 10 min' },
  { value: 15, label: 'Every 15 min' },
  { value: 20, label: 'Every 20 min' },
  { value: 25, label: 'Every 25 min' },
  { value: 30, label: 'Every 30 min' },
  { value: 60, label: 'Every 1 hour' },
]

type SelectOption<T extends string | number> = { value: T; label: string }

/* ── Monochrome custom dropdown (native <select> can't be themed) ── */
function Select<T extends string | number>({ value, options, onChange }: {
  value: T
  options: SelectOption<T>[]
  onChange: (v: T) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [])

  const current = options.find((r) => r.value === value)

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="w-full flex items-center justify-between rounded-lg px-3.5 py-2.5 text-sm transition-all duration-150 focus:outline-none"
        style={{
          background: '#0a0a0a',
          color: '#ededed',
          border: `1px solid ${open ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.1)'}`,
          // alpha-only shadow — interpolates smoothly, no flash on toggle
          boxShadow: `0 0 0 3px rgba(255,255,255,${open ? 0.05 : 0})`,
        }}
      >
        <span className="font-mono text-[13px]">{current?.label ?? value}</span>
        <ChevronDown
          size={14}
          className={`text-neutral-500 transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.ul
            role="listbox"
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.12, ease: 'easeOut' }}
            className="absolute z-20 mt-2 w-full overflow-hidden rounded-lg py-1"
            style={{
              background: '#0a0a0a',
              border: '1px solid rgba(255,255,255,0.1)',
              boxShadow: '0 16px 40px -8px rgba(0,0,0,0.8)',
            }}
          >
            {options.map((route) => {
              const selected = route.value === value
              return (
                <li key={route.value}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    onClick={() => {
                      onChange(route.value)
                      setOpen(false)
                    }}
                    className={`w-full flex items-center justify-between px-3.5 py-2 text-left font-mono text-[13px] transition-colors duration-100 hover:bg-white/5 ${
                      selected ? 'text-white' : 'text-neutral-400'
                    }`}
                  >
                    {route.label}
                    {selected && <Check size={13} className="text-neutral-500" />}
                  </button>
                </li>
              )
            })}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  )
}

function factorLabel(value: number) {
  if (value === 0) return 'free'
  return `${value.toFixed(value % 1 === 0 ? 0 : 1)}×`
}

/* ── Checklist dropdown used by Models Probe ── */
function ModelMultiSelect({ values, models, onChange }: {
  values: string[]
  models: ModelCatalogEntry[]
  onChange: (values: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const selected = new Set(values)

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [])

  const toggle = (key: string) => {
    const next = new Set(values)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    onChange(models.filter((model) => next.has(model.key)).map((model) => model.key))
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="w-full flex items-center justify-between rounded-lg px-3.5 py-2.5 text-sm transition-all duration-150 focus:outline-none"
        style={{
          background: '#0a0a0a',
          color: '#ededed',
          border: `1px solid ${open ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.1)'}`,
          boxShadow: `0 0 0 3px rgba(255,255,255,${open ? 0.05 : 0})`,
        }}
      >
        <span className="font-mono text-[13px]">
          {values.length === 0 ? 'No models selected' : `${values.length} of ${models.length} models`}
        </span>
        <ChevronDown size={14} className={`text-neutral-500 transition-transform duration-150 ${open ? 'rotate-180' : ''}`} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.12, ease: 'easeOut' }}
            className="absolute z-30 mt-2 w-full overflow-hidden rounded-lg"
            style={{
              background: '#0a0a0a',
              border: '1px solid rgba(255,255,255,0.1)',
              boxShadow: '0 16px 40px -8px rgba(0,0,0,0.8)',
            }}
          >
            <div className="flex items-center justify-between px-3.5 py-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.07)' }}>
              <span className="text-[10px] uppercase tracking-[0.1em] text-neutral-600">Models to probe</span>
              <div className="flex items-center gap-3 text-[11px]">
                <button type="button" onClick={() => onChange(models.map((model) => model.key))} className="text-neutral-400 hover:text-white transition-colors">All</button>
                <button type="button" onClick={() => onChange([])} className="text-neutral-500 hover:text-white transition-colors">None</button>
              </div>
            </div>
            <ul role="listbox" aria-multiselectable="true" className="max-h-[360px] overflow-y-auto py-1">
              {models.map((model) => {
                const checked = selected.has(model.key)
                return (
                  <li key={model.key}>
                    <button
                      type="button"
                      role="option"
                      aria-selected={checked}
                      onClick={() => toggle(model.key)}
                      className="w-full flex items-center gap-3 px-3.5 py-2 text-left transition-colors duration-100 hover:bg-white/5"
                    >
                      <span
                        className={`w-4 h-4 rounded flex items-center justify-center shrink-0 ${checked ? 'bg-neutral-100 text-black' : 'text-transparent'}`}
                        style={!checked ? { border: '1px solid rgba(255,255,255,0.16)' } : undefined}
                      >
                        <Check size={11} strokeWidth={3} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className={`block text-[12px] truncate ${checked ? 'text-neutral-100' : 'text-neutral-400'}`}>{model.name}</span>
                        <span className="block font-mono text-[10px] text-neutral-600 truncate">{model.key}</span>
                      </span>
                      <span className="font-mono text-[10px] text-neutral-600 tabular-nums">{factorLabel(model.credit_factor)}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function SettingRow({ title, hint, checked, onChange }: {
  title: string
  hint: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <label className="flex items-center gap-3 cursor-pointer select-none">
      <Switch checked={checked} onChange={onChange} />
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-neutral-200">{title}</span>
        <span className="block text-[11px] text-neutral-500 mt-0.5">{hint}</span>
      </span>
    </label>
  )
}

export function Settings() {
  const { data, isLoading } = useSettings()
  const { data: models, isLoading: modelsLoading } = useModelCatalog()
  const update = useUpdateSettings()

  const set = (patch: Partial<AppSettings>) => update.mutate(patch)

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] } }}
      className="space-y-6"
    >
      {/* Header */}
      <div>
        <h1 className="text-[24px] font-bold text-white tracking-tight">Settings</h1>
        <p className="text-sm text-neutral-500 mt-1">Runtime preferences — applied immediately, persisted across restarts</p>
      </div>

      {/* Qoder upstream */}
      <Card className="p-5">
        <SectionTitle icon={<Network size={13} className="text-neutral-400" />}>Qoder upstream</SectionTitle>
        {isLoading ? (
          <Skeleton className="h-[70px]" />
        ) : (
          <div>
            <span className="label">Inference route</span>
            <Select
              value={data?.qoder_infer_base ?? 'api3'}
              options={QODER_ROUTES}
              onChange={(v) => set({ qoder_infer_base: v })}
            />
            <span className="block text-[11px] text-neutral-500 mt-2">
              Select the Qoder host used for new inference requests. Changes are applied and saved immediately.
            </span>
          </div>
        )}
      </Card>

      {/* Models probe */}
      <Card className="p-5">
        <SectionTitle icon={<Activity size={13} className="text-neutral-400" />}>Models Probe</SectionTitle>
        {isLoading || modelsLoading ? (
          <Skeleton className="h-[154px]" />
        ) : (
          <div className="space-y-4">
            <div>
              <span className="label">Probe interval</span>
              <Select
                value={data?.probe_interval_minutes ?? 15}
                options={PROBE_OPTIONS}
                onChange={(v) => set({ probe_interval_minutes: v })}
              />
              <span className="block text-[11px] text-neutral-500 mt-2">
                How often the router pings the selected models with a short "Hello!" to measure TPS and health.
              </span>
            </div>
            <div className="pt-1">
              <span className="label">Models</span>
              <ModelMultiSelect
                values={data?.probe_model_keys ?? []}
                models={models ?? []}
                onChange={(values) => set({ probe_model_keys: values })}
              />
              <span className="block text-[11px] text-neutral-500 mt-2">
                Applied on the next probe cycle. Cantus and tier routes are opt-in because every probe is a real credit-bearing request.
              </span>
            </div>
          </div>
        )}
      </Card>

      {/* Worker */}
      {WORKER_ENABLED && (
        <Card className="p-5">
          <SectionTitle icon={<TerminalSquare size={13} className="text-neutral-400" />}>Worker</SectionTitle>
          {isLoading ? (
            <Skeleton className="h-11" />
          ) : (
            <div className="space-y-4">
              <SettingRow
                title="Process logs"
                hint="Collect subprocess output and show it in the Worker tab log. Turn off to mute noisy output."
                checked={data?.worker_logs_enabled ?? true}
                onChange={(v) => set({ worker_logs_enabled: v })}
              />
              <SettingRow
                title="Retry allow"
                hint="Enable retry when trial activation fails — spawns new proxy + machine per attempt."
                checked={data?.worker_retry_allow ?? false}
                onChange={(v) => set({ worker_retry_allow: v })}
              />
              <SettingRow
                title="Use proxy"
                hint="Route worker traffic through the localhost:8080 proxy API (adds --proxy-use to shyla_qoder)."
                checked={data?.worker_proxy_use ?? false}
                onChange={(v) => set({ worker_proxy_use: v })}
              />
            </div>
          )}
        </Card>
      )}

      {/* Accounts */}
      <Card className="p-5">
        <SectionTitle icon={<Users size={13} className="text-neutral-400" />}>Accounts</SectionTitle>
        {isLoading ? (
          <Skeleton className="h-28" />
        ) : (
          <div className="space-y-4">
            <SettingRow
              title="Account email"
              hint="Show the account's email address under its name."
              checked={data?.accounts_show_email ?? true}
              onChange={(v) => set({ accounts_show_email: v })}
            />
            <SettingRow
              title="Token stats"
              hint="Show total tokens used on account cards."
              checked={data?.accounts_show_tokens ?? true}
              onChange={(v) => set({ accounts_show_tokens: v })}
            />
            <SettingRow
              title="Request stats"
              hint="Show total request count on account cards."
              checked={data?.accounts_show_requests ?? true}
              onChange={(v) => set({ accounts_show_requests: v })}
            />
            <div className="pt-2" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
              <SettingRow
                title="Auto-delete exhausted"
                hint="Delete exhausted accounts immediately instead of parking them. Turning this on also removes ALL currently exhausted accounts at once."
                checked={data?.accounts_auto_delete_exhausted ?? false}
                onChange={(v) => set({ accounts_auto_delete_exhausted: v })}
              />
            </div>
          </div>
        )}
      </Card>
    </motion.div>
  )
}
