// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { ApiError, api, refreshAccessToken } from './api'
import { PERMISSIONS } from '../stores/auth-store'
import type {
  AdminOperation,
  AdminOperationFilters,
  AdminOperationKind,
  AdminOperationLiveness,
  AdminOperationPage,
  AdminOperationRecoveryEvidence,
  AdminOperationReconcileResult,
  AdminOperationRuntimeState,
} from '../types/admin-operations'

export const ADMIN_OPERATION_REASON_MAX_LENGTH = 255

export const ADMIN_OPERATION_READ_PERMISSIONS = [
  PERMISSIONS.OPERATIONS_READ_ALL,
  PERMISSIONS.ADMIN_ACCESS,
] as const

export const ADMIN_OPERATION_MANAGE_PERMISSIONS = [
  PERMISSIONS.OPERATIONS_MANAGE_ALL,
  PERMISSIONS.ADMIN_ACCESS,
] as const

const API_BASE = import.meta.env.VITE_API_URL || '/api'
const SAFE_CODE = /^[a-z][a-z0-9_]{0,99}$/
const SAFE_DIAGNOSTIC_VALUE = /^[a-z0-9][a-z0-9_.-]{0,63}$/
const SAFE_REFERENCE = /^[0-9a-fA-F-]{8,64}$/

const LAUNCH_ACTIVE_STATES = new Set(['prepared', 'executing', 'uncertain'])
const VOLUME_ACTIVE_STATES = new Set(['pending', 'in_progress', 'recovery_required'])

const DIAGNOSTIC_LABELS: Record<string, string> = {
  row_state: 'Row state',
  action: 'Action',
  container_count: 'Matching containers',
  health_status: 'Health',
  destination_status: 'Destination status',
  executor_alive: 'Executor alive',
  helper: 'Helper',
  liveness_proof: 'Liveness proof',
}

const PROOF_SOURCE_LABELS: Record<string, string> = {
  runtime_labels: 'Matching runtime labels',
  graceful_marker: 'Graceful shutdown marker',
  helper_artifact: 'Helper completion artifact',
  worker_heartbeat_missing: 'Worker heartbeat missing',
  none: 'No proof source',
}

export interface AdminOperationAccess {
  canRead: boolean
  canManage: boolean
}

export interface AdminOperationStatePresentation {
  status: 'running' | 'stopped' | 'pending' | 'error' | 'warning' | 'info'
  label: string
}

export interface AdminOperationDiagnostic {
  key: string
  label: string
  value: string
}

export interface AdminOperationCounter {
  key: string
  label: string
  value: number
}

export interface AdminOperationErrorInfo {
  code: string | null
  message: string
  recoveryRequired: boolean
  applied: boolean
  evidence: AdminOperationRecoveryEvidence | null
}

/** Mirrors the backend split: reads need read_all, actions need manage_all. */
export function adminOperationAccess(
  hasAllPermissions: (permissions: string[]) => boolean
): AdminOperationAccess {
  return {
    canRead: hasAllPermissions([...ADMIN_OPERATION_READ_PERMISSIONS]),
    canManage: hasAllPermissions([...ADMIN_OPERATION_MANAGE_PERMISSIONS]),
  }
}

export function normalizeOperationReason(value: string): string {
  return value.trim()
}

/** Reasons are trimmed, bounded, and never blank before they reach the API. */
export function operationReasonValidationError(value: string): string | null {
  const reason = normalizeOperationReason(value)
  if (!reason) return 'Enter a reason.'
  if (reason.length > ADMIN_OPERATION_REASON_MAX_LENGTH) {
    return `Reason must be ${ADMIN_OPERATION_REASON_MAX_LENGTH} characters or fewer.`
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

export function canSubmitOperationReason(reason: string, busy: boolean): boolean {
  return !busy && operationReasonValidationError(reason) === null
}

export function adminOperationKindLabel(kind: AdminOperationKind): string {
  switch (kind) {
    case 'launch':
      return 'Launch'
    case 'backup':
      return 'Backup'
    case 'restore':
      return 'Restore'
  }
}

function humanizeCode(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function shortOperationId(value: string | null | undefined): string {
  if (!value || !SAFE_REFERENCE.test(value)) return 'Unknown'
  return value.slice(0, 8)
}

function safeOperationDisplayText(value: unknown, maximumLength = 120): string | null {
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

function safeOperationUsername(value: unknown): string | null {
  const username = safeOperationDisplayText(value, 64)
  if (!username) return null
  return username.replace(/^@+/, '') || null
}

/** Owner names are display-only; the short owner reference stays the fallback. */
export function operationOwnerLabel(
  operation: Pick<AdminOperation, 'owner_id' | 'owner_username'>
): string {
  const username = safeOperationUsername(operation.owner_username)
  return username ? `@${username}` : shortOperationId(operation.owner_id)
}

export function operationTargetName(operation: Pick<AdminOperation, 'target_name'>): string | null {
  return safeOperationDisplayText(operation.target_name)
}

/** Target name is the primary identity; the operation kind is the fallback. */
export function operationTargetLabel(
  operation: Pick<AdminOperation, 'kind' | 'target_name'>
): string {
  return operationTargetName(operation) ?? adminOperationKindLabel(operation.kind)
}

export function operationTargetTypeLabel(targetType: AdminOperation['target_type']): string | null {
  if (targetType === 'server') return 'Server'
  if (targetType === 'volume') return 'Volume'
  return null
}

export function operationActionLabel(action: string | null | undefined): string {
  if (!action || !SAFE_CODE.test(action)) return '—'
  return humanizeCode(action)
}

export function operationReasonCodeLabel(reason: string | null | undefined): string {
  if (!reason || !SAFE_CODE.test(reason)) return 'Not available'
  return reason
}

export function operationStateLabel(state: string | null | undefined): string {
  if (!state || !SAFE_CODE.test(state)) return 'Unknown'
  const labels: Record<string, string> = {
    prepared: 'Prepared',
    executing: 'Executing',
    uncertain: 'Uncertain',
    pending: 'Pending',
    in_progress: 'In progress',
    recovery_required: 'Recovery required',
    succeeded: 'Succeeded',
    completed: 'Completed',
    failed: 'Failed',
    deleting: 'Deleting',
    delete_failed: 'Delete failed',
    deleted: 'Deleted',
  }
  return labels[state] ?? humanizeCode(state)
}

export function operationStatePresentation(
  kind: AdminOperationKind,
  state: string | null | undefined
): AdminOperationStatePresentation {
  if (!state || !SAFE_CODE.test(state)) {
    return { status: 'info', label: 'Unknown' }
  }
  if (kind === 'launch') {
    switch (state) {
      case 'succeeded':
        return { status: 'running', label: operationStateLabel(state) }
      case 'failed':
        return { status: 'error', label: operationStateLabel(state) }
      case 'uncertain':
        return { status: 'warning', label: operationStateLabel(state) }
      case 'prepared':
      case 'executing':
        return { status: 'pending', label: operationStateLabel(state) }
    }
  } else {
    switch (state) {
      case 'completed':
        return { status: 'running', label: operationStateLabel(state) }
      case 'failed':
      case 'delete_failed':
        return { status: 'error', label: operationStateLabel(state) }
      case 'recovery_required':
        return { status: 'warning', label: operationStateLabel(state) }
      case 'pending':
      case 'in_progress':
      case 'deleting':
        return { status: 'pending', label: operationStateLabel(state) }
      case 'deleted':
        return { status: 'stopped', label: operationStateLabel(state) }
    }
  }
  return { status: 'info', label: operationStateLabel(state) }
}

export function operationLivenessPresentation(
  liveness: AdminOperationLiveness | null | undefined
): AdminOperationStatePresentation | null {
  switch (liveness) {
    case 'alive':
      return { status: 'running', label: 'Executor alive' }
    case 'stopped':
      return { status: 'stopped', label: 'Executor stopped' }
    case 'ambiguous':
      return { status: 'warning', label: 'Liveness ambiguous' }
    default:
      return null
  }
}

export function operationRuntimePresentation(
  runtimeState: AdminOperationRuntimeState | null | undefined
): AdminOperationStatePresentation | null {
  switch (runtimeState) {
    case 'present':
      return { status: 'info', label: 'Runtime present' }
    case 'absent':
      return { status: 'stopped', label: 'Runtime absent' }
    case 'ambiguous':
      return { status: 'warning', label: 'Runtime ambiguous' }
    default:
      return null
  }
}

export function operationProofSourceLabel(value: string | null | undefined): string {
  if (!value) return 'Not inspected'
  if (!SAFE_CODE.test(value)) return 'Unavailable'
  return PROOF_SOURCE_LABELS[value] ?? humanizeCode(value)
}

export function isAdminOperationActive(
  kind: AdminOperationKind,
  state: string | null | undefined
): boolean {
  if (!state) return false
  return kind === 'launch' ? LAUNCH_ACTIVE_STATES.has(state) : VOLUME_ACTIVE_STATES.has(state)
}

export function formatHeartbeatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return 'No heartbeat'
  }
  const bounded = Math.max(0, Math.floor(seconds))
  if (bounded < 60) return `${bounded}s`
  if (bounded < 3600) return `${Math.floor(bounded / 60)}m`
  if (bounded < 86400) return `${Math.floor(bounded / 3600)}h`
  return `${Math.floor(bounded / 86400)}d`
}

export function sanitizeOperationDiagnostics(
  diagnostics: Record<string, string> | null | undefined
): AdminOperationDiagnostic[] {
  if (!diagnostics || typeof diagnostics !== 'object') return []
  const result: AdminOperationDiagnostic[] = []
  for (const key of Object.keys(DIAGNOSTIC_LABELS)) {
    const value = diagnostics[key]
    if (typeof value !== 'string') continue
    const bounded = value.slice(0, 64)
    if (!SAFE_DIAGNOSTIC_VALUE.test(bounded)) continue
    result.push({ key, label: DIAGNOSTIC_LABELS[key], value: bounded })
  }
  return result
}

export function sanitizeOperationCounters(
  counters: Record<string, number> | null | undefined
): AdminOperationCounter[] {
  if (!counters || typeof counters !== 'object') return []
  const value = counters.container_count
  if (!Number.isInteger(value) || value < 0) return []
  return [{ key: 'container_count', label: 'Matching containers', value }]
}

function sanitizedDiagnosticRecord(
  diagnostics: Record<string, string> | null | undefined
): Record<string, string> {
  return Object.fromEntries(
    sanitizeOperationDiagnostics(diagnostics).map(({ key, value }) => [key, value])
  )
}

function clampInteger(
  value: number | undefined,
  fallback: number,
  minimum: number,
  maximum: number
) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return fallback
  return Math.min(maximum, Math.max(minimum, Math.floor(value)))
}

export function buildAdminOperationQuery(filters: AdminOperationFilters = {}): string {
  const params = new URLSearchParams()
  if (filters.kind) params.set('kind', filters.kind)
  if (filters.state) params.set('state', filters.state)
  if (filters.owner_id) params.set('owner_id', filters.owner_id)
  if (typeof filters.age_days === 'number' && Number.isFinite(filters.age_days)) {
    params.set('age_days', String(Math.max(0, Math.floor(filters.age_days))))
  }
  if (filters.older_than) params.set('older_than', filters.older_than)
  if (filters.recovery_required === true) params.set('recovery_required', 'true')
  else if (filters.recovery_required === false) params.set('recovery_required', 'false')
  params.set('limit', String(clampInteger(filters.limit, 50, 1, 100)))
  params.set('offset', String(clampInteger(filters.offset, 0, 0, 1000)))
  return params.toString()
}

export function adminOperationsPath(filters: AdminOperationFilters = {}): string {
  return `/admin/operations?${buildAdminOperationQuery(filters)}`
}

export function adminOperationDetailPath(kind: AdminOperationKind, id: string): string {
  return `/admin/operations/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`
}

export function fetchAdminOperations(
  filters: AdminOperationFilters = {}
): Promise<AdminOperationPage> {
  return api.get<AdminOperationPage>(adminOperationsPath(filters))
}

export function fetchAdminOperation(kind: AdminOperationKind, id: string): Promise<AdminOperation> {
  return api.get<AdminOperation>(adminOperationDetailPath(kind, id))
}

export interface AdminOperationRequestErrorOptions {
  recoveryRequired?: boolean
  applied?: boolean
  evidence?: AdminOperationRecoveryEvidence | null
}

export class AdminOperationRequestError extends Error {
  readonly status: number
  readonly code: string | null
  readonly recoveryRequired: boolean
  readonly applied: boolean
  readonly evidence: AdminOperationRecoveryEvidence | null

  constructor(
    message: string,
    status: number,
    code: string | null,
    options: AdminOperationRequestErrorOptions = {}
  ) {
    super(message)
    this.name = 'AdminOperationRequestError'
    this.status = status
    this.code = code
    this.recoveryRequired = options.recoveryRequired === true
    this.applied = options.applied === true
    this.evidence = options.evidence ?? null
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function asString(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function asSafeCode(value: unknown): string | null {
  const text = asString(value)
  return text && SAFE_CODE.test(text) ? text : null
}

function asLiveness(value: unknown): AdminOperationLiveness | null {
  return value === 'alive' || value === 'stopped' || value === 'ambiguous' ? value : null
}

function asRuntimeState(value: unknown): AdminOperationRuntimeState | null {
  return value === 'present' || value === 'absent' || value === 'ambiguous' ? value : null
}

function recoveryEvidence(detail: Record<string, unknown> | null): AdminOperationRecoveryEvidence {
  const diagnostics = asRecord(detail?.diagnostics)
  const sanitized: Record<string, string> = {}
  if (diagnostics) {
    for (const [key, value] of Object.entries(diagnostics)) {
      if (typeof value === 'string') sanitized[key] = value
    }
  }
  return {
    state: asSafeCode(detail?.state),
    liveness: asLiveness(detail?.liveness),
    proof_source: asSafeCode(detail?.proof_source),
    runtime_state: asRuntimeState(detail?.runtime_state),
    reason_code: asSafeCode(detail?.reason_code),
    diagnostics: sanitizedDiagnosticRecord(sanitized),
  }
}

function errorDetail(body: unknown): Record<string, unknown> | null {
  const record = asRecord(body)
  if (!record) return null
  // FastAPI HTTPException nests the stable payload under `detail`; accept a
  // top-level payload as well so the client stays compatible with both.
  return asRecord(record.detail) ?? record
}

function codeFromBody(body: unknown): string | null {
  return asSafeCode(errorDetail(body)?.code)
}

export async function reconcileAdminOperation(
  kind: AdminOperationKind,
  id: string,
  reason: string
): Promise<AdminOperationReconcileResult> {
  const normalized = normalizeOperationReason(reason)
  const validation = operationReasonValidationError(normalized)
  if (validation) {
    throw new AdminOperationRequestError(validation, 422, 'invalid_reason')
  }

  const send = (token: string) =>
    fetch(`${API_BASE}${adminOperationDetailPath(kind, id)}/reconcile`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ reason: normalized }),
    })

  let response = await send(localStorage.getItem('nukelab-token') || '')
  if (response.status === 401) {
    const refreshed = await refreshAccessToken()
    if (!refreshed) {
      throw new AdminOperationRequestError(
        'Your session expired. Sign in again.',
        401,
        'session_expired'
      )
    }
    response = await send(localStorage.getItem('nukelab-token') || '')
  }

  let body: unknown
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (response.ok) {
    if (!asRecord(body)) {
      throw new AdminOperationRequestError(
        'The server returned an unexpected response. Refresh before retrying.',
        response.status,
        'invalid_response'
      )
    }
    return body as AdminOperationReconcileResult
  }

  const detail = errorDetail(body)
  const code = codeFromBody(body)
  if (response.status === 409 && code === 'recovery_required') {
    throw new AdminOperationRequestError(
      'Proof is still ambiguous. No mutation or reservation release occurred.',
      409,
      code,
      {
        recoveryRequired: true,
        applied: false,
        evidence: recoveryEvidence(detail),
      }
    )
  }

  throw new AdminOperationRequestError(
    operationErrorMessage(code, response.status),
    response.status,
    code
  )
}

function operationErrorMessage(code: string | null, status: number): string {
  switch (code) {
    case 'operation_not_found':
      return 'The operation no longer exists. Refresh the list and try again.'
    case 'inspection_unavailable':
      return 'Operation inspection is temporarily unavailable. Try again later. No change was made.'
    case 'permission_denied':
    case 'permission_revoked':
      return 'You do not have permission to reconcile this operation.'
    case 'audit_unavailable':
      return 'The audit entry could not be recorded, so no change was made.'
    case 'invalid_reason':
      return 'Enter a reason between 1 and 255 characters without control characters.'
    case 'session_expired':
      return 'Your session expired. Sign in again.'
    case 'invalid_response':
      return 'The server returned an unexpected response. Refresh before retrying.'
    default:
      break
  }
  if (status === 404) return 'The operation no longer exists. Refresh the list and try again.'
  if (status === 503) {
    return 'Operation inspection is temporarily unavailable. Try again later. No change was made.'
  }
  if (status === 403) return 'You do not have permission to reconcile this operation.'
  if (status === 422) {
    return 'Enter a reason between 1 and 255 characters without control characters.'
  }
  if (status === 401) return 'Your session expired. Sign in again.'
  if (status >= 500) return 'The server could not complete the request. No change was confirmed.'
  if (status === 0) return 'The request could not reach the server. No change was confirmed.'
  return 'The request failed. No change was confirmed.'
}

function errorCode(error: unknown): string | null {
  if (error instanceof AdminOperationRequestError) return error.code
  if (error instanceof ApiError) return error.code ?? null
  if (error && typeof error === 'object' && 'code' in error) {
    const value = (error as { code?: unknown }).code
    return typeof value === 'string' ? value : null
  }
  return null
}

function errorStatus(error: unknown): number {
  if (error instanceof AdminOperationRequestError) return error.status
  if (error instanceof ApiError) return error.status
  return 0
}

export function adminOperationErrorInfo(error: unknown): AdminOperationErrorInfo {
  if (error instanceof AdminOperationRequestError && error.recoveryRequired) {
    return {
      code: error.code,
      message: error.message,
      recoveryRequired: true,
      applied: false,
      evidence: error.evidence,
    }
  }
  const code = errorCode(error)
  const status = errorStatus(error)
  return {
    code,
    message: operationErrorMessage(code, status),
    recoveryRequired: false,
    applied: false,
    evidence: null,
  }
}

export function adminOperationLoadErrorInfo(error: unknown): AdminOperationErrorInfo {
  const code = errorCode(error)
  const status = errorStatus(error)
  let message = 'Could not load operation evidence. Try again.'
  if (code === 'permission_denied' || code === 'permission_revoked' || status === 403) {
    message = 'You do not have permission to view operations.'
  } else if (code === 'operation_not_found' || status === 404) {
    message = 'The operation no longer exists. Refresh the list.'
  } else if (status === 503) {
    message = 'Operation evidence is temporarily unavailable. Try again later.'
  }
  return {
    code,
    message,
    recoveryRequired: false,
    applied: false,
    evidence: null,
  }
}
