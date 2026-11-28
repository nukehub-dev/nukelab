// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import type {
  CreateJobRequest,
  JobBillingMode,
  JobCapabilities,
  JobFormField,
  JobListFilter,
  JobLogState,
  JobOutcomeCode,
  JobState,
} from '../types/batch-job'

export const JOB_STATES: readonly JobState[] = [
  'queued',
  'starting',
  'running',
  'cancelling',
  'recovery_required',
  'succeeded',
  'failed',
  'cancelled',
  'timed_out',
  'expired',
]

export const JOB_TERMINAL_STATES: readonly JobState[] = [
  'succeeded',
  'failed',
  'cancelled',
  'timed_out',
  'expired',
]

export const JOB_LIST_FILTERS: readonly JobListFilter[] = ['active', 'history', 'all']

const JOB_STATE_LABELS: Record<JobState, string> = {
  queued: 'Queued',
  starting: 'Starting',
  running: 'Running',
  cancelling: 'Cancelling',
  recovery_required: 'Needs review',
  succeeded: 'Succeeded',
  failed: 'Failed',
  cancelled: 'Cancelled',
  timed_out: 'Timed out',
  expired: 'Expired',
}

const JOB_STATE_DESCRIPTIONS: Record<JobState, string> = {
  queued: 'The job is waiting for an eligible execution slot.',
  starting: 'Capacity and the work volume are reserved while the runtime starts.',
  running: 'The job is executing in the approved environment.',
  cancelling: 'A stop was requested. Resources remain held until termination is verified.',
  recovery_required:
    'The recorded outcome could not be verified automatically. An operator must review it before the job can be finalized.',
  succeeded: 'The runtime exited successfully and its result was recorded.',
  failed: 'The job did not complete successfully.',
  cancelled: 'The job was cancelled before it produced a completed result.',
  timed_out: 'The job reached its maximum runtime and was stopped.',
  expired: 'The job waited longer than the queue limit and was never admitted.',
}

const JOB_REASON_COPY: Record<string, string> = {
  waiting_capacity: 'Waiting for available CPU and memory capacity.',
  volume_busy: 'Waiting for the selected work volume to finish another operation.',
  revision_unavailable: 'The selected environment revision is no longer available.',
  plan_changed: 'The selected resource plan changed before the job could start.',
  plan_unavailable: 'The selected resource plan is no longer available.',
  insufficient_credits: 'The account does not have enough credits for this job.',
  quota_exceeded: 'This job exceeds the current resource quota.',
  artifact_missing: 'A required environment image is unavailable.',
  permission_revoked: 'You no longer have permission for this job.',
  cohort_not_allowed: 'Batch jobs are limited to an approved pilot cohort.',
  runtime_unverifiable: 'The runtime outcome could not be verified.',
  job_deadline_exceeded: 'The job reached its maximum runtime and was stopped.',
  queue_expired: 'The job waited past the queue limit and expired before it could start.',
  request_cancelled: 'The job was cancelled before it started.',
  cancellation_requested: 'A stop was requested for this job.',
  recovery_required:
    'The outcome needs operator verification. No retry is available until it is reconciled.',
  feature_disabled: 'Job submission is currently disabled for this account.',
}

const JOB_FORM_FIELDS: readonly JobFormField[] = [
  'name',
  'revision_id',
  'plan_id',
  'volume_id',
  'argv',
  'max_runtime_seconds',
]

const JOB_ERROR_COPY: Record<string, string> = {
  feature_disabled: 'Job submission is currently disabled for this account.',
  permission_denied: 'You no longer have permission to do that.',
  job_not_found: 'This job is unavailable or no longer exists.',
  idempotency_conflict:
    'This submission changed after a previous attempt. Review the form and submit again.',
  invalid_request: 'Review the request fields and try again.',
  argv_too_large: 'The command is too long. Reduce the number of arguments or their size.',
  runtime_too_long: 'Choose a maximum runtime within the allowed limit.',
  revision_unavailable: 'The selected environment revision is no longer available.',
  plan_unavailable: 'The selected resource plan is no longer available.',
  paid_plan_unsupported: 'Paid plans are not supported for batch jobs on this deployment.',
  volume_unavailable: 'The selected work volume is no longer available.',
  volume_busy: 'The selected work volume is busy with another operation.',
  job_limit_reached: 'You already have the maximum number of active or queued jobs.',
  job_not_cancellable: 'This job can no longer be cancelled.',
  runtime_unverifiable: 'The runtime outcome could not be verified.',
  cohort_not_allowed:
    'Batch jobs are limited to an approved pilot cohort. Contact an administrator.',
  quota_exceeded: 'This job exceeds your current resource quota.',
  artifact_missing: 'A required environment image is unavailable.',
  permission_revoked: 'You no longer have permission for this job.',
  queue_expired: 'The job waited past the queue limit and expired before it could start.',
  request_cancelled: 'The job was cancelled before it started.',
  cancellation_requested: 'A stop was requested for this job.',
}

const JOB_ERROR_FIELDS: Record<string, JobFormField> = {
  argv_too_large: 'argv',
  runtime_too_long: 'max_runtime_seconds',
  revision_unavailable: 'revision_id',
  plan_unavailable: 'plan_id',
  paid_plan_unsupported: 'plan_id',
  volume_unavailable: 'volume_id',
  volume_busy: 'volume_id',
}

const JOB_LOG_LABELS: Record<JobLogState, string> = {
  pending: 'Pending',
  available: 'Available',
  truncated: 'Truncated',
  unavailable: 'Unavailable',
  expired: 'Expired',
}

const JOB_LOG_DESCRIPTIONS: Record<JobLogState, string> = {
  pending: 'Logs will appear after the runtime starts producing output.',
  available: 'The retained output tail is available.',
  truncated: 'Only the bounded tail of the output was retained.',
  unavailable: 'Logs could not be captured for this job.',
  expired: 'The log retention window has passed.',
}

const JOB_OUTCOME_LABELS: Record<JobOutcomeCode, string> = {
  succeeded: 'Succeeded',
  failed: 'Failed',
  cancelled: 'Cancelled',
  timed_out: 'Timed out',
  expired: 'Expired',
  runtime_unverifiable: 'Runtime unverifiable',
}

export function isJobState(value: unknown): value is JobState {
  return typeof value === 'string' && (JOB_STATES as readonly string[]).includes(value)
}

export function isJobListFilter(value: unknown): value is JobListFilter {
  return typeof value === 'string' && (JOB_LIST_FILTERS as readonly string[]).includes(value)
}

export function isJobFormField(value: unknown): value is JobFormField {
  return typeof value === 'string' && (JOB_FORM_FIELDS as readonly string[]).includes(value)
}

export function parseJobListSearch(search: Record<string, unknown>): {
  state?: JobListFilter
} {
  return isJobListFilter(search.state) ? { state: search.state } : {}
}

export function isJobTerminal(state: JobState): boolean {
  return JOB_TERMINAL_STATES.includes(state)
}

/**
 * Cheap active-state check for polling. Everything that is not a confirmed
 * terminal state can still change, including recovery_required after an
 * operator reconciles it.
 */
export function isJobActive(state: JobState): boolean {
  return !isJobTerminal(state)
}

export function isJobListActive(items: readonly { state: JobState }[]): boolean {
  return items.some((item) => isJobActive(item.state))
}

export function jobStateLabel(state: JobState): string {
  return JOB_STATE_LABELS[state]
}

export function jobStateDescription(state: JobState): string {
  return JOB_STATE_DESCRIPTIONS[state]
}

export function jobReasonCopy(reasonCode: string | null | undefined): string | null {
  if (!reasonCode) return null
  return JOB_REASON_COPY[reasonCode] ?? null
}

export function jobErrorMessage(code: string | null | undefined, fallback: string): string {
  if (!code) return fallback
  return JOB_ERROR_COPY[code] ?? fallback
}

export function jobErrorField(code: string | null | undefined): JobFormField | null {
  if (!code) return null
  return JOB_ERROR_FIELDS[code] ?? null
}

export function jobFieldLabel(field: JobFormField): string {
  switch (field) {
    case 'name':
      return 'Job name'
    case 'revision_id':
      return 'Environment revision'
    case 'plan_id':
      return 'Resource plan'
    case 'volume_id':
      return 'Work volume'
    case 'argv':
      return 'Command'
    case 'max_runtime_seconds':
      return 'Maximum runtime'
  }
}

export function jobLogStateLabel(state: JobLogState): string {
  return JOB_LOG_LABELS[state]
}

export function jobLogStateDescription(state: JobLogState): string {
  return JOB_LOG_DESCRIPTIONS[state]
}

export function jobOutcomeLabel(outcome: JobOutcomeCode): string {
  return JOB_OUTCOME_LABELS[outcome]
}

export function jobProofLabel(proof: string | null | undefined): string {
  if (proof === 'observed') return 'Observed by the runtime'
  if (!proof) return 'No proof recorded'
  return proof.replaceAll('_', ' ')
}

/**
 * Trust the server flag when present. Older or degraded payloads without the
 * flag still allow the actions the public lifecycle permits.
 */
export function canCancelJob(job: { state: JobState; can_cancel?: boolean | null }): boolean {
  if (typeof job.can_cancel === 'boolean') return job.can_cancel
  return job.state === 'queued' || job.state === 'starting' || job.state === 'running'
}

export function jobPollInterval(
  active: boolean,
  failures: number,
  hidden: boolean
): number | false {
  if (!active || hidden) return false
  return Math.min(60_000, 5_000 * 2 ** Math.min(Math.max(0, failures), 4))
}

/** Parse the argument textarea literally: one argument per line, no shell parsing. */
export function parseJobArgs(text: string): string[] {
  return text.split(/\r\n|\n|\r/).filter((line) => line.trim().length > 0)
}

export function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).length
}

export function argvByteLength(argv: readonly string[]): number {
  return argv.reduce((total, value) => total + utf8ByteLength(value) + 1, 0)
}

export function validateJobArgv(
  argv: readonly string[],
  limits: Pick<JobCapabilities['limits'], 'max_argv_items' | 'max_input_bytes'>
): string | null {
  if (argv.length === 0) return 'Enter one executable or argument per line.'
  if (argv.some((value) => value.includes('\0'))) {
    return 'Arguments cannot contain NUL characters.'
  }
  if (argv.length > limits.max_argv_items) {
    return `Use at most ${limits.max_argv_items} arguments.`
  }
  if (argvByteLength(argv) > limits.max_input_bytes) {
    return 'The command exceeds the allowed input size.'
  }
  return null
}

export function createJobIdempotencyKey(): string {
  const randomUUID = globalThis.crypto?.randomUUID
  if (typeof randomUUID === 'function') return randomUUID.call(globalThis.crypto)
  return `job-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`
}

/** Contract: 1..128 visible ASCII characters. */
export function isValidJobIdempotencyKey(key: string | null | undefined): key is string {
  return typeof key === 'string' && /^[\x21-\x7e]{1,128}$/.test(key)
}

export function jobRequestSignature(request: CreateJobRequest): string {
  return JSON.stringify({
    name: request.name,
    revision_id: request.revision_id,
    plan_id: request.plan_id,
    volume_id: request.volume_id,
    argv: request.argv,
    max_runtime_seconds: request.max_runtime_seconds,
  })
}

export function jobMaximumCost(
  costPerHour: number,
  runtimeSeconds: number,
  billingMode: JobBillingMode
): number {
  if (billingMode === 'zero_cost') return 0
  return Math.max(0, costPerHour) * (Math.max(0, runtimeSeconds) / 3600)
}

export function disabledJobCapabilities(reasonCode = 'feature_disabled'): JobCapabilities {
  return {
    enabled: false,
    can_submit: false,
    billing_mode: 'zero_cost',
    secrets_enabled: false,
    storage_limits_enforced: false,
    storage_enforcement_required: false,
    reason_code: reasonCode,
    limits: {
      max_active_jobs: 1,
      max_queued_jobs: 3,
      default_runtime_seconds: 1800,
      max_runtime_seconds: 7200,
      queue_ttl_seconds: 86400,
      max_argv_items: 64,
      max_input_bytes: 16384,
      log_tail_bytes: 262144,
      log_retention_seconds: 604800,
    },
  }
}
