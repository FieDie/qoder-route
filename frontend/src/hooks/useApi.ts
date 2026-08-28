import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Account, AccountPoolStatus, ActivityStats, AppSettings, CreatedPanelApiKey, DashboardStats, ModelCatalogEntry, ModelEntry, ModelStatusSnapshot, PanelApiKey, WorkerStatus } from '../types'
import { authHeaders, notifyUnauthorized } from '../lib/apiKey'

const BASE = ''

function errorMessage(err: { detail?: unknown; message?: string }, fallback: string): string {
  const detail = err.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && typeof detail[0]?.msg === 'string') return detail[0].msg
  if (typeof err.message === 'string' && err.message) return err.message
  return fallback
}

async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const { headers: extraHeaders, ...rest } = options ?? {}
  const res = await fetch(`${BASE}${url}`, {
    ...rest,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(extraHeaders as Record<string, string> | undefined),
    },
  })
  if (res.status === 401) {
    notifyUnauthorized()
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(errorMessage(err, 'Request failed'))
  }
  return res.json()
}

export function usePoolStatus() {
  return useQuery<AccountPoolStatus>({
    queryKey: ['pool-status'],
    queryFn: () => api('/api/accounts'),
    refetchInterval: 5000,
  })
}

export function useAvailableAccounts() {
  return useQuery<{ filter: string; count: number; accounts: Account[] }>({
    queryKey: ['accounts', 'available'],
    queryFn: () => api('/api/accounts/available'),
    refetchInterval: 30000,
  })
}

export function useExhaustedAccounts() {
  return useQuery<{ filter: string; count: number; accounts: Account[] }>({
    queryKey: ['accounts', 'exhausted'],
    queryFn: () => api('/api/accounts/exhausted'),
    refetchInterval: 30000,
  })
}

export function useDashboardStats() {
  return useQuery<DashboardStats>({
    queryKey: ['dashboard-stats'],
    queryFn: () => api('/api/accounts/stats/dashboard'),
    refetchInterval: 10000,
  })
}

export function useActivityStats() {
  return useQuery<ActivityStats>({
    queryKey: ['activity-stats'],
    queryFn: () => api('/api/accounts/stats/activity'),
    refetchInterval: 5000,
  })
}

export function useModelStatus() {
  return useQuery<ModelStatusSnapshot>({
    queryKey: ['model-status'],
    queryFn: () => api('/api/status/models'),
    refetchInterval: 5000,
  })
}

export function useAvailableModels() {
  return useQuery<ModelEntry[]>({
    queryKey: ['models'],
    queryFn: () => api('/api/accounts/models/list'),
    staleTime: 300000,
  })
}

export function useModelCatalog() {
  return useQuery<ModelCatalogEntry[]>({
    queryKey: ['model-catalog'],
    queryFn: () => api('/api/models/catalog'),
    staleTime: 300000,
  })
}

export function useAddAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { name?: string; pat_token: string; priority: number; model_level: string }) =>
      api<Account>('/api/accounts', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pool-status'] })
      qc.invalidateQueries({ queryKey: ['dashboard-stats'] })
      qc.invalidateQueries({ queryKey: ['accounts', 'available'] })
      qc.invalidateQueries({ queryKey: ['accounts', 'exhausted'] })
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['pool-status'] })
        qc.invalidateQueries({ queryKey: ['dashboard-stats'] })
        qc.invalidateQueries({ queryKey: ['accounts', 'available'] })
        qc.invalidateQueries({ queryKey: ['accounts', 'exhausted'] })
      }, 2500)
    },
  })
}

export function useUpdateAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: { id: number; name?: string; priority?: number; model_level?: string }) =>
      api<Account>(`/api/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pool-status'] })
      qc.invalidateQueries({ queryKey: ['dashboard-stats'] })
      qc.invalidateQueries({ queryKey: ['accounts', 'available'] })
      qc.invalidateQueries({ queryKey: ['accounts', 'exhausted'] })
    },
  })
}

export function useDeleteAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api(`/api/accounts/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      // invalidate all account-related queries so UI updates immediately
      qc.invalidateQueries({ queryKey: ['pool-status'] })
      qc.invalidateQueries({ queryKey: ['dashboard-stats'] })
      qc.invalidateQueries({ queryKey: ['accounts', 'available'] })
      qc.invalidateQueries({ queryKey: ['accounts', 'exhausted'] })
    },
  })
}

export function useRefreshQuota() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<{ ok: boolean; quota: Record<string, unknown> }>(`/api/accounts/${id}/quota/refresh`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pool-status'] })
      qc.invalidateQueries({ queryKey: ['dashboard-stats'] })
      qc.invalidateQueries({ queryKey: ['accounts', 'available'] })
      qc.invalidateQueries({ queryKey: ['accounts', 'exhausted'] })
    },
  })
}

export async function fetchAccountPat(id: number): Promise<string> {
  const data = await api<{ pat: string }>(`/api/accounts/${id}/pat`)
  return data.pat
}

export async function fetchApiKeySecret(id: number): Promise<string> {
  const data = await api<{ key: string }>(`/api/auth/keys/${id}`)
  return data.key
}

export function useWorkerStatus() {
  return useQuery<WorkerStatus>({
    queryKey: ['worker-status'],
    queryFn: () => api('/api/worker/status'),
    refetchInterval: (query) => (query.state.data?.running ? 800 : 4000),
  })
}

export function useRunWorker() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { pat: string; retry_allow: boolean; auto_add: boolean; proxy: string | null }) =>
      api<WorkerStatus>('/api/worker/run', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['worker-status'] })
    },
  })
}

export function useRemoveFromQueue() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (index: number) =>
      api(`/api/worker/queue/${index}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['worker-status'] })
    },
  })
}

export function useClearQueue() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api(`/api/worker/queue`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['worker-status'] })
    },
  })
}

export function useSettings() {
  return useQuery<AppSettings>({
    queryKey: ['settings'],
    queryFn: () => api('/api/settings'),
  })
}

export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    scope: { id: 'settings' },
    mutationFn: (data: Partial<AppSettings>) =>
      api<AppSettings>('/api/settings', { method: 'PUT', body: JSON.stringify(data) }),
    onMutate: async (data) => {
      await qc.cancelQueries({ queryKey: ['settings'] })
      const prev = qc.getQueryData<AppSettings>(['settings'])
      qc.setQueryData<AppSettings>(['settings'], (old) => (old ? { ...old, ...data } : old))
      return { prev }
    },
    onError: (_err, _data, ctx) => {
      if (ctx?.prev) qc.setQueryData(['settings'], ctx.prev)
    },
    onSettled: (data) => {
      if (data) qc.setQueryData(['settings'], data)
    },
  })
}

export function useApiKeys() {
  return useQuery<{ keys: PanelApiKey[] }>({
    queryKey: ['api-keys'],
    queryFn: () => api('/api/auth/keys'),
  })
}

export function useCreateApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      api<CreatedPanelApiKey>('/api/auth/keys', {
        method: 'POST',
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })
}

export function useDeleteApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api(`/api/auth/keys/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['api-keys'] })
      qc.invalidateQueries({ queryKey: ['settings'] })
    },
  })
}
