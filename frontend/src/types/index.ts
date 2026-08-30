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
  accounts_exhausted: number
  total_requests: number
  total_tokens: number
  credits_spent: number
  recent_errors: Array<{
    account_id: number
    account_name: string
    message: string
    at: string | null
  }>
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
  context_length: number
  kind: 'tier' | 'model'
}

export interface WorkerQueueItem {
  pat_short: string
  retry_allow: boolean
  auto_add: boolean
  has_proxy: boolean
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
  queue: WorkerQueueItem[]
}

export type QoderInferBase = 'api1' | 'api2' | 'api3'

export interface AppSettings {
  worker_logs_enabled: boolean
  worker_retry_allow: boolean
  worker_proxy_use: boolean
  accounts_show_email: boolean
  accounts_show_tokens: boolean
  accounts_show_requests: boolean
  accounts_auto_delete_exhausted: boolean
  qoder_infer_base: QoderInferBase
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

export type LogLevel = 'info' | 'warn' | 'error'
export type LogPhase = 'start' | 'retry' | 'swap' | 'done' | 'error'
export type LogOutcome = 'ok' | 'quota' | 'queue' | 'rate_limit' | 'infra' | 'account'
export type LogDialect = 'openai' | 'anthropic'

/** Pool lifecycle actions on source === "pool" events. */
export type PoolAction =
  | 'added'
  | 'removed'
  | 'parked'
  | 'auto_deleted'
  | 'cooldown'
  | 'restored'

export interface LogEvent {
  seq: number
  ts: number
  level: LogLevel
  source: string
  message: string
  request_id?: string
  dialect?: LogDialect
  phase?: LogPhase
  outcome?: LogOutcome
  /** Pool lifecycle verb when source === "pool". */
  action?: PoolAction | string
  reason?: string
  account_id?: number
  account_name?: string
  model?: string
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  credits?: number
  latency_ms?: number
  first_token_ms?: number
  thinking_chars?: number
  tool_calls?: number
  finish_reason?: string
}

export interface RequestSummary {
  request_id: string
  ts: number
  last_ts: number
  level?: LogLevel
  source?: string
  message?: string
  dialect?: LogDialect
  model?: string
  account_id?: number
  account_name?: string
  phase?: LogPhase
  outcome?: LogOutcome
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  credits?: number
  latency_ms?: number
  first_token_ms?: number
  thinking_chars?: number
  tool_calls?: number
  finish_reason?: string
  live?: boolean
}

