import { motion, AnimatePresence } from 'framer-motion'
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { usePoolStatus, useAddAccount, useDeleteAccount, useUpdateAccount, useRefreshQuota, fetchAccountPat, useSettings, useAvailableAccounts, useExhaustedAccounts } from '../../hooks/useApi'
import { StatusBadge, Card, Modal, Skeleton, EmptyState } from '../ui/GlassPanel'
import { timeAgo, planEndInfo } from '../../lib/utils'
import { Plus, Trash2, Power, PowerOff, KeyRound, Activity, ArrowUpRight, RefreshCw, Crown, Copy, Check, Wallet, WalletMinimal, CalendarClock } from 'lucide-react'
import type { Account } from '../../types'

const stagger = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.05 } },
}
const rise = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.22, 1, 0.36, 1] } },
}

function getStatus(acc: Account): 'active' | 'error' | 'inactive' {
  if (!acc.is_active) return 'inactive'
  if (acc.is_quota_exceeded) return 'error'
  if (acc.consecutive_failures >= 3) return 'error'
  if (acc.last_error_message) return 'error'
  return 'active'
}

/* ── Plan expiry chip: end date + days left, color-coded by urgency ── */
function PlanEndChip({ epoch }: { epoch: number | null }) {
  const info = planEndInfo(epoch)
  if (!info) return null

  const expired = info.daysLeft <= 0
  const tone = expired
    ? 'text-red-400'
    : info.daysLeft <= 2
      ? 'text-red-400'
      : info.daysLeft <= 7
        ? 'text-amber-400'
        : 'text-neutral-500'

  return (
    <span className={`chip chip-muted ml-1 ${tone}`} title={`Plan ends ${info.label}`}>
      <CalendarClock size={9} />
      {expired ? `expired ${info.label}` : `${info.label} · ${info.daysLeft}d left`}
    </span>
  )
}

/* ── Quota bar: used + available in credits ── */
function QuotaBar({ acc }: { acc: Account }) {
  if (acc.quota_total == null) {
    return (
      <div className="flex items-center gap-2 text-[11px] text-neutral-600">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 20a8 8 0 1 1 8-8" /><path d="M12 12l4-4" />
        </svg>
        <span>quota not fetched</span>
      </div>
    )
  }

  const total = acc.quota_total
  const used = acc.quota_used ?? (acc.quota_remaining != null ? total - acc.quota_remaining : 0)
  const remaining = acc.quota_remaining ?? (total - used)
  const pct = total > 0 ? Math.min(used / total, 1) : 0
  const exhausted = acc.is_quota_exceeded || remaining <= 0

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[11px]">
        <span className="flex items-center gap-1.5 text-neutral-500">
          Quota
          {acc.plan_name && (
            <span className="chip chip-muted ml-1">
              <Crown size={9} />
              {acc.plan_name}
            </span>
          )}
          <PlanEndChip epoch={acc.plan_end_date} />
        </span>
        <span className={`tabular-nums ${exhausted ? 'text-white font-semibold' : ''}`}>
          {exhausted ? (
            <span>exhausted</span>
          ) : (
            <>
              <span className="text-neutral-100 font-semibold">{Math.round(used)}</span> used
              <span className="mx-1 text-neutral-700">·</span>
              <span>{Math.round(remaining)} left</span>
            </>
          )}
        </span>
      </div>
      <div className="h-[5px] rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.07)' }}>
        <div
          className="h-full rounded-full transition-[width] duration-700 ease-out"
          style={{ width: `${pct * 100}%`, background: '#e5e5e5' }}
        />
      </div>
      <div className="flex justify-between text-[10px] text-neutral-600 tabular-nums">
        <span>0</span>
        <span>{Math.round(total)} {acc.quota_unit}</span>
      </div>
    </div>
  )
}

/* ── Copy full PAT to clipboard ── */
function CopyPatButton({ accountId }: { accountId: number }) {
  const [copied, setCopied] = useState(false)

  const onCopy = async () => {
    try {
      const pat = await fetchAccountPat(accountId)
      await navigator.clipboard.writeText(pat)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard or fetch failed — leave icon unchanged */
    }
  }

  return (
    <button onClick={onCopy} className="icon-btn w-5 h-5 shrink-0" title="Copy full PAT">
      {copied ? <Check size={11} className="text-white" /> : <Copy size={11} />}
    </button>
  )
}

function AccountCard({ acc, onToggle, onDelete, onRefreshQuota, quotaRefreshing, showEmail, showTokens, showRequests }: {
  acc: Account
  onToggle: () => void
  onDelete: () => void
  onRefreshQuota: () => void
  quotaRefreshing: boolean
  showEmail: boolean
  showTokens: boolean
  showRequests: boolean
}) {
  const status = getStatus(acc)

  return (
    <motion.div variants={rise} layout>
      <Card className="p-5 group">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div
              className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 text-[13px] font-bold"
              style={{
                background: 'rgba(255,255,255,0.06)',
                border: '1px solid rgba(255,255,255,0.1)',
                color: '#e5e5e5',
              }}
            >
              {acc.name.slice(0, 2).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2.5">
                <span className="font-semibold text-white truncate tracking-tight">{acc.name}</span>
                <StatusBadge status={status} />
              </div>
              {showEmail && acc.email && (
                <div className="text-[10px] text-neutral-600 truncate mt-0.5">{acc.email}</div>
              )}
              <div className="flex items-center gap-1.5 mt-1 text-[11px] text-neutral-500 font-mono">
                <KeyRound size={10} className="shrink-0" />
                <span className="truncate">{acc.pat_short}</span>
                <CopyPatButton accountId={acc.id} />
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
            <button onClick={onRefreshQuota} disabled={quotaRefreshing} className="icon-btn" title="Refresh quota">
              <RefreshCw size={14} className={quotaRefreshing ? 'animate-spin' : ''} />
            </button>
            <button onClick={onToggle} className="icon-btn" title={acc.is_active ? 'Disable' : 'Enable'}>
              {acc.is_active ? <Power size={14} /> : <PowerOff size={14} />}
            </button>
            <button onClick={onDelete} className="icon-btn" title="Remove">
              <Trash2 size={14} />
            </button>
          </div>
        </div>

        <div className="mt-4">
          <QuotaBar acc={acc} />
        </div>
        <div
          className="mt-3 pt-3 flex items-center gap-5 text-[11px] text-neutral-500"
          style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}
        >
          {showRequests && (
            <span className="flex items-center gap-1.5">
              <Activity size={11} className="text-neutral-600" />
              <span className="tabular-nums">{acc.total_requests.toLocaleString()}</span> req
            </span>
          )}
          {showTokens && (
            <span className="flex items-center gap-1.5">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-neutral-600">
                <path d="M4 17l6-6-6-6M12 19h8" />
              </svg>
              <span className="tabular-nums">{acc.total_tokens.toLocaleString()}</span> tok
            </span>
          )}
          <span className="ml-auto text-neutral-600">
            {acc.last_used_at ? timeAgo(acc.last_used_at) : 'never used'}
          </span>
        </div>

        {acc.last_error_message && (
          <div
            className="mt-3 px-3 py-2 rounded-lg text-[11px] font-mono text-neutral-300 line-clamp-1"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)' }}
          >
            {acc.last_error_message}
          </div>
        )}
      </Card>
    </motion.div>
  )
}

export function AccountManager() {
  const { data: pool, isLoading: loadingFromPool, error } = usePoolStatus()
  const { data: appSettings } = useSettings()
  const addAccount = useAddAccount()
  const deleteAccount = useDeleteAccount()
  const updateAccount = useUpdateAccount()
  const refreshQuota = useRefreshQuota()
  
  // Use dedicated endpoints for filtered views
  const { data: availableData, isLoading: loadingAvailable } = useAvailableAccounts()
  const { data: exhaustedData, isLoading: loadingExhausted } = useExhaustedAccounts()

  const [showAdd, setShowAdd] = useState(false)
  const [addForm, setAddForm] = useState({ name: '', pat_token: '', priority: 0 })
  const [quotaRefreshingId, setQuotaRefreshingId] = useState<number | null>(null)

  // Tab state lives in the URL — survives page refresh
  const { tab } = useParams<{ tab: string }>()
  const navigate = useNavigate()
  const activeTab: 'available' | 'exhausted' = tab === 'exhausted' ? 'exhausted' : 'available'
  const setActiveTab = (t: 'available' | 'exhausted') => navigate(`/accounts/${t}`)

  // Get current data based on active tab
  const accountsData = activeTab === 'available' ? availableData : exhaustedData
  const currentAccounts = accountsData?.accounts ?? []

  const handleAdd = async () => {
    try {
      await addAccount.mutateAsync({ ...addForm, model_level: 'auto' })
      setShowAdd(false)
      setAddForm({ name: '', pat_token: '', priority: 0 })
    } catch {
      /* surfaced via addAccount.isError */
    }
  }

  const handleRefreshQuota = async (id: number) => {
    setQuotaRefreshingId(id)
    try {
      await refreshQuota.mutateAsync(id)
    } catch {
      /* mutation error state handles display */
    } finally {
      setQuotaRefreshingId(null)
    }
  }

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-6">
      {/* Header */}
      <motion.div variants={rise} className="flex items-center gap-4">
        <div className="flex-1 min-w-0">
          <h1 className="text-[24px] font-bold text-white tracking-tight">Account Pool</h1>
        </div>
        {/* Tabs — centered in header row */}
        {!loadingAvailable && !loadingExhausted && !error && pool?.accounts && pool.accounts.length > 0 && (
          <div className="inline-flex p-1 rounded-xl bg-white/5 border border-white/10 shrink-0">
            <button
              onClick={() => setActiveTab('available')}
              className={`px-4 py-2 rounded-lg text-xs font-medium transition-all duration-300 flex items-center gap-2 ${
                activeTab === 'available'
                  ? 'bg-white text-black shadow-lg'
                  : 'text-neutral-400 hover:text-neutral-300 hover:bg-white/5'
              }`}
            >
              <WalletMinimal size={13} className={activeTab === 'available' ? '' : 'opacity-60'} />
              Available ({availableData?.count ?? 0})
            </button>
            <button
              onClick={() => setActiveTab('exhausted')}
              className={`px-4 py-2 rounded-lg text-xs font-medium transition-all duration-300 flex items-center gap-2 ${
                activeTab === 'exhausted'
                  ? 'bg-white text-black shadow-lg'
                  : 'text-neutral-400 hover:text-neutral-300 hover:bg-white/5'
              }`}
            >
              <Wallet size={13} className={activeTab === 'exhausted' ? '' : 'opacity-60'} />
              Exhausted ({exhaustedData?.count ?? 0})
            </button>
          </div>
        )}
        <div className="flex-1 flex justify-end">
          <button onClick={() => setShowAdd(true)} className="btn-primary">
            <Plus size={15} />
            Add Account
          </button>
        </div>
      </motion.div>

      {/* Stat strip */}
      {pool && (
        <motion.div variants={rise} className="grid grid-cols-4 gap-4">
          {[
            { label: 'Total', value: pool.total_accounts, style: { color: '#fafafa' } },
            { label: 'Active', value: pool.active_accounts, style: { color: '#d4d4d4' } },
            { label: 'Available', value: pool.available_accounts, style: { color: '#a3a3a3' } },
            { label: 'Error', value: pool.accounts_in_cooldown, style: { color: '#737373' } },
          ].map((s) => (
            <Card key={s.label} className="px-5 py-4">
              <div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-neutral-600">{s.label}</div>
              <div className="text-2xl font-bold tabular-nums mt-1" style={s.style}>
                {s.value}
              </div>
            </Card>
          ))}
        </motion.div>
      )}

      {/* Aggregate credits */}
      {pool && (() => {
        const withQuota = pool.accounts.filter((a) => a.quota_total != null && a.quota_total > 0)
        if (!withQuota.length) return null
        const total = withQuota.reduce((s, a) => s + (a.quota_total ?? 0), 0)
        const used = withQuota.reduce((s, a) => s + (a.quota_used ?? (a.quota_remaining != null ? (a.quota_total ?? 0) - a.quota_remaining : 0)), 0)
        const left = withQuota.reduce((s, a) => s + (a.quota_remaining ?? 0), 0)
        const pct = total > 0 ? Math.min(used / total, 1) : 0
        return (
          <motion.div variants={rise}>
            <Card className="px-5 py-4">
              <div className="flex items-center justify-between">
                <div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-neutral-600">Pool Credits</div>
                <div className="text-[11px] text-neutral-500 tabular-nums">
                  <span className="text-neutral-100 font-semibold">{Math.round(used).toLocaleString()}</span> used
                  <span className="mx-1.5 text-neutral-700">·</span>
                  <span>{Math.round(left).toLocaleString()} left</span>
                  <span className="mx-1.5 text-neutral-700">·</span>
                  <span>{Math.round(total).toLocaleString()} total</span>
                </div>
              </div>
              <div className="mt-3 h-[6px] rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.07)' }}>
                <div
                  className="h-full rounded-full transition-[width] duration-700 ease-out"
                  style={{ width: `${pct * 100}%`, background: '#e5e5e5' }}
                />
              </div>
            </Card>
          </motion.div>
        )
      })()}

      {/* Account cards */}
      {loadingAvailable && activeTab === 'available' || loadingExhausted && activeTab === 'exhausted' ? (
        <div className="grid md:grid-cols-2 gap-4">
          {[1, 2].map((i) => <Skeleton key={i} className="h-[150px]" />)}
        </div>
      ) : error ? (
        <Card className="p-6 text-center text-neutral-400 text-sm">{error.message}</Card>
      ) : !pool?.accounts.length ? (
        <Card>
          <EmptyState
            icon={<Plus size={20} />}
            title="No accounts yet"
            hint="Add your first Qoder PAT account to start routing requests through the pool."
            action={
              <button onClick={() => setShowAdd(true)} className="btn-primary">
                <Plus size={14} />
                Add Account
              </button>
            }
          />
        </Card>
      ) : currentAccounts.length === 0 ? (
        <Card>
          <EmptyState
            icon={activeTab === 'exhausted' ? <Wallet size={20} /> : <WalletMinimal size={20} />}
            title={activeTab === 'exhausted' ? 'No exhausted accounts' : 'No available accounts'}
            hint={activeTab === 'exhausted'
              ? 'All your accounts have remaining credits.'
              : 'All your accounts are currently exhausted.'}
          />
        </Card>
      ) : (
        <motion.div variants={stagger} className="grid md:grid-cols-2 gap-4">
          <AnimatePresence>
            {currentAccounts.map((acc) => (
              <AccountCard
                key={acc.id}
                acc={acc}
                quotaRefreshing={quotaRefreshingId === acc.id}
                showEmail={appSettings?.accounts_show_email ?? true}
                showTokens={appSettings?.accounts_show_tokens ?? true}
                showRequests={appSettings?.accounts_show_requests ?? true}
                onToggle={() => updateAccount.mutate({ id: acc.id, is_active: !acc.is_active })}
                onDelete={() => deleteAccount.mutate(acc.id)}
                onRefreshQuota={() => handleRefreshQuota(acc.id)}
              />
            ))}
          </AnimatePresence>
        </motion.div>
      )}

      {/* Add modal */}
      <Modal open={showAdd} onClose={() => setShowAdd(false)} title="Add Account" subtitle="Token is validated against Qoder before saving">
        <div className="space-y-4">
          <div>
            <label className="label">Account name</label>
            <input
              className="input"
              placeholder="e.g. production-main"
              value={addForm.name}
              onChange={(e) => setAddForm({ ...addForm, name: e.target.value })}
            />
          </div>

          <div>
            <label className="label">Personal Access Token</label>
            <input
              className="input font-mono"
              placeholder="pt-..."
              type="password"
              value={addForm.pat_token}
              onChange={(e) => setAddForm({ ...addForm, pat_token: e.target.value })}
            />
            <p className="text-[11px] text-neutral-600 mt-1.5 flex items-center gap-1">
              Get yours at
              <a
                href="https://qoder.com/account/integrations"
                target="_blank"
                rel="noopener noreferrer"
                className="text-neutral-300 hover:text-white inline-flex items-center gap-0.5 transition-colors"
              >
                qoder.com/account/integrations <ArrowUpRight size={10} />
              </a>
            </p>
          </div>

          <div>
            <label className="label">Priority</label>
            <input
              type="number"
              className="input"
              value={addForm.priority}
              onChange={(e) => setAddForm({ ...addForm, priority: parseInt(e.target.value) || 0 })}
              min={0}
              max={100}
            />
            <p className="text-[11px] text-neutral-600 mt-1.5">Higher priority accounts are preferred in rotation.</p>
          </div>

          {addAccount.isError && (
            <div
              className="px-3 py-2.5 rounded-lg text-xs text-red-300"
              style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)' }}
            >
              {addAccount.error.message}
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button onClick={() => setShowAdd(false)} className="btn-ghost flex-1">Cancel</button>
            <button
              onClick={handleAdd}
              disabled={!addForm.name || !addForm.pat_token || addAccount.isPending}
              className="btn-primary flex-1"
            >
              {addAccount.isPending ? (
                <>
                  <span className="w-3.5 h-3.5 rounded-full border-2 border-black/20 border-t-black animate-spin" />
                  Validating…
                </>
              ) : (
                'Add Account'
              )}
            </button>
          </div>
        </div>
      </Modal>
    </motion.div>
  )
}
