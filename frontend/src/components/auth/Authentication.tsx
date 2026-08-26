import { useState } from 'react'
import { motion } from 'framer-motion'
import { Check, Copy, KeyRound, Plus, Shield, Trash2 } from 'lucide-react'
import { Card, SectionTitle, Switch, Skeleton, EmptyState } from '../ui/GlassPanel'
import { fetchApiKeySecret, useApiKeys, useCreateApiKey, useDeleteApiKey, useSettings, useUpdateSettings } from '../../hooks/useApi'
import { getApiKey, rememberKeyIfNeeded, setApiKey, verifyApiKey } from '../../lib/apiKey'

function timeAgoLabel(iso: string | null): string {
  if (!iso) return ''
  const ms = new Date(iso.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z').getTime()
  if (!Number.isFinite(ms)) return ''
  const mins = Math.floor((Date.now() - ms) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function CopyKeyButton({ keyId }: { keyId: number }) {
  const [copied, setCopied] = useState(false)

  const onCopy = async () => {
    try {
      const secret = await fetchApiKeySecret(keyId)
      await navigator.clipboard.writeText(secret)
      await rememberKeyIfNeeded(secret)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard or fetch failed */
    }
  }

  return (
    <button type="button" onClick={onCopy} className="icon-btn" title="Copy key">
      {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
    </button>
  )
}

export function Authentication() {
  const { data: settings, isLoading: settingsLoading } = useSettings()
  const { data: keysData, isLoading: keysLoading } = useApiKeys()
  const update = useUpdateSettings()
  const createKey = useCreateApiKey()
  const deleteKey = useDeleteApiKey()

  const [name, setName] = useState('')
  const [toggleError, setToggleError] = useState('')

  const keys = keysData?.keys ?? []
  const enabled = settings?.auth_enabled ?? false

  const onToggle = async (next: boolean) => {
    setToggleError('')
    if (next && keys.length === 0) {
      setToggleError('Create an API key before enabling authentication.')
      return
    }
    try {
      if (next && !getApiKey() && keys[0]) {
        setApiKey(await fetchApiKeySecret(keys[0].id))
      }
      await update.mutateAsync({ auth_enabled: next })
    } catch (err) {
      setToggleError(err instanceof Error ? err.message : 'Failed to update')
    }
  }

  const onCreate = async () => {
    const trimmed = name.trim() || 'Panel key'
    try {
      deleteKey.reset()
      const row = await createKey.mutateAsync(trimmed)
      setName('')
      if (row.key) await rememberKeyIfNeeded(row.key)
    } catch {
      /* mutation error state */
    }
  }

  const onDelete = async (id: number) => {
    const others = keys.filter((k) => k.id !== id)
    const stored = getApiKey()
    let deletingStored = false
    let replacement = ''
    if (stored) {
      try {
        deletingStored = (await fetchApiKeySecret(id)) === stored
      } catch {
        deletingStored = !(await verifyApiKey(stored))
      }
      if (deletingStored && others[0]) {
        replacement = await fetchApiKeySecret(others[0].id)
      }
    }
    try {
      await deleteKey.mutateAsync(id)
      if (deletingStored) setApiKey(replacement)
    } catch {
      /* mutation error state */
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] } }}
      className="space-y-6"
    >
      <div>
        <h1 className="text-[24px] font-bold text-white tracking-tight">Authentication</h1>
        <p className="text-sm text-neutral-500 mt-1">
          Gate the admin panel with API keys. Model routes stay open — <span className="font-mono text-neutral-400">/v1/chat/completions</span>, <span className="font-mono text-neutral-400">/v1/messages</span>, <span className="font-mono text-neutral-400">/v1/models</span>.
        </p>
      </div>

      <Card className="p-5">
        <SectionTitle icon={<Shield size={13} className="text-neutral-400" />}>Panel access</SectionTitle>
        {settingsLoading ? (
          <Skeleton className="h-11" />
        ) : (
          <div className="space-y-3">
            <label className="flex items-center gap-3 cursor-pointer select-none">
              <Switch checked={enabled} onChange={onToggle} disabled={update.isPending} />
              <span className="min-w-0">
                <span className="block text-[13px] font-medium text-neutral-200">Require API key</span>
                <span className="block text-[11px] text-neutral-500 mt-0.5">
                  Off by default. When on, every admin request needs a valid key. Missing or invalid keys return 401 Invalid API key.
                </span>
              </span>
            </label>
            {toggleError && (
              <div
                className="px-3 py-2.5 rounded-lg text-xs text-red-300"
                style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)' }}
              >
                {toggleError}
              </div>
            )}
          </div>
        )}
      </Card>

      <Card className="p-5">
        <SectionTitle icon={<KeyRound size={13} className="text-neutral-400" />}>API keys</SectionTitle>
        <div className="flex gap-2 mb-4">
          <input
            className="input flex-1"
            placeholder="Key name, e.g. laptop"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onCreate()
            }}
            maxLength={128}
          />
          <button
            type="button"
            className="btn-primary shrink-0"
            onClick={onCreate}
            disabled={createKey.isPending}
          >
            <Plus size={14} />
            {createKey.isPending ? 'Creating…' : 'Create key'}
          </button>
        </div>
        {createKey.isError && (
          <div
            className="mb-4 px-3 py-2.5 rounded-lg text-xs text-red-300"
            style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)' }}
          >
            {createKey.error.message}
          </div>
        )}
        {keysLoading ? (
          <Skeleton className="h-24" />
        ) : keys.length === 0 ? (
          <EmptyState
            icon={<KeyRound size={20} />}
            title="No keys yet"
            hint="Create a key, then turn on Require API key. Copy copies the full key to the clipboard."
          />
        ) : (
          <ul className="divide-y divide-white/5">
            {keys.map((key) => (
              <li key={key.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-medium text-neutral-200 truncate">{key.name}</div>
                  <div className="text-[11px] font-mono text-neutral-600 truncate">
                    {key.key_prefix}
                    {key.created_at ? ` · ${timeAgoLabel(key.created_at)}` : ''}
                  </div>
                </div>
                <CopyKeyButton keyId={key.id} />
                <button
                  type="button"
                  className="icon-btn"
                  title="Delete key"
                  onClick={() => onDelete(key.id)}
                  disabled={deleteKey.isPending}
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
        {deleteKey.isError && (
          <div
            className="mt-3 px-3 py-2.5 rounded-lg text-xs text-red-300"
            style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)' }}
          >
            {deleteKey.error.message}
          </div>
        )}
      </Card>
    </motion.div>
  )
}
