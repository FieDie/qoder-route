const STORAGE_KEY = 'qoderroute.apiKey'

export const UNAUTHORIZED_EVENT = 'qoderroute:unauthorized'

export function getApiKey(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export function setApiKey(key: string) {
  try {
    if (key) localStorage.setItem(STORAGE_KEY, key)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* private mode / blocked storage */
  }
}

export function authHeaders(): Record<string, string> {
  const key = getApiKey()
  return key ? { Authorization: `Bearer ${key}` } : {}
}

export function notifyUnauthorized() {
  window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
}

export function logsStreamUrl(): string {
  const key = getApiKey()
  return key
    ? `/api/logs/stream?api_key=${encodeURIComponent(key)}`
    : '/api/logs/stream'
}

/** Does not go through the panel fetch helper, so a stale key will not open the unlock overlay. */
export async function verifyApiKey(key: string): Promise<boolean> {
  if (!key) return false
  try {
    const res = await fetch('/api/auth/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    })
    if (!res.ok) return false
    const data = await res.json()
    return data.valid === true
  } catch {
    return false
  }
}

export async function rememberKeyIfNeeded(newKey: string) {
  if (!newKey) return
  const stored = getApiKey()
  if (!stored) {
    setApiKey(newKey)
    return
  }
  if (!(await verifyApiKey(stored))) setApiKey(newKey)
}
