// ==================== Instance Types ====================
export type InstanceStatus = 'creating' | 'running' | 'stopped' | 'error' | 'destroyed' | 'destroying'

export interface Instance {
  id: string
  name: string
  status: InstanceStatus
  docker_id?: string
  container_id?: string  // Alias for docker_id (backend compatibility)
  redsocks_container_id?: string
  port?: number  // Alias for adb_port
  ram_limit_mb: number
  cpu_cores: number
  assigned_account_id?: string
  assigned_account_email?: string
  assigned_proxy_host?: string
  created_at: string
  updated_at: string
}

export interface InstanceCreateRequest {
  name: string
  ram_limit_mb?: number
  cpu_cores?: number
}

export interface SystemCapacity {
  total_ram_mb: number
  free_ram_mb: number
  running_instances: number
  max_safe_instances: number
  possible_more_instances: number
}

// Alias for backwards compatibility
export type CapacityInfo = SystemCapacity

// ==================== Account Types ====================
export type AccountStatus = 'new' | 'warming' | 'active' | 'cooldown' | 'banned'
export type AccountType = 'free' | 'premium'

export interface Account {
  id: string
  email: string
  password?: string
  display_name?: string
  type: AccountType
  status: AccountStatus
  proxy_id?: string
  proxy_host?: string
  proxy_port?: number
  assigned_instance_id?: string
  assigned_instance_name?: string
  session_blob_path?: string
  warmup_day?: number
  last_used?: string
  streams_today: number
  total_streams: number
  created_at: string
  updated_at: string
}

export interface AccountCreateRequest {
  email: string
  password?: string
  display_name?: string
  type: AccountType
  proxy_id?: string
}

export interface AccountBatchCreateRequest {
  count: number
  instance_ids?: string[]
}

export interface AccountRegistrationResult {
  registered: number
  failed: number
  accounts: string[]
  capped_at?: number | null
}

// ==================== Challenge Types ====================
export type ChallengeType = 'captcha' | 'email_verify' | 'phone_verify' | 'terms_accept' | 'unknown'
export type ChallengeStatus = 'pending' | 'resolved' | 'expired' | 'failed'

export interface Challenge {
  id: string
  account_id: string
  account_email?: string
  instance_id?: string
  instance_name?: string
  type: ChallengeType
  status: ChallengeStatus
  screenshot_path?: string
  resolved_at?: string
  expires_at: string
  notes?: string
  created_at: string
  updated_at: string
}

// ==================== Song Types ====================
export type SongStatus = 'active' | 'paused' | 'completed' | 'failed'
export type SongPriority = 'high' | 'medium' | 'low'

export interface Song {
  id: string
  spotify_uri: string
  title: string
  artist: string
  album_art_url?: string
  total_target_streams: number
  daily_rate: number
  completed_streams: number
  status: SongStatus
  priority: SongPriority
  created_at: string
  updated_at: string
  streams_today: number
}

export interface SongCreateRequest {
  spotify_uri: string
  title: string
  artist: string
  album_art_url?: string
  total_target_streams: number
  daily_rate: number
  priority?: SongPriority
}

export interface SongETA {
  remaining_streams: number
  estimated_hours: number
  estimated_completion: string
}

// ==================== Proxy Types ====================
export type ProxyProtocol = 'http' | 'https' | 'socks5'
export type ProxyStatus = 'healthy' | 'unhealthy' | 'unchecked'

export interface Proxy {
  id: string
  host: string
  port: number
  username?: string
  password?: string
  protocol: ProxyProtocol
  country?: string
  status: ProxyStatus
  ip?: string
  latency_ms?: number
  last_health_check?: string
  linked_account_id?: string
  linked_account_email?: string
  uptime_pct: number
  created_at: string
  updated_at: string
}

export interface ProxyCreateRequest {
  host: string
  port: number
  username?: string
  password?: string
  protocol: ProxyProtocol
  country?: string
}

export interface ProxyTestResult {
  healthy: boolean
  ip?: string
  latency_ms?: number
  error?: string
}

export interface ProxyTestAllResult {
  total: number
  tested: number
  healthy: number
  unhealthy: number
}

export interface ProxyAutoAssignResult {
  assigned: number
  remaining_unlinked_accounts: number
  remaining_unlinked_proxies: number
}

export interface ProxyIpVerificationResult {
  proxy_id: string
  account_id: string
  instance_id: string
  ip?: string
  matches_proxy?: boolean | null
  proxy_host?: string | null
}

export interface ProxyProviderStatus {
  connected: boolean
  provider: string
  total_proxies?: number
  used_proxies?: number
  available?: number
  message?: string
  error?: string
}

// ==================== Stream Log Types ====================
export type StreamResult = 'success' | 'fail' | 'shuffle_miss' | 'health_check'

export interface StreamLog {
  id: string
  instance_id: string
  account_id: string
  song_id: string
  duration_sec: number
  result: StreamResult
  failure_reason?: string
  created_at: string
  instance_name?: string
  account_email?: string
  song_title?: string
}

export interface StreamLogSummary {
  total_streams: number
  success_rate: number
  avg_duration: number
  streams_today: number
  failed_streams: number
}

export interface StreamLogsQueryParams {
  skip?: number
  limit?: number
  instance_id?: string
  song_id?: string
  result?: StreamResult
  date_from?: string
  date_to?: string
}

// ==================== Settings Types ====================
export interface Settings {
  max_streams_per_account_per_day: number
  min_stream_duration_sec: number
  max_concurrent_streams: number
  rotation_interval_streams: number
  rotation_interval_hours: number
  cooldown_hours: number
  // Phase 9: Legacy humanization level (backward compatible)
  humanization_level: 'low' | 'medium' | 'high'
  // Phase 9: New typed humanization settings
  humanization_enabled: boolean
  humanization_preset: 'low' | 'medium' | 'high' | 'custom'
  pre_stream_min_sec: number
  pre_stream_max_sec: number
  between_tracks_min_sec: number
  between_tracks_max_sec: number
  random_actions_enabled: boolean
  min_actions_per_stream: number
  max_actions_per_stream: number
  warmup_between_tracks_min_sec: number
  warmup_between_tracks_max_sec: number
  default_account_type: 'free' | 'premium'
  warmup_duration_days: number
  creation_delay_min_sec: number
  creation_delay_max_sec: number
  daily_account_creation_cap: number
  daily_reset_hour: number
}

export interface SettingsUpdateRequest {
  settings: Record<string, string>
}

// ==================== System Types ====================
export interface SystemResources {
  cpu_percent: number
  ram_percent: number
  ram_used_gb: number
  ram_total_gb: number
  disk_percent: number
}

// ==================== WebSocket Types ====================
export interface WebSocketMessage {
  type: string
  payload?: unknown
}

export interface InstanceStatusEvent {
  type: 'instance_status'
  instance_id: string
  status: InstanceStatus
}

export interface StreamCompletedEvent {
  type: 'stream_completed'
  instance_id: string
  account_id: string
  song_id: string
  duration_sec: number
}

export interface AlertEvent {
  type: 'alert'
  level: 'info' | 'warning' | 'error'
  message: string
}

// ==================== API Response Types ====================
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  skip: number
  limit: number
}

export interface APIError {
  detail: string
}
