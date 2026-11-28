// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

export type JobState =
  | 'queued'
  | 'starting'
  | 'running'
  | 'cancelling'
  | 'recovery_required'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'timed_out'
  | 'expired'

export type JobListFilter = 'active' | 'history' | 'all'

export type JobOutcomeCode =
  'succeeded' | 'failed' | 'cancelled' | 'timed_out' | 'expired' | 'runtime_unverifiable'

export type JobLogState = 'pending' | 'available' | 'truncated' | 'unavailable' | 'expired'

export type JobBillingMode = 'zero_cost' | 'paid'

export type JobBillingState = 'none' | 'held' | 'settled' | 'released'

export interface JobLimits {
  max_active_jobs: number
  max_queued_jobs: number
  default_runtime_seconds: number
  max_runtime_seconds: number
  queue_ttl_seconds: number
  max_argv_items: number
  max_input_bytes: number
  log_tail_bytes: number
  log_retention_seconds: number
}

export interface JobCapabilities {
  enabled: boolean
  can_submit: boolean
  billing_mode: JobBillingMode
  secrets_enabled: boolean
  storage_limits_enforced: boolean
  storage_enforcement_required: boolean
  reason_code: string | null
  limits: JobLimits
}

export interface EligibleJobRevision {
  revision_id: string
  environment_id: string
  environment_name: string
  display_label: string
  fingerprint: string | null
  portable_fingerprint: string | null
  image_reference: string | null
  supports_jobs: boolean
  reason_code: string | null
}

export interface EligibleJobRevisionList {
  items: EligibleJobRevision[]
}

export interface JobSummary {
  id: string
  name: string
  state: JobState
  reason_code: string | null
  environment_name: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  can_cancel: boolean
}

export interface JobPage {
  items: JobSummary[]
  next_cursor: string | null
}

export interface JobEnvironmentSnapshot {
  revision_id: string
  environment_id: string
  name: string
  display_label: string
  fingerprint: string | null
  image_reference: string | null
}

export interface JobPlanSnapshot {
  id: string
  name: string
  cpu: number
  memory_mib: number
  disk_mib: number
  gpu_count: number
  cost_per_hour: number
}

export interface JobVolumeLink {
  id: string
  display_name: string
  available: boolean
}

export interface JobResult {
  exit_code: number | null
  outcome_code: JobOutcomeCode
  started_at: string | null
  finished_at: string | null
  duration_seconds: number | null
  proof: string | null
}

export interface JobLogSummary {
  state: JobLogState
  truncated: boolean
  size_bytes: number
  expires_at: string | null
}

export interface JobBilling {
  mode: JobBillingMode
  charged: number
  authorized: number
  rate_per_hour: number
  state: JobBillingState
}

export interface JobDetail {
  id: string
  name: string
  state: JobState
  reason_code: string | null
  reason_message: string | null
  created_at: string
  updated_at: string | null
  queue_expires_at: string | null
  started_at: string | null
  finished_at: string | null
  deadline_at: string | null
  can_cancel: boolean
  replayed: boolean
  environment: JobEnvironmentSnapshot
  plan: JobPlanSnapshot
  volume: JobVolumeLink | null
  argv: string[]
  limits: { max_runtime_seconds: number }
  result: JobResult | null
  logs: JobLogSummary
  billing: JobBilling
}

export interface JobLogs {
  state: JobLogState
  text?: string | null
  truncated: boolean
  size_bytes: number
  expires_at: string | null
  encoding?: string
}

export interface CreateJobRequest {
  name: string
  revision_id: string
  plan_id: string
  volume_id: string
  argv: string[]
  max_runtime_seconds: number
}

export type JobErrorCode =
  | 'feature_disabled'
  | 'permission_denied'
  | 'job_not_found'
  | 'idempotency_conflict'
  | 'invalid_request'
  | 'argv_too_large'
  | 'runtime_too_long'
  | 'revision_unavailable'
  | 'plan_unavailable'
  | 'paid_plan_unsupported'
  | 'insufficient_credits'
  | 'volume_unavailable'
  | 'volume_busy'
  | 'job_limit_reached'
  | 'job_not_cancellable'
  | 'runtime_unverifiable'

export type JobFormField =
  'name' | 'revision_id' | 'plan_id' | 'volume_id' | 'argv' | 'max_runtime_seconds'
