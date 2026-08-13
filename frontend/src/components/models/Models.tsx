import { motion } from 'framer-motion'
import { BrainCircuit, Coins, Eye, Layers3 } from 'lucide-react'
import { Card, EmptyState, HeaderBadge, Skeleton } from '../ui/GlassPanel'
import { useModelCatalog } from '../../hooks/useApi'
import { formatNumber } from '../../lib/utils'
import type { ModelCatalogEntry } from '../../types'

const stagger = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.035 } },
}
const rise = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.3, ease: [0.22, 1, 0.36, 1] } },
}

function factorLabel(value: number) {
  if (value === 0) return '0× · free'
  return `${value.toFixed(value % 1 === 0 ? 0 : 1)}×`
}

function contextLabel(model: ModelCatalogEntry) {
  const max = model.context_windows.length
    ? Math.max(...model.context_windows)
    : model.max_input_tokens
  return max >= 1_000_000 ? '1M context' : `${formatNumber(max)} context`
}

function ModelRow({ model }: { model: ModelCatalogEntry }) {
  return (
    <motion.div
      variants={rise}
      className="grid grid-cols-[minmax(0,1fr)_auto] md:grid-cols-[minmax(190px,1.1fr)_minmax(180px,1fr)_minmax(220px,1fr)_100px] items-center gap-x-5 gap-y-2 px-5 py-4"
      style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}
    >
      <div className="min-w-0">
        <div className="text-[14px] font-semibold text-neutral-100 truncate">{model.name}</div>
        <div className="md:hidden text-[11px] font-mono text-neutral-600 mt-0.5 truncate">{model.key}</div>
      </div>

      <div className="hidden md:block min-w-0 font-mono text-[12px] text-neutral-400 truncate">
        {model.key}
      </div>

      <div className="hidden md:flex items-center gap-2 flex-wrap">
        <span className="chip chip-muted">{model.kind === 'tier' ? 'Tier' : 'Model'}</span>
        {model.is_reasoning && (
          <span className="chip chip-muted"><BrainCircuit size={10} /> Reasoning</span>
        )}
        {!model.is_reasoning && model.supports_thinking && (
          <span className="chip chip-muted"><BrainCircuit size={10} /> Thinking</span>
        )}
        {model.is_vision && (
          <span className="chip chip-muted"><Eye size={10} /> Image input</span>
        )}
        <span className="text-[10px] text-neutral-600">{contextLabel(model)}</span>
      </div>

      <div className="justify-self-end">
        <span
          className="inline-flex min-w-[74px] justify-center rounded-lg px-2.5 py-1.5 font-mono text-[12px] font-semibold tabular-nums text-neutral-100"
          style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)' }}
        >
          {factorLabel(model.credit_factor)}
        </span>
      </div>
    </motion.div>
  )
}

export function Models() {
  const { data, isLoading, isError } = useModelCatalog()

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-6">
      <motion.div variants={rise} className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-[24px] font-bold text-white tracking-tight">Models</h1>
          <p className="text-sm text-neutral-500 mt-1">Qoder model keys, route capabilities and base credit multipliers</p>
        </div>
        <HeaderBadge icon={<Layers3 size={11} />}>{data?.length ?? 0} models</HeaderBadge>
      </motion.div>

      {isLoading ? (
        <Card className="p-5 space-y-3">
          {[1, 2, 3, 4, 5, 6].map((row) => <Skeleton key={row} className="h-12" />)}
        </Card>
      ) : isError || !data ? (
        <Card>
          <EmptyState icon={<Coins size={20} />} title="Catalog unavailable" hint="The router could not load the local model catalog." />
        </Card>
      ) : (
        <motion.div variants={rise}>
          <Card className="overflow-hidden">
            <div className="hidden md:grid grid-cols-[minmax(190px,1.1fr)_minmax(180px,1fr)_minmax(220px,1fr)_100px] gap-5 px-5 py-3 text-[10px] font-semibold uppercase tracking-[0.1em] text-neutral-600">
              <span>Name</span>
              <span>Key</span>
              <span>Capabilities</span>
              <span className="text-right">Credits</span>
            </div>
            {data.map((model) => <ModelRow key={model.key} model={model} />)}
          </Card>
          <p className="mt-3 px-1 text-[11px] leading-relaxed text-neutral-600">
            Credit values are base multipliers from Qoder's catalog. Promotions and active free-call rewards can make the actual charge lower or zero.
            {' '}Reasoning is the catalog model type; Thinking marks optional thinking support on otherwise non-reasoning models such as Kimi-K3.
            {' '}Image input means that the Qoder route accepts images, regardless of how the upstream model processes them internally.
          </p>
        </motion.div>
      )}
    </motion.div>
  )
}
