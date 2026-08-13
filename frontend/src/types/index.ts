export interface Account {
  id: number
  name: string
  pat_short: string
  is_active: boolean
  is_available: boolean
  priority: number
  model_level: string
  default_model: string
  last_used_at: string | null
  last_error_at: string | null
  last_error_message: string | null
  consecutive_failures: number
  total_requests: number
  total_tokens: number
  plan_tier: string | null
  plan_name: string | null
  is_paid: boolean
  plan_end_date: number | null
  quota_expires_at: number | null
  email: string | null
  activity_id: string | null
  activity_status: 'claimable' | 'active' | 'exhausted' | null
  activity_label: string | null
  activity_model: string | null
  activity_limit: number | null
  activity_used: number
  activity_remaining: number | null
  activity_expires_at: number | null
  activity_checked_at: number | null
  activity_claimed_at: number | null
  quota_total: number | null
  quota_used: number | null
  quota_remaining: number | null
  quota_percentage: number | null
  quota_unit: string
  is_quota_exceeded: boolean
  quota_fetched_at: number | null
  created_at: string
  updated_at: string
}

export interface AccountPoolStatus {
  total_accounts: number
  active_accounts: number
  available_accounts: number
  accounts_in_cooldown: number
  total_requests: number
  accounts: Account[]
}

export interface DashboardStats {
  total_accounts: number
  active_accounts: number
  available_now: number
  accounts_in_cooldown: number
  total_requests: number
  total_tokens: number
  credits_spent: number
  accounts_by_model: Record<string, number>
  recent_errors: Array<{
    account_id: number
    account_name: string
    message: string
    at: string | null
  }>
}

export interface ModelEntry {
  display_name: string
  level_key: string
}

export interface ModelCatalogEntry {
  key: string
  name: string
  credit_factor: number
  is_reasoning: boolean
  supports_thinking: boolean
  thinking_efforts: string[]
  default_thinking_effort: string | null
  is_vision: boolean
  max_input_tokens: number
  context_windows: number[]
  kind: 'tier' | 'model'
}

export interface WorkerStatus {
  running: boolean
  started_at: number | null
  finished_at: number | null
  exit_code: number | null
  success: boolean | null
  auto_add: boolean
  added_account_id: number | null
  pat_short: string | null
  lines: string[]
}

export type QoderInferBase = 'api1' | 'api2' | 'api3'

export interface AppSettings {
  worker_logs_enabled: boolean
  worker_retry_allow: boolean
  accounts_show_email: boolean
  accounts_show_tokens: boolean
  accounts_show_requests: boolean
  accounts_auto_delete_exhausted: boolean
  accounts_auto_delete_keep_activity: boolean
  account_activity_checks_enabled: boolean
  qoder_infer_base: QoderInferBase
  probe_interval_minutes: number
  probe_model_keys: string[]
}

export interface ModelStatus {
  model: string
  display: string
  alive: boolean
  is_queued: boolean
  tps: number
  tokens: number
  latency_ms: number
  error: string | null
  at: number
}

export interface ModelStatusSnapshot {
  enabled: boolean
  interval_minutes: number
  probing: boolean
  last_run: number | null
  models: ModelStatus[]
}

export interface ActivityPoint {
  t: number
  requests: number
  tokens: number
}

export interface ModelUsage {
  model: string
  display: string
  requests: number
  tokens: number
  credits: number
}

export interface ActivityStats {
  bucket_sec: number
  series: ActivityPoint[]
  by_model: ModelUsage[]
  window: { requests: number; tokens: number; credits: number }
}
