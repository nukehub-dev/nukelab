// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

export type AdminJobState =
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

export type AdminJobListState = 'active' | 'history' | 'all'

/**
 * One sanitized job row returned by the read-only admin jobs API. Command
 * arguments, logs, environment values, image/runtime references, volume
 * paths, and fencing tokens are never part of this contract.
 */
export interface AdminJobEntry {
  id: string
  state: AdminJobState | string
  reason_code: string | null
  owner_id: string
  owner_username: string | null
  owner_display_name: string | null
  environment_name: string | null
  environment_display_label: string | null
  plan_name: string | null
  volume_display_name: string | null
  created_at: string | null
  updated_at: string | null
  finished_at: string | null
  reservation_active: boolean
  guard_active: boolean
  heartbeat_age_seconds: number | null
  log_state: string
  cleanup_state: string
  cleanup_attempts: number
  can_reconcile: boolean
  can_cancel: boolean
}

/** Age-filtered state counts that stay stable under the active/history chip. */
export interface AdminJobSummary {
  total: number
  queued: number
  starting: number
  running: number
  cancelling: number
  recovery_required: number
  succeeded: number
  failed: number
  cancelled: number
  timed_out: number
  expired: number
}

export interface AdminJobPagination {
  limit: number
  offset: number
  total: number
  has_more: boolean
}

export interface AdminJobPage {
  items: AdminJobEntry[]
  pagination: AdminJobPagination
  summary: AdminJobSummary
}

export interface AdminJobFilters {
  state?: AdminJobListState | null
  age_min_seconds?: number | null
  limit?: number
  offset?: number
}

export type AdminJobReconcileOutcome = 'applied' | 'already_terminal' | 'no_change'

export interface AdminJobReconcileRequest {
  reason: string
}

/**
 * Sanitized result of a proof-backed reconcile. The server applies only a
 * fenced terminal transition supported by runtime proof; ambiguous evidence
 * returns `no_change` and releases nothing.
 */
export interface AdminJobReconcileResult {
  job: AdminJobEntry
  applied: boolean
  already_terminal: boolean
  outcome: AdminJobReconcileOutcome
  terminal_state: string | null
  proof_source: string | null
  reason_code: string | null
}

export type AdminJobCancelOutcome =
  'cancelled' | 'cancellation_requested' | 'already_cancelling' | 'already_terminal'

/**
 * Sanitized control-plane cancellation outcome. A queued job becomes terminal
 * immediately; a starting/running job records a stop request and keeps its
 * reservation, volume guard, and credit hold until runtime proof.
 */
export interface AdminJobCancelResult {
  job: AdminJobEntry
  applied: boolean
  already_terminal: boolean
  outcome: AdminJobCancelOutcome
  previous_state: string | null
}
