import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { KeyRound } from 'lucide-react'
import { getApiKey, setApiKey, UNAUTHORIZED_EVENT } from '../../lib/apiKey'

export function AuthGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [locked, setLocked] = useState(false)
  const [value, setValue] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    const onUnauthorized = () => setLocked(true)
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  const unlock = (e: FormEvent) => {
    e.preventDefault()
    const key = value.trim()
    if (!key) {
      setError('Paste an API key')
      return
    }
    setApiKey(key)
    setValue('')
    setError('')
    setLocked(false)
    qc.invalidateQueries()
  }

  return (
    <>
      {children}
      {locked && (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center p-4"
          style={{ background: 'rgba(0,0,0,0.92)' }}
        >
          <form
            onSubmit={unlock}
            className="w-full max-w-md rounded-2xl p-6 space-y-4"
            style={{
              background: '#0a0a0a',
              border: '1px solid rgba(255,255,255,0.12)',
              boxShadow: '0 32px 80px -16px rgba(0,0,0,0.9)',
            }}
          >
            <div className="flex items-center gap-3">
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center text-neutral-300"
                style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)' }}
              >
                <KeyRound size={16} />
              </div>
              <div>
                <h2 className="text-[15px] font-semibold text-white tracking-tight">Invalid API key</h2>
                <p className="text-xs text-neutral-500 mt-0.5">
                  Authentication is on. Paste a panel key to continue. Model API routes are unaffected.
                </p>
              </div>
            </div>
            {getApiKey() && (
              <p className="text-[11px] text-neutral-600">
                The stored key was rejected. Replace it below.
              </p>
            )}
            <input
              className="input font-mono"
              placeholder="qr_…"
              type="password"
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            {error && <p className="text-xs text-red-300">{error}</p>}
            <button type="submit" className="btn-primary w-full">
              Unlock panel
            </button>
          </form>
        </div>
      )}
    </>
  )
}
