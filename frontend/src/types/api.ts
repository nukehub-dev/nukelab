// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

export interface PaginatedResponse<T> {
  data: T[]
  pagination: {
    page: number
    limit: number
    total: number
    totalPages: number
  }
}

export interface ServerVolumeMount {
  volume_id: string
  mount_path: string
  mode: 'read_write' | 'read_only'
  is_primary?: boolean
  max_size_bytes?: number | null
  volume?: {
    id: string
    name: string
    display_name: string
    size_bytes: number
    max_size_bytes?: number | null
  }
}

export interface Server {
  id: string
  name: string
  status: 'running' | 'stopped' | 'pending' | 'error'
  external_url?: string
  user_id?: string
  username?: string
  plan_id?: string
  environment_id?: string
  created_at?: string
  container_id?: string
  volume_id?: string
  volume_mode?: string
  volume_mounts?: ServerVolumeMount[]
  allocated_cpu?: number
  allocated_memory?: string
  allocated_disk?: string
  health_status?: string
  status_reason?: string
  stop_reason?: string
  started_at?: string
  stopped_at?: string
  last_activity?: string
  expires_at?: string
  total_cost?: number
  last_billed_at?: string
}

export interface User {
  id: string
  username: string
  email: string
  first_name?: string
  last_name?: string
  display_name: string
  avatar_url: string
  role: string
  permissions?: string[]
  nuke_balance: number
  daily_allowance: number
  daily_allowance_override?: number | null
  daily_allowance_override_until?: string | null
  effective_daily_allowance?: number
  has_active_allowance_override?: boolean
  is_active: boolean
  is_verified: boolean
  last_login?: string
  created_at?: string
  updated_at?: string
  login_count: number
  oauth_provider?: string
  profile?: Record<string, unknown>
  preferences?: Record<string, unknown>
  profile_visibility?: 'private' | 'public'
}

export interface PublicUser {
  id: string
  username: string
  display_name: string
  avatar_url: string
}

export interface Environment {
  id: string
  name: string
  slug: string
  image: string
  description?: string
  category?: string
  is_active: boolean
  is_public: boolean
  created_at: string
  updated_at?: string
  created_by?: string
  icon?: string
  color?: string
}

export interface Plan {
  id: string
  name: string
  slug: string
  description?: string
  category: string
  cpu_limit: number
  memory_limit: string
  disk_limit: string
  gpu_limit: number
  max_servers_per_user: number
  cost_per_hour: number
  cooldown_seconds: number
  is_public: boolean
  visible_to_roles: string[]
  is_active: boolean
  priority: number
  created_at: string
  updated_at?: string
}

export interface ApiToken {
  id: string
  name: string
  scopes: string[]
  usage_count: number
  last_used_at?: string
  created_at: string
  expires_at?: string
  is_active: boolean
}

export interface ApiTokenWithValue extends ApiToken {
  token: string
}

export interface ApiTokenUsage {
  token_id: string
  name: string
  usage_count: number
  last_used_at?: string
  created_at?: string
  expires_at?: string
  is_active: boolean
}

export interface CreditTransaction {
  id: string
  user_id: string
  amount: number
  balance_after: number
  type: 'admin_grant' | 'admin_deduct' | 'server_usage' | 'daily_allowance' | string
  description: string
  server_id?: string
  actor_id?: string
  metadata?: Record<string, unknown>
  created_at: string
}

export interface CreditSummary {
  user_id: string
  current_balance: number
  today_consumed: number
  total_earned: number
  total_consumed: number
}

export interface CreditHistoryResponse {
  transactions: CreditTransaction[]
  pagination: {
    page: number
    limit: number
    total: number
    total_pages: number
  }
}

export interface LowBalanceUser {
  id: string
  username: string
  nuke_balance: number
  daily_allowance: number
  email: string
}

export interface WorkspaceActivity {
  id: string
  actor_id: string | null
  action: string
  target_type: string
  target_id: string | null
  details: Record<string, unknown>
  created_at: string
  actor?: {
    username: string
    display_name: string
    avatar_url: string
  } | null
}

export interface PublicProfile {
  id: string
  username: string
  display_name: string
  avatar_url: string
  role: string
  profile_visibility: 'private' | 'public'
  profile: Record<string, unknown>
  created_at?: string
}

export interface UserPreferences {
  theme?: string
  accent_color?: string | null
  oled_mode?: boolean
  use_gravatar?: boolean
  language?: string
  timezone?: string
  default_environment?: string
  default_plan?: string
  sidebar_collapsed?: boolean
  sidebar_pinned?: boolean
  density?: 'compact' | 'comfortable'
  pinned_workspace_ids?: string[]
  notifications?: Record<string, unknown>
  dashboard?: Record<string, unknown>
  idle_shutdown_enabled?: boolean
  idle_shutdown_timeout?: number
  stop_on_logout?: boolean
}

export interface ApiError {
  detail: string
}
