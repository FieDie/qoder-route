import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Account, AccountPoolStatus, ActivityStats, AppSettings, DashboardStats, ModelCatalogEntry, ModelEntry, ModelStatusSnapshot, WorkerStatus } from '../types'

const BASE = ''

async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || err.message || 'Request failed')
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
    mutationFn: (data: { name: string; pat_token: string; priority: number; model_level: string }) =>
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
    mutationFn: ({ id, ...data }: { id: number; name?: string; is_active?: boolean; priority?: number; model_level?: string }) =>
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

export function useClaimActivity() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api<Account>(`/api/accounts/${id}/activity/claim`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pool-status'] })
      qc.invalidateQueries({ queryKey: ['accounts', 'available'] })
      qc.invalidateQueries({ queryKey: ['accounts', 'exhausted'] })
    },
  })
}

export async function fetchAccountPat(id: number): Promise<string> {
  const data = await api<{ pat: string }>(`/api/accounts/${id}/pat`)
  return data.pat
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
    mutationFn: (data: { pat: string; retry_allow: boolean; auto_add: boolean }) =>
      api<WorkerStatus>('/api/worker/run', { method: 'POST', body: JSON.stringify(data) }),
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
