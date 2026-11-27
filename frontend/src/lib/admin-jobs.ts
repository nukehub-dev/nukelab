// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { ApiError, api } from './api'
import { formatHeartbeatAge } from './admin-operations'
import { formatDate, formatRelativeTime, parseUtcDate } from './utils'
import { PERMISSIONS } from '../stores/auth-store'
import type {
  AdminJobEntry,
  AdminJobFilters,
  AdminJobListState,
  AdminJobPage,
  AdminJobState,
  AdminJobSummary,
} from '../types/admin-jobs'

export const ADMIN_JOB_READ_PERMISSIONS = [
  PERMISSIONS.OPERATIONS_READ_ALL,
  PERMISSIONS.ADMIN_ACCESS,
] as const

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
}

/** The admin jobs view is strictly read-only; no manage permission exists. */
export function adminJobAccess(
  hasAllPermissions: (permissions: string[]) => boolean
): AdminJobAccess {
  return {
    canRead: hasAllPermissions([...ADMIN_JOB_READ_PERMISSIONS]),
  }
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
    // No runtime finalizer exists for jobs in this release.
    can_reconcile: false,
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

export function fetchAdminJobs(filters: AdminJobFilters = {}): Promise<AdminJobPage> {
  return api.get<AdminJobPage>(adminJobsPath(filters)).then((page) => sanitizeAdminJobPage(page))
}

export interface AdminJobErrorInfo {
  code: string | null
  message: string
}

function jobErrorStatus(error: unknown): number {
  return error instanceof ApiError ? error.status : 0
}

function jobErrorCode(error: unknown): string | null {
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
