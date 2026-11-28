// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { ApiError, api } from './api'
import { formatHeartbeatAge } from './admin-operations'
import { formatDate, formatRelativeTime, parseUtcDate } from './utils'
import { PERMISSIONS } from '../stores/auth-store'
import type {
  AdminJobCancelOutcome,
  AdminJobCancelResult,
  AdminJobEntry,
  AdminJobFilters,
  AdminJobListState,
  AdminJobPage,
  AdminJobReconcileOutcome,
  AdminJobReconcileResult,
  AdminJobState,
  AdminJobSummary,
} from '../types/admin-jobs'

/** Admin access is required; one cross-owner job read grant is also required. */
export const ADMIN_JOB_READ_ANY_PERMISSIONS = [
  PERMISSIONS.JOBS_READ_ALL,
  PERMISSIONS.JOBS_ACCESS_OTHERS,
  PERMISSIONS.OPERATIONS_READ_ALL,
] as const

/** One cross-owner job manage grant is required for cancel or reconcile. */
export const ADMIN_JOB_MANAGE_ANY_PERMISSIONS = [
  PERMISSIONS.JOBS_WRITE_ALL,
  PERMISSIONS.OPERATIONS_MANAGE_ALL,
] as const

export const ADMIN_JOB_REASON_MIN_LENGTH = 8
export const ADMIN_JOB_REASON_MAX_LENGTH = 500

export const ADMIN_JOB_STATES: readonly AdminJobState[] = [
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

export const ADMIN_JOB_ACTIVE_STATES: readonly AdminJobState[] = [
  'queued',
  'starting',
  'running',
  'cancelling',
  'recovery_required',
]

export const ADMIN_JOB_LIST_STATES: readonly AdminJobListState[] = ['active', 'history', 'all']

export const ADMIN_JOB_AGE_OPTIONS = [
  { value: 'all', label: 'Any age', seconds: null },
  { value: '1h', label: 'At least 1 hour old', seconds: 3600 },
  { value: '6h', label: 'At least 6 hours old', seconds: 21600 },
  { value: '1d', label: 'At least 1 day old', seconds: 86400 },
  { value: '3d', label: 'At least 3 days old', seconds: 259200 },
  { value: '7d', label: 'At least 7 days old', seconds: 604800 },
] as const

export type AdminJobAgeFilter = (typeof ADMIN_JOB_AGE_OPTIONS)[number]['value']

export interface AdminJobAccess {
  canRead: boolean
  canManage: boolean
}

/**
 * Cross-owner reads need admin access plus one job read grant. Cancel and
 * reconcile need admin access plus one job manage grant; the Jobs-specific
 * grants are primary and the Operations grants remain compatibility fallbacks.
 */
export function adminJobAccess(
  hasAllPermissions: (permissions: string[]) => boolean,
  hasAnyPermission: (permissions: string[]) => boolean
): AdminJobAccess {
  const admin = hasAllPermissions([PERMISSIONS.ADMIN_ACCESS])
  return {
    canRead: admin && hasAnyPermission([...ADMIN_JOB_READ_ANY_PERMISSIONS]),
    canManage: admin && hasAnyPermission([...ADMIN_JOB_MANAGE_ANY_PERMISSIONS]),
  }
}

export function normalizeAdminJobReason(value: string): string {
  return value.trim()
}

/** Reasons are trimmed, bounded, and never blank before they reach the API. */
export function adminJobReasonValidationError(value: string): string | null {
  const reason = normalizeAdminJobReason(value)
  if (!reason) return 'Enter a reason.'
  if (Array.from(reason).length < ADMIN_JOB_REASON_MIN_LENGTH) {
    return `Reason must be at least ${ADMIN_JOB_REASON_MIN_LENGTH} characters.`
  }
  if (Array.from(reason).length > ADMIN_JOB_REASON_MAX_LENGTH) {
    return `Reason must be ${ADMIN_JOB_REASON_MAX_LENGTH} characters or fewer.`
  }
  if (
    Array.from(reason).some((character) => {
      const code = character.codePointAt(0) ?? 0
      return code < 32 || code === 127
    })
  ) {
    return 'Reason must not contain control characters.'
  }
  return null
}

export function canSubmitAdminJobReason(reason: string, busy: boolean): boolean {
  return !busy && adminJobReasonValidationError(reason) === null
}

export type AdminJobStatusTone =
  'pending' | 'warning' | 'running' | 'error' | 'stopped' | 'info' | 'healthy' | 'unknown'

export interface AdminJobPresentation {
  tone: AdminJobStatusTone
  label: string
}

const STATE_LABELS: Record<AdminJobState, string> = {
  queued: 'Queued',
  starting: 'Starting',
  running: 'Running',
  cancelling: 'Cancelling',
  recovery_required: 'Recovery required',
  succeeded: 'Succeeded',
  failed: 'Failed',
  cancelled: 'Cancelled',
  timed_out: 'Timed out',
  expired: 'Expired',
}

const STATE_TONES: Record<AdminJobState, AdminJobStatusTone> = {
  queued: 'pending',
  starting: 'warning',
  running: 'running',
  cancelling: 'warning',
  recovery_required: 'warning',
  succeeded: 'healthy',
  failed: 'error',
  cancelled: 'stopped',
  timed_out: 'error',
  expired: 'stopped',
}

const SAFE_CODE = /^[a-z][a-z0-9_]{0,99}$/
const SAFE_REFERENCE =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/
const MAX_AGE_SECONDS = 365 * 24 * 60 * 60

function humanizeCode(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function isAdminJobState(value: unknown): value is AdminJobState {
  return typeof value === 'string' && (ADMIN_JOB_STATES as readonly string[]).includes(value)
}

export function safeAdminJobCode(value: unknown): string | null {
  return typeof value === 'string' && SAFE_CODE.test(value) ? value : null
}

export function isAdminJobReference(value: unknown): value is string {
  return typeof value === 'string' && SAFE_REFERENCE.test(value)
}

export function shortAdminJobReference(value: unknown): string {
  return isAdminJobReference(value) ? value.slice(0, 8) : 'Unknown'
}

function safeAdminJobText(value: unknown, maximumLength = 120): string | null {
  if (typeof value !== 'string') return null
  const cleaned = Array.from(value)
    .filter((character) => {
      const code = character.codePointAt(0) ?? 0
      return code >= 32 && code !== 127
    })
    .join('')
    .trim()
  if (!cleaned) return null
  return Array.from(cleaned).slice(0, maximumLength).join('')
}

function safeAdminJobUsername(value: unknown): string | null {
  const username = safeAdminJobText(value, 64)
  if (!username) return null
  return username.replace(/^@+/, '') || null
}

export function adminJobStatePresentation(state: unknown): AdminJobPresentation {
  if (!isAdminJobState(state)) return { tone: 'info', label: 'Unknown' }
  return { tone: STATE_TONES[state], label: STATE_LABELS[state] }
}

export function isAdminJobActive(state: unknown): boolean {
  return isAdminJobState(state) && (ADMIN_JOB_ACTIVE_STATES as readonly string[]).includes(state)
}

export function isAdminJobRecoveryRequired(state: unknown): boolean {
  return state === 'recovery_required'
}

/** Only bounded machine-readable reason codes are ever rendered as labels. */
export function adminJobReasonPresentation(reasonCode: unknown): AdminJobPresentation | null {
  const code = safeAdminJobCode(reasonCode)
  if (!code) return null
  if (code === 'recovery_required') {
    return { tone: 'warning', label: 'Operator verification required' }
  }
  if (code === 'cancellation_requested') {
    return { tone: 'warning', label: 'Cancellation requested' }
  }
  if (code === 'waiting_capacity') {
    return { tone: 'info', label: 'Waiting for capacity' }
  }
  if (code === 'volume_busy') {
    return { tone: 'info', label: 'Volume busy' }
  }
  if (code === 'runtime_unverifiable') {
    return { tone: 'warning', label: 'Runtime unverifiable' }
  }
  return { tone: 'info', label: humanizeCode(code) }
}

/** Owner names are display-only; IDs remain the API identity. */
export function adminJobOwnerLabel(
  entry: Pick<AdminJobEntry, 'owner_id' | 'owner_username'>
): string {
  const username = safeAdminJobUsername(entry.owner_username)
  return username ? `@${username}` : shortAdminJobReference(entry.owner_id)
}

export function adminJobOwnerName(
  entry: Pick<AdminJobEntry, 'owner_username' | 'owner_display_name'>
): string | null {
  return safeAdminJobText(entry.owner_display_name) ?? safeAdminJobUsername(entry.owner_username)
}

export function adminJobEnvironmentLabel(
  entry: Pick<AdminJobEntry, 'environment_name' | 'environment_display_label'>
): string {
  return (
    safeAdminJobText(entry.environment_display_label) ??
    safeAdminJobText(entry.environment_name) ??
    'Environment unavailable'
  )
}

export function adminJobPlanLabel(entry: Pick<AdminJobEntry, 'plan_name'>): string {
  return safeAdminJobText(entry.plan_name) ?? 'Plan unavailable'
}

export function adminJobVolumeLabel(entry: Pick<AdminJobEntry, 'volume_display_name'>): string {
  return safeAdminJobText(entry.volume_display_name) ?? 'Volume unavailable'
}

export function adminJobLogStateLabel(value: unknown): string {
  const code = safeAdminJobCode(value)
  if (!code) return 'Unknown'
  const labels: Record<string, string> = {
    pending: 'Pending',
    available: 'Available',
    truncated: 'Truncated',
    unavailable: 'Unavailable',
    expired: 'Expired',
  }
  return labels[code] ?? humanizeCode(code)
}

export function adminJobCleanupStateLabel(value: unknown): string {
  const code = safeAdminJobCode(value)
  if (!code) return 'Unknown'
  const labels: Record<string, string> = {
    pending: 'Pending',
    in_progress: 'In progress',
    succeeded: 'Succeeded',
    failed: 'Failed',
    not_required: 'Not required',
  }
  return labels[code] ?? humanizeCode(code)
}

const PROOF_SOURCE_LABELS: Record<string, string> = {
  executor_absent: 'Executor absent',
  executor_exited: 'Executor exited',
  runtime_absent: 'Runtime absent',
  runtime_exited: 'Runtime exited',
  labels_verified: 'Runtime labels verified',
  exit_evidence: 'Exit evidence verified',
  none: 'No proof source',
}

export function adminJobProofSourceLabel(value: unknown): string {
  const code = safeAdminJobCode(value)
  if (!code) return 'Not reported'
  return PROOF_SOURCE_LABELS[code] ?? humanizeCode(code)
}

export function adminJobHeartbeatLabel(seconds: unknown): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return 'No heartbeat'
  return formatHeartbeatAge(seconds)
}

export function adminJobCreatedLabel(value: string | null | undefined): string {
  const timestamp = safeTimestamp(value)
  return timestamp ? formatRelativeTime(timestamp) : '—'
}

export function adminJobTimestampLabel(value: string | null | undefined): string {
  const timestamp = safeTimestamp(value)
  return timestamp ? formatDate(timestamp) : '—'
}

function safeTimestamp(value: unknown): string | null {
  if (typeof value !== 'string' || !value) return null
  const parsed = parseUtcDate(value)
  return Number.isFinite(parsed.getTime()) ? value : null
}

function boundedInteger(value: unknown, minimum: number, maximum: number): number | null {
  if (typeof value !== 'number' || !Number.isInteger(value)) return null
  if (value < minimum || value > maximum) return null
  return value
}

function boundedCount(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0
  return Math.min(1_000_000_000, Math.max(0, Math.floor(value)))
}

export function emptyAdminJobSummary(): AdminJobSummary {
  return {
    total: 0,
    queued: 0,
    starting: 0,
    running: 0,
    cancelling: 0,
    recovery_required: 0,
    succeeded: 0,
    failed: 0,
    cancelled: 0,
    timed_out: 0,
    expired: 0,
  }
}

export function sanitizeAdminJobSummary(value: unknown): AdminJobSummary {
  const summary =
    value !== null && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {}
  return {
    total: boundedCount(summary.total),
    queued: boundedCount(summary.queued),
    starting: boundedCount(summary.starting),
    running: boundedCount(summary.running),
    cancelling: boundedCount(summary.cancelling),
    recovery_required: boundedCount(summary.recovery_required),
    succeeded: boundedCount(summary.succeeded),
    failed: boundedCount(summary.failed),
    cancelled: boundedCount(summary.cancelled),
    timed_out: boundedCount(summary.timed_out),
    expired: boundedCount(summary.expired),
  }
}

/**
 * Normalizes one server-returned row before rendering. The API already strips
 * payloads, logs, environment values, and runtime identity; this keeps the UI
 * resilient to malformed fields without ever inventing metadata.
 */
export function sanitizeAdminJobEntry(entry: AdminJobEntry): AdminJobEntry {
  return {
    id: isAdminJobReference(entry.id) ? entry.id : '',
    state: isAdminJobState(entry.state) ? entry.state : 'unknown',
    reason_code: safeAdminJobCode(entry.reason_code),
    owner_id: isAdminJobReference(entry.owner_id) ? entry.owner_id : '',
    owner_username: safeAdminJobUsername(entry.owner_username),
    owner_display_name: safeAdminJobText(entry.owner_display_name),
    environment_name: safeAdminJobText(entry.environment_name),
    environment_display_label: safeAdminJobText(entry.environment_display_label),
    plan_name: safeAdminJobText(entry.plan_name),
    volume_display_name: safeAdminJobText(entry.volume_display_name),
    created_at: safeTimestamp(entry.created_at),
    updated_at: safeTimestamp(entry.updated_at),
    finished_at: safeTimestamp(entry.finished_at),
    reservation_active: entry.reservation_active === true,
    guard_active: entry.guard_active === true,
    heartbeat_age_seconds: boundedInteger(entry.heartbeat_age_seconds, 0, 2_000_000_000),
    log_state: safeAdminJobCode(entry.log_state) ?? 'unknown',
    cleanup_state: safeAdminJobCode(entry.cleanup_state) ?? 'unknown',
    cleanup_attempts: boundedInteger(entry.cleanup_attempts, 0, 2_000_000_000) ?? 0,
    // Preserve the server's proof-backed action flags, but never for a row with
    // an invalid reference that cannot address the action endpoint.
    can_reconcile: isAdminJobReference(entry.id) && entry.can_reconcile === true,
    can_cancel: isAdminJobReference(entry.id) && entry.can_cancel === true,
  }
}

export function sanitizeAdminJobPage(page: AdminJobPage): AdminJobPage {
  const pagination = page?.pagination
  return {
    items: Array.isArray(page?.items) ? page.items.map(sanitizeAdminJobEntry) : [],
    summary: sanitizeAdminJobSummary(page?.summary),
    pagination: {
      limit: boundedInteger(pagination?.limit, 1, 100) ?? 50,
      offset: boundedInteger(pagination?.offset, 0, 1000) ?? 0,
      total:
        typeof pagination?.total === 'number' && Number.isFinite(pagination.total)
          ? Math.max(0, Math.floor(pagination.total))
          : 0,
      has_more: pagination?.has_more === true,
    },
  }
}

function clampInteger(
  value: number | undefined,
  fallback: number,
  minimum: number,
  maximum: number
): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback
  return Math.min(maximum, Math.max(minimum, Math.floor(value)))
}

export function isAdminJobListState(value: unknown): value is AdminJobListState {
  return typeof value === 'string' && (ADMIN_JOB_LIST_STATES as readonly string[]).includes(value)
}

export function buildAdminJobsQuery(filters: AdminJobFilters = {}): string {
  const params = new URLSearchParams()
  if (isAdminJobListState(filters.state) && filters.state !== 'all') {
    params.set('state', filters.state)
  }
  if (typeof filters.age_min_seconds === 'number' && Number.isFinite(filters.age_min_seconds)) {
    params.set(
      'age_min_seconds',
      String(clampInteger(filters.age_min_seconds, 0, 0, MAX_AGE_SECONDS))
    )
  }
  params.set('limit', String(clampInteger(filters.limit, 50, 1, 100)))
  params.set('offset', String(clampInteger(filters.offset, 0, 0, 1000)))
  return params.toString()
}

export function adminJobsPath(filters: AdminJobFilters = {}): string {
  return `/admin/jobs?${buildAdminJobsQuery(filters)}`
}

export function adminJobReconcilePath(id: string): string {
  return `/admin/jobs/${encodeURIComponent(id)}/reconcile`
}

export function adminJobCancelPath(id: string): string {
  return `/admin/jobs/${encodeURIComponent(id)}/cancel`
}

export function fetchAdminJobs(filters: AdminJobFilters = {}): Promise<AdminJobPage> {
  return api.get<AdminJobPage>(adminJobsPath(filters)).then((page) => sanitizeAdminJobPage(page))
}

export interface AdminJobErrorInfo {
  code: string | null
  message: string
}

export type AdminJobReconcileErrorInfo = AdminJobErrorInfo

export class AdminJobReconcileRequestError extends Error {
  readonly status: number
  readonly code: string | null

  constructor(message: string, status: number, code: string | null) {
    super(message)
    this.name = 'AdminJobReconcileRequestError'
    this.status = status
    this.code = code
  }
}

export class AdminJobCancelRequestError extends Error {
  readonly status: number
  readonly code: string | null

  constructor(message: string, status: number, code: string | null) {
    super(message)
    this.name = 'AdminJobCancelRequestError'
    this.status = status
    this.code = code
  }
}

function jobErrorStatus(error: unknown): number {
  if (
    error instanceof AdminJobReconcileRequestError ||
    error instanceof AdminJobCancelRequestError
  ) {
    return error.status
  }
  return error instanceof ApiError ? error.status : 0
}

function jobErrorCode(error: unknown): string | null {
  if (
    error instanceof AdminJobReconcileRequestError ||
    error instanceof AdminJobCancelRequestError
  ) {
    return error.code
  }
  if (error instanceof ApiError) return error.code ?? null
  if (error && typeof error === 'object' && 'code' in error) {
    const value = (error as { code?: unknown }).code
    return typeof value === 'string' ? value : null
  }
  return null
}

export function adminJobsLoadErrorInfo(error: unknown): AdminJobErrorInfo {
  const code = jobErrorCode(error)
  const status = jobErrorStatus(error)
  if (code === 'permission_denied' || code === 'permission_revoked' || status === 403) {
    return {
      code,
      message: 'You do not have permission to view batch jobs.',
    }
  }
  if (status === 404) {
    return {
      code,
      message: 'Admin job visibility is not available on this deployment.',
    }
  }
  if (status === 503) {
    return {
      code,
      message: 'Job visibility is temporarily unavailable. Try again later.',
    }
  }
  if (status === 401) {
    return { code, message: 'Your session expired. Sign in again.' }
  }
  return {
    code,
    message: 'Could not load batch jobs. Try again.',
  }
}

const RECONCILE_OUTCOMES: readonly AdminJobReconcileOutcome[] = [
  'applied',
  'already_terminal',
  'no_change',
]

function isAdminJobReconcileOutcome(value: unknown): value is AdminJobReconcileOutcome {
  return typeof value === 'string' && (RECONCILE_OUTCOMES as readonly string[]).includes(value)
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function invalidReconcileResponse(): AdminJobReconcileRequestError {
  return new AdminJobReconcileRequestError(
    'The server returned an unexpected response. Refresh before retrying.',
    200,
    'invalid_response'
  )
}

/**
 * Normalizes the reconcile response before it reaches UI state. The server
 * already strips argv, logs, environment values, and runtime identity; this
 * keeps the dialog and result banner bounded even if the payload drifts.
 */
export function sanitizeAdminJobReconcileResult(value: unknown): AdminJobReconcileResult {
  const record = asRecord(value)
  const job = asRecord(record?.job)
  if (!record || !job) throw invalidReconcileResponse()

  const applied = record.applied === true
  const alreadyTerminal = record.already_terminal === true
  const outcome = isAdminJobReconcileOutcome(record.outcome)
    ? record.outcome
    : applied
      ? 'applied'
      : alreadyTerminal
        ? 'already_terminal'
        : 'no_change'

  return {
    job: sanitizeAdminJobEntry(job as unknown as AdminJobEntry),
    applied,
    already_terminal: alreadyTerminal,
    outcome,
    terminal_state: safeAdminJobCode(record.terminal_state),
    proof_source: safeAdminJobCode(record.proof_source),
    reason_code: safeAdminJobCode(record.reason_code),
  }
}

export function adminJobReconcileErrorMessage(code: string | null, status: number): string {
  switch (code) {
    case 'proof_insufficient':
      return 'Proof is still insufficient. No job state, reservation, or volume guard was changed.'
    case 'job_not_reconcilable':
      return 'This job is already terminal or no longer reconcilable. Refresh the list to see its current state.'
    case 'job_not_found':
      return 'The job no longer exists. Refresh the list and try again.'
    case 'permission_denied':
    case 'permission_revoked':
      return 'You do not have permission to reconcile this job.'
    case 'invalid_reason':
      return `Enter a reason between ${ADMIN_JOB_REASON_MIN_LENGTH} and ${ADMIN_JOB_REASON_MAX_LENGTH} characters without control characters.`
    case 'invalid_job_reference':
      return 'This job reference is invalid. Refresh the list and try again.'
    case 'invalid_response':
      return 'The server returned an unexpected response. Refresh before retrying.'
    default:
      break
  }
  if (status === 404) return 'The job no longer exists. Refresh the list and try again.'
  if (status === 403) return 'You do not have permission to reconcile this job.'
  if (status === 422) {
    return `Enter a reason between ${ADMIN_JOB_REASON_MIN_LENGTH} and ${ADMIN_JOB_REASON_MAX_LENGTH} characters without control characters.`
  }
  if (status === 503) {
    return 'Job proof inspection is temporarily unavailable. Try again later. No change was made.'
  }
  if (status === 401) return 'Your session expired. Sign in again.'
  if (status >= 500) return 'The server could not complete the request. No change was confirmed.'
  if (status === 0) return 'The request could not reach the server. No change was confirmed.'
  return 'The request failed. No change was confirmed.'
}

export function adminJobReconcileErrorInfo(error: unknown): AdminJobReconcileErrorInfo {
  const code = jobErrorCode(error)
  const status = jobErrorStatus(error)
  return { code, message: adminJobReconcileErrorMessage(code, status) }
}

/**
 * Submits a bounded reason and returns only the sanitized proof outcome.
 * Validation and API failures are converted to a sanitized error so raw
 * server payloads never reach the dialog.
 */
export async function reconcileAdminJob(
  id: string,
  reason: string
): Promise<AdminJobReconcileResult> {
  if (!isAdminJobReference(id)) {
    throw new AdminJobReconcileRequestError(
      'This job reference is invalid. Refresh the list and try again.',
      422,
      'invalid_job_reference'
    )
  }
  const normalized = normalizeAdminJobReason(reason)
  const validation = adminJobReasonValidationError(normalized)
  if (validation) {
    throw new AdminJobReconcileRequestError(validation, 422, 'invalid_reason')
  }

  try {
    const body = await api.post<unknown>(adminJobReconcilePath(id), { reason: normalized })
    return sanitizeAdminJobReconcileResult(body)
  } catch (error) {
    if (error instanceof AdminJobReconcileRequestError) throw error
    const code = jobErrorCode(error)
    const status = jobErrorStatus(error)
    throw new AdminJobReconcileRequestError(
      adminJobReconcileErrorMessage(code, status),
      status,
      code
    )
  }
}

const CANCEL_OUTCOMES: readonly AdminJobCancelOutcome[] = [
  'cancelled',
  'cancellation_requested',
  'already_cancelling',
  'already_terminal',
]

function isAdminJobCancelOutcome(value: unknown): value is AdminJobCancelOutcome {
  return typeof value === 'string' && (CANCEL_OUTCOMES as readonly string[]).includes(value)
}

function invalidCancelResponse(): AdminJobCancelRequestError {
  return new AdminJobCancelRequestError(
    'The server returned an unexpected response. Refresh before retrying.',
    200,
    'invalid_response'
  )
}

/**
 * Normalizes a cancellation result before it reaches UI state. The server
 * already strips argv, logs, environment values, and runtime identity; this
 * keeps the dialog and result banner bounded even if the payload drifts.
 */
export function sanitizeAdminJobCancelResult(value: unknown): AdminJobCancelResult {
  const record = asRecord(value)
  const job = asRecord(record?.job)
  if (!record || !job || !isAdminJobCancelOutcome(record.outcome)) {
    throw invalidCancelResponse()
  }

  const outcome = record.outcome
  const applied = record.applied === true
  const alreadyTerminal = record.already_terminal === true

  return {
    job: sanitizeAdminJobEntry(job as unknown as AdminJobEntry),
    applied,
    already_terminal: alreadyTerminal,
    outcome,
    previous_state: safeAdminJobCode(record.previous_state),
  }
}

export function adminJobCancelErrorMessage(code: string | null, status: number): string {
  switch (code) {
    case 'job_not_cancellable':
      return 'This job is recovery-only or past the point where cancellation can be requested. Use proof-backed reconcile; no reservation, volume guard, or credit hold was released.'
    case 'job_not_found':
      return 'The job no longer exists. Refresh the list and try again.'
    case 'permission_denied':
    case 'permission_revoked':
      return 'You do not have permission to cancel this job.'
    case 'invalid_reason':
      return `Enter a reason between ${ADMIN_JOB_REASON_MIN_LENGTH} and ${ADMIN_JOB_REASON_MAX_LENGTH} characters without control characters.`
    case 'invalid_job_reference':
      return 'This job reference is invalid. Refresh the list and try again.'
    case 'invalid_response':
      return 'The server returned an unexpected response. Refresh before retrying.'
    case 'audit_unavailable':
      return 'The audit trail is unavailable, so no cancellation was applied. Try again later.'
    case 'cancellation_failed':
      return 'The cancellation request could not be completed. Refresh before retrying.'
    default:
      break
  }
  if (status === 404) return 'The job no longer exists. Refresh the list and try again.'
  if (status === 403) return 'You do not have permission to cancel this job.'
  if (status === 409) {
    return 'This job is recovery-only or no longer cancellable. No reservation or volume guard was released.'
  }
  if (status === 422) {
    return `Enter a reason between ${ADMIN_JOB_REASON_MIN_LENGTH} and ${ADMIN_JOB_REASON_MAX_LENGTH} characters without control characters.`
  }
  if (status === 401) return 'Your session expired. Sign in again.'
  if (status >= 500) return 'The server could not complete the request. No change was confirmed.'
  if (status === 0) return 'The request could not reach the server. No change was confirmed.'
  return 'The request failed. No change was confirmed.'
}

export function adminJobCancelErrorInfo(error: unknown): AdminJobErrorInfo {
  const code = jobErrorCode(error)
  const status = jobErrorStatus(error)
  return { code, message: adminJobCancelErrorMessage(code, status) }
}

/**
 * Submits a bounded reason and returns only the sanitized cancellation
 * outcome. Validation and API failures are converted to a sanitized error so
 * raw server payloads never reach the dialog.
 */
export async function cancelAdminJob(id: string, reason: string): Promise<AdminJobCancelResult> {
  if (!isAdminJobReference(id)) {
    throw new AdminJobCancelRequestError(
      'This job reference is invalid. Refresh the list and try again.',
      422,
      'invalid_job_reference'
    )
  }
  const normalized = normalizeAdminJobReason(reason)
  const validation = adminJobReasonValidationError(normalized)
  if (validation) {
    throw new AdminJobCancelRequestError(validation, 422, 'invalid_reason')
  }

  try {
    const body = await api.post<unknown>(adminJobCancelPath(id), { reason: normalized })
    return sanitizeAdminJobCancelResult(body)
  } catch (error) {
    if (error instanceof AdminJobCancelRequestError) throw error
    const code = jobErrorCode(error)
    const status = jobErrorStatus(error)
    throw new AdminJobCancelRequestError(adminJobCancelErrorMessage(code, status), status, code)
  }
}
