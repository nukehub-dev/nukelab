// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { ApiError, api } from './api'
import { formatDate, formatRelativeTime, parseUtcDate } from './utils'
import { PERMISSIONS } from '../stores/auth-store'
import type {
  AdminQueueEntry,
  AdminQueueFilters,
  AdminQueuePage,
  AdminQueueResources,
  AdminQueueStatus,
  AdminQueueSummary,
} from '../types/admin-queue'

export const ADMIN_QUEUE_READ_PERMISSIONS = [
  PERMISSIONS.SERVERS_READ_ALL,
  PERMISSIONS.ADMIN_ACCESS,
] as const

/** Owner labels come from the user directory, so the picker needs this grant. */
export const ADMIN_QUEUE_OWNER_PICKER_PERMISSION = PERMISSIONS.USERS_READ
export const ADMIN_QUEUE_ANY_OWNER_LABEL = 'Any owner'

export interface AdminQueueAccess {
  canRead: boolean
}

/** The admin queue is strictly read-only: no manage permission exists. */
export function adminQueueAccess(
  hasAllPermissions: (permissions: string[]) => boolean
): AdminQueueAccess {
  return {
    canRead: hasAllPermissions([...ADMIN_QUEUE_READ_PERMISSIONS]),
  }
}

export const ADMIN_QUEUE_STATUSES: readonly AdminQueueStatus[] = [
  'pending',
  'scheduled',
  'starting',
  'started',
  'failed',
  'cancelled',
]

export const ADMIN_QUEUE_RECOVERY_REASON = 'recovery_required'

const STATUS_LABELS: Record<AdminQueueStatus, string> = {
  pending: 'Pending',
  scheduled: 'Scheduled',
  starting: 'Starting',
  started: 'Started',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

export type QueueStatusTone = 'pending' | 'warning' | 'running' | 'error' | 'stopped' | 'info'

export interface QueueStatusPresentation {
  tone: QueueStatusTone
  label: string
}

export function isQueueStatus(value: unknown): value is AdminQueueStatus {
  return typeof value === 'string' && (ADMIN_QUEUE_STATUSES as readonly string[]).includes(value)
}

export function queueStatusLabel(status: string | null | undefined): string {
  return isQueueStatus(status) ? STATUS_LABELS[status] : 'Unknown'
}

/** Maps a queue status to the shared status-badge vocabulary. */
export function queueStatusPresentation(
  status: string | null | undefined
): QueueStatusPresentation {
  if (!isQueueStatus(status)) return { tone: 'info', label: 'Unknown' }
  switch (status) {
    case 'pending':
      return { tone: 'pending', label: STATUS_LABELS[status] }
    case 'scheduled':
      return { tone: 'info', label: STATUS_LABELS[status] }
    case 'starting':
      return { tone: 'warning', label: STATUS_LABELS[status] }
    case 'started':
      return { tone: 'running', label: STATUS_LABELS[status] }
    case 'failed':
      return { tone: 'error', label: STATUS_LABELS[status] }
    case 'cancelled':
      return { tone: 'stopped', label: STATUS_LABELS[status] }
  }
}

const SAFE_CODE = /^[a-z][a-z0-9_]{0,63}$/
const SAFE_REFERENCE =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/

export function safeQueueReasonCode(value: unknown): string | null {
  return typeof value === 'string' && SAFE_CODE.test(value) ? value : null
}

export function isQueueRecoveryRequired(reasonCode: unknown): boolean {
  return safeQueueReasonCode(reasonCode) === ADMIN_QUEUE_RECOVERY_REASON
}

function humanizeCode(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

/** Only bounded machine-readable reason codes are ever rendered as labels. */
export function queueReasonPresentation(reasonCode: unknown): QueueStatusPresentation | null {
  const code = safeQueueReasonCode(reasonCode)
  if (!code) return null
  if (code === ADMIN_QUEUE_RECOVERY_REASON) {
    return { tone: 'warning', label: 'Recovery required' }
  }
  return { tone: 'info', label: humanizeCode(code) }
}

export function isQueueReference(value: unknown): value is string {
  return typeof value === 'string' && SAFE_REFERENCE.test(value)
}

/** Short, non-linkable references keep owner/server metadata bounded. */
export function shortQueueReference(value: unknown): string {
  return isQueueReference(value) ? value.slice(0, 8) : 'Unknown'
}

function safeQueueDisplayText(value: unknown, maximumLength = 120): string | null {
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

function safeQueueUsername(value: unknown): string | null {
  const username = safeQueueDisplayText(value, 64)
  if (!username) return null
  return username.replace(/^@+/, '') || null
}

export function safeQueueServerName(value: unknown): string {
  return safeQueueDisplayText(value) ?? 'Unnamed request'
}

/** Owner names are display-only; IDs remain the filter and API identity. */
export function queueOwnerLabel(
  entry: Pick<AdminQueueEntry, 'owner_id' | 'owner_username'>
): string {
  const username = safeQueueUsername(entry.owner_username)
  return username ? `@${username}` : shortQueueReference(entry.owner_id)
}

export function queuePlanLabel(entry: Pick<AdminQueueEntry, 'plan_id' | 'plan_name'>): string {
  return safeQueueDisplayText(entry.plan_name) ?? shortQueueReference(entry.plan_id)
}

export function queueEnvironmentLabel(
  entry: Pick<AdminQueueEntry, 'environment_id' | 'environment_name'>
): string {
  return safeQueueDisplayText(entry.environment_name) ?? shortQueueReference(entry.environment_id)
}

export interface AdminQueueOwnerCandidate {
  id: string
  username?: string | null
  display_name?: string | null
  avatar_url?: string | null
}

export interface AdminQueueOwnerOption {
  value: string
  label: string
  image?: string
}

function safeAvatarUrl(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed && trimmed.length <= 2048 ? trimmed : undefined
}

/** Formats one directory user as `Display Name (@username)`. */
export function queueOwnerOptionLabel(candidate: AdminQueueOwnerCandidate): string | null {
  const username = safeQueueUsername(candidate.username)
  const display = safeQueueDisplayText(candidate.display_name, 120) ?? username
  if (!display) return null
  return username ? `${display} (@${username})` : display
}

/**
 * Builds bounded owner-picker options. Only UUID values can reach the queue
 * filter, so directory rows without a valid user ID are omitted.
 */
export function queueOwnerOptions(
  candidates: readonly AdminQueueOwnerCandidate[]
): AdminQueueOwnerOption[] {
  const options: AdminQueueOwnerOption[] = [{ value: '', label: ADMIN_QUEUE_ANY_OWNER_LABEL }]
  for (const candidate of candidates) {
    if (!isQueueReference(candidate.id)) continue
    const label = queueOwnerOptionLabel(candidate)
    if (!label) continue
    const image = safeAvatarUrl(candidate.avatar_url)
    options.push(image ? { value: candidate.id, label, image } : { value: candidate.id, label })
  }
  return options
}

export function adminQueueOwnerPickerAllowed(
  hasPermission: (permission: string) => boolean
): boolean {
  return hasPermission(ADMIN_QUEUE_OWNER_PICKER_PERMISSION)
}

/** Keeps owner filtering UUID-only for both the picker and the manual input. */
export function queueOwnerFilterValue(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed && isQueueReference(trimmed) ? trimmed : null
}

function boundedCount(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0
  return Math.min(1_000_000_000, Math.max(0, Math.floor(value)))
}

function boundedResourceNumber(value: unknown, maximum: number): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0
  return Math.min(maximum, Math.max(0, value))
}

export function emptyQueueSummary(): AdminQueueSummary {
  return {
    total: 0,
    pending: 0,
    scheduled: 0,
    starting: 0,
    started: 0,
    failed: 0,
    cancelled: 0,
    recovery_required: 0,
  }
}

export function sanitizeQueueSummary(value: unknown): AdminQueueSummary {
  const summary =
    value !== null && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {}
  return {
    total: boundedCount(summary.total),
    pending: boundedCount(summary.pending),
    scheduled: boundedCount(summary.scheduled),
    starting: boundedCount(summary.starting),
    started: boundedCount(summary.started),
    failed: boundedCount(summary.failed),
    cancelled: boundedCount(summary.cancelled),
    recovery_required: boundedCount(summary.recovery_required),
  }
}

export function sanitizeQueueResources(value: unknown): AdminQueueResources {
  const resources =
    value !== null && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {}
  return {
    cpu: boundedResourceNumber(resources.cpu, 1024),
    memory_mib: boundedInteger(resources.memory_mib, 0, 100_000_000) ?? 0,
    disk_mib: boundedInteger(resources.disk_mib, 0, 100_000_000) ?? 0,
    gpu_count: boundedInteger(resources.gpu_count, 0, 1024) ?? 0,
  }
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

/**
 * Normalizes one server-returned row before rendering. The API already strips
 * payloads, tokens and raw text; this keeps the UI resilient to malformed
 * fields without ever inventing metadata.
 */
export function sanitizeQueueEntry(entry: AdminQueueEntry): AdminQueueEntry {
  const position = boundedInteger(entry.position, 1, 1_000_000)
  return {
    id: typeof entry.id === 'string' ? entry.id : '',
    owner_id: typeof entry.owner_id === 'string' ? entry.owner_id : '',
    owner_username: safeQueueUsername(entry.owner_username),
    server_id: typeof entry.server_id === 'string' ? entry.server_id : null,
    server_name: safeQueueServerName(entry.server_name),
    environment_id: typeof entry.environment_id === 'string' ? entry.environment_id : '',
    environment_name: safeQueueDisplayText(entry.environment_name),
    plan_id: typeof entry.plan_id === 'string' ? entry.plan_id : '',
    plan_name: safeQueueDisplayText(entry.plan_name),
    resources: sanitizeQueueResources(entry.resources),
    status: entry.status,
    reason_code: safeQueueReasonCode(entry.reason_code),
    position,
    priority: boundedInteger(entry.priority, 0, 1_000_000) ?? 0,
    requested_at: safeTimestamp(entry.requested_at),
    started_at: safeTimestamp(entry.started_at),
    failed_at: safeTimestamp(entry.failed_at),
    expires_at: safeTimestamp(entry.expires_at),
  }
}

export function sanitizeQueuePage(page: AdminQueuePage): AdminQueuePage {
  const pagination = page?.pagination
  return {
    items: Array.isArray(page?.items) ? page.items.map(sanitizeQueueEntry) : [],
    summary: sanitizeQueueSummary(page?.summary),
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

export function queueTimestampLabel(value: string | null | undefined): string {
  const timestamp = safeTimestamp(value)
  return timestamp ? formatDate(timestamp) : '—'
}

export function queueRelativeTimestampLabel(value: string | null | undefined): string {
  const timestamp = safeTimestamp(value)
  return timestamp ? formatRelativeTime(timestamp) : '—'
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

export function buildAdminQueueQuery(filters: AdminQueueFilters = {}): string {
  const params = new URLSearchParams()
  const statuses = Array.from(new Set(filters.statuses ?? [])).filter(isQueueStatus)
  for (const status of statuses) params.append('status', status)
  if (isQueueReference(filters.owner_id)) params.set('owner_id', filters.owner_id)
  if (typeof filters.age_days === 'number' && Number.isFinite(filters.age_days)) {
    params.set('age_days', String(clampInteger(filters.age_days, 0, 0, 3650)))
  }
  if (filters.older_than && safeTimestamp(filters.older_than)) {
    params.set('older_than', filters.older_than)
  }
  if (filters.recovery_required === true) params.set('recovery_required', 'true')
  else if (filters.recovery_required === false) params.set('recovery_required', 'false')
  params.set('limit', String(clampInteger(filters.limit, 50, 1, 100)))
  params.set('offset', String(clampInteger(filters.offset, 0, 0, 1000)))
  return params.toString()
}

export function adminQueuePath(filters: AdminQueueFilters = {}): string {
  return `/admin/server-queue?${buildAdminQueueQuery(filters)}`
}

export function fetchAdminQueue(filters: AdminQueueFilters = {}): Promise<AdminQueuePage> {
  return api.get<AdminQueuePage>(adminQueuePath(filters)).then((page) => sanitizeQueuePage(page))
}

export interface AdminQueueErrorInfo {
  code: string | null
  message: string
}

function queueErrorStatus(error: unknown): number {
  return error instanceof ApiError ? error.status : 0
}

function queueErrorCode(error: unknown): string | null {
  if (error instanceof ApiError) return error.code ?? null
  if (error && typeof error === 'object' && 'code' in error) {
    const value = (error as { code?: unknown }).code
    return typeof value === 'string' ? value : null
  }
  return null
}

export function adminQueueLoadErrorInfo(error: unknown): AdminQueueErrorInfo {
  const code = queueErrorCode(error)
  const status = queueErrorStatus(error)
  if (code === 'permission_denied' || code === 'permission_revoked' || status === 403) {
    return {
      code,
      message: 'You do not have permission to view the server queue.',
    }
  }
  if (status === 404) {
    return {
      code,
      message: 'Admin queue visibility is not available on this deployment.',
    }
  }
  if (status === 503) {
    return {
      code,
      message: 'Queue visibility is temporarily unavailable. Try again later.',
    }
  }
  if (status === 401) {
    return { code, message: 'Your session expired. Sign in again.' }
  }
  return {
    code,
    message: 'Could not load queue requests. Try again.',
  }
}
