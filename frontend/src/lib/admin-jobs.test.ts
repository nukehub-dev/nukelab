// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import {
  ADMIN_JOB_MANAGE_PERMISSIONS,
  ADMIN_JOB_READ_PERMISSIONS,
  ADMIN_JOB_REASON_MAX_LENGTH,
  ADMIN_JOB_REASON_MIN_LENGTH,
  AdminJobReconcileRequestError,
  adminJobAccess,
  adminJobCleanupStateLabel,
  adminJobCreatedLabel,
  adminJobEnvironmentLabel,
  adminJobHeartbeatLabel,
  adminJobLogStateLabel,
  adminJobOwnerLabel,
  adminJobPlanLabel,
  adminJobProofSourceLabel,
  adminJobReasonPresentation,
  adminJobReasonValidationError,
  adminJobReconcileErrorInfo,
  adminJobReconcilePath,
  adminJobStatePresentation,
  adminJobVolumeLabel,
  adminJobsLoadErrorInfo,
  adminJobsPath,
  buildAdminJobsQuery,
  canSubmitAdminJobReason,
  emptyAdminJobSummary,
  fetchAdminJobs,
  isAdminJobActive,
  isAdminJobRecoveryRequired,
  normalizeAdminJobReason,
  reconcileAdminJob,
  safeAdminJobCode,
  sanitizeAdminJobEntry,
  sanitizeAdminJobPage,
  sanitizeAdminJobReconcileResult,
  sanitizeAdminJobSummary,
  shortAdminJobReference,
} from './admin-jobs'
import type { AdminJobEntry, AdminJobState } from '../types/admin-jobs'

const ownerId = '11111111-1111-4111-8111-111111111111'
const jobId = '22222222-2222-4222-8222-222222222222'

function entry(overrides: Partial<AdminJobEntry> = {}): AdminJobEntry {
  return {
    id: jobId,
    state: 'running',
    reason_code: 'waiting_capacity',
    owner_id: ownerId,
    owner_username: 'alice',
    owner_display_name: 'Alice Admin',
    environment_name: 'Approved runtime',
    environment_display_label: 'Approved runtime — approved 2026-11-20',
    plan_name: 'Small',
    volume_display_name: 'pilot-data',
    created_at: '2026-11-27T12:00:00',
    updated_at: '2026-11-27T12:01:00',
    finished_at: null,
    reservation_active: true,
    guard_active: true,
    heartbeat_age_seconds: 120,
    log_state: 'pending',
    cleanup_state: 'pending',
    cleanup_attempts: 0,
    can_reconcile: false,
    ...overrides,
  }
}

function pagePayload() {
  return {
    items: [entry()],
    pagination: { limit: 20, offset: 40, total: 61, has_more: true },
    summary: {
      total: 61,
      queued: 3,
      starting: 1,
      running: 2,
      cancelling: 0,
      recovery_required: 1,
      succeeded: 50,
      failed: 4,
      cancelled: 0,
      timed_out: 0,
      expired: 0,
    },
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function granted(permissions: string[]) {
  return (required: string[]) => required.every((permission) => permissions.includes(permission))
}

beforeEach(() => {
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => (key === 'nukelab-token' ? 'token' : null),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('admin jobs access', () => {
  it('requires both operations read and admin access to read', () => {
    expect([...ADMIN_JOB_READ_PERMISSIONS]).toEqual(['operations:read_all', 'admin:access'])
    expect(adminJobAccess(granted([...ADMIN_JOB_READ_PERMISSIONS]))).toEqual({
      canRead: true,
      canManage: false,
    })
    expect(adminJobAccess(granted(['operations:read_all']))).toEqual({
      canRead: false,
      canManage: false,
    })
    expect(adminJobAccess(granted(['admin:access']))).toEqual({
      canRead: false,
      canManage: false,
    })
    expect(adminJobAccess(granted([]))).toEqual({ canRead: false, canManage: false })
  })

  it('requires operations manage plus the read permissions for reconcile', () => {
    expect([...ADMIN_JOB_MANAGE_PERMISSIONS]).toEqual([
      'operations:manage_all',
      'operations:read_all',
      'admin:access',
    ])
    expect(adminJobAccess(granted([...ADMIN_JOB_MANAGE_PERMISSIONS]))).toEqual({
      canRead: true,
      canManage: true,
    })
    expect(adminJobAccess(granted(['operations:manage_all', 'admin:access']))).toEqual({
      canRead: false,
      canManage: false,
    })
    expect(adminJobAccess(granted(['operations:manage_all', 'operations:read_all']))).toEqual({
      canRead: false,
      canManage: false,
    })
  })
})

describe('admin jobs filters and transport', () => {
  it('serializes state, age, and bounded pagination', () => {
    const query = buildAdminJobsQuery({
      state: 'history',
      age_min_seconds: 259200,
      limit: 500,
      offset: -1,
    })
    const params = new URLSearchParams(query)

    expect(params.get('state')).toBe('history')
    expect(params.get('age_min_seconds')).toBe('259200')
    expect(params.get('limit')).toBe('100')
    expect(params.get('offset')).toBe('0')
    expect(adminJobsPath({ limit: 10, offset: 20 })).toBe('/admin/jobs?limit=10&offset=20')
  })

  it('omits the all/default state and clamps out-of-range ages', () => {
    const params = new URLSearchParams(
      buildAdminJobsQuery({
        state: 'all',
        age_min_seconds: -10,
        limit: 10,
        offset: 0,
      })
    )

    expect(params.get('state')).toBeNull()
    expect(params.get('age_min_seconds')).toBe('0')
    expect(
      new URLSearchParams(buildAdminJobsQuery({ state: 'bogus' as never })).get('state')
    ).toBeNull()
  })

  it('lists a bounded page through the read-only admin jobs API', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(pagePayload()))
    vi.stubGlobal('fetch', fetchMock)

    const page = await fetchAdminJobs({ limit: 20, offset: 40 })

    expect(page.items).toHaveLength(1)
    expect(page.pagination).toEqual({ limit: 20, offset: 40, total: 61, has_more: true })
    expect(page.summary.running).toBe(2)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/admin/jobs?limit=20&offset=40')
    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({
      Authorization: 'Bearer token',
    })
  })

  it('sanitizes malformed rows and pagination before rendering', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          items: [
            entry({
              id: 'not-a-uuid',
              state: 'unexpected',
              owner_username: 'bad\u0007owner',
              log_state: '../../private',
              cleanup_state: '/private/path',
              cleanup_attempts: 2.5,
              heartbeat_age_seconds: -1,
              created_at: 'not-a-date',
              can_reconcile: true,
            }),
          ],
          pagination: { limit: 0, offset: 5000, total: -3, has_more: false },
        })
      )
    )

    const page = await fetchAdminJobs()

    expect(page.items[0]).toMatchObject({
      id: '',
      state: 'unknown',
      owner_username: 'badowner',
      log_state: 'unknown',
      cleanup_state: 'unknown',
      cleanup_attempts: 0,
      heartbeat_age_seconds: null,
      created_at: null,
      can_reconcile: false,
    })
    expect(page.pagination).toEqual({ limit: 50, offset: 0, total: 0, has_more: false })
    expect(page.summary).toEqual(emptyAdminJobSummary())
  })

  it('drops command, log, and environment fields before rendering', () => {
    const raw = {
      ...entry(),
      argv: ['python', '/work/secret.py'],
      logs: { text: 'log-secret output' },
      environment_values: { API_KEY: 'env-secret' },
      runtime_identity: { path: '/var/lib/private/runtime' },
    } as AdminJobEntry

    const sanitized = sanitizeAdminJobEntry(raw)

    expect(sanitized).not.toHaveProperty('argv')
    expect(sanitized).not.toHaveProperty('logs')
    expect(sanitized).not.toHaveProperty('environment_values')
    expect(sanitized).not.toHaveProperty('runtime_identity')
  })

  it('preserves stable API error codes and gives bounded messages', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: { code: 'permission_denied' } }, 403))
    )

    const error = await fetchAdminJobs().catch((reason: unknown) => reason)

    expect(error).toBeInstanceOf(ApiError)
    expect(adminJobsLoadErrorInfo(error)).toEqual({
      code: 'permission_denied',
      message: 'You do not have permission to view batch jobs.',
    })
    expect(adminJobsLoadErrorInfo(new ApiError('unavailable', 503))).toMatchObject({
      message: 'Job visibility is temporarily unavailable. Try again later.',
    })
    expect(adminJobsLoadErrorInfo(new Error('raw backend detail'))).toEqual({
      code: null,
      message: 'Could not load batch jobs. Try again.',
    })
  })
})

describe('admin jobs reconcile', () => {
  function reconcilePayload(overrides: Record<string, unknown> = {}) {
    return {
      job: entry({ state: 'succeeded', can_reconcile: false }),
      applied: true,
      already_terminal: false,
      outcome: 'applied',
      terminal_state: 'succeeded',
      proof_source: 'executor_absent',
      reason_code: null,
      ...overrides,
    }
  }

  it('trims and bounds the reason between 8 and 500 characters', () => {
    expect(ADMIN_JOB_REASON_MIN_LENGTH).toBe(8)
    expect(ADMIN_JOB_REASON_MAX_LENGTH).toBe(500)
    expect(adminJobReasonValidationError('')).toBe('Enter a reason.')
    expect(adminJobReasonValidationError('   ')).toBe('Enter a reason.')
    expect(adminJobReasonValidationError('short')).toBe('Reason must be at least 8 characters.')
    expect(adminJobReasonValidationError('12345678')).toBeNull()
    expect(adminJobReasonValidationError(` ${'x'.repeat(8)} `)).toBeNull()
    expect(adminJobReasonValidationError('x'.repeat(501))).toBe(
      'Reason must be 500 characters or fewer.'
    )
    expect(adminJobReasonValidationError('valid\u0007reason')).toBe(
      'Reason must not contain control characters.'
    )
    expect(normalizeAdminJobReason('  operator checked proof  ')).toBe('operator checked proof')
    expect(canSubmitAdminJobReason('12345678', false)).toBe(true)
    expect(canSubmitAdminJobReason('12345678', true)).toBe(false)
    expect(canSubmitAdminJobReason('short', false)).toBe(false)
  })

  it('posts the bounded reason and sanitizes the proof result', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        reconcilePayload({
          job: {
            ...entry({ state: 'succeeded', can_reconcile: false }),
            argv: ['python', '/work/secret.py'],
            logs: { text: 'log-secret output' },
          },
          raw_runtime: '/var/lib/private/runtime',
        })
      )
    )
    vi.stubGlobal('fetch', fetchMock)

    const reason = '  operator verified executor termination  '
    const result = await reconcileAdminJob(jobId, reason)

    expect(result.outcome).toBe('applied')
    expect(result.applied).toBe(true)
    expect(result.terminal_state).toBe('succeeded')
    expect(result.job).not.toHaveProperty('argv')
    expect(result.job).not.toHaveProperty('logs')
    expect(result).not.toHaveProperty('raw_runtime')
    expect(adminJobReconcilePath(jobId)).toBe(`/admin/jobs/${jobId}/reconcile`)
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/admin/jobs/${jobId}/reconcile`)
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ reason: 'operator verified executor termination' }),
    })
  })

  it('keeps the row unchanged when proof is insufficient', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            detail: {
              code: 'proof_insufficient',
              message: 'raw /var/lib/private/runtime payload',
            },
          },
          409
        )
      )
    )

    const error = await reconcileAdminJob(jobId, 'operator checked the runtime').catch(
      (reason: unknown) => reason
    )

    expect(error).toBeInstanceOf(AdminJobReconcileRequestError)
    expect(error).toMatchObject({ status: 409, code: 'proof_insufficient' })
    expect((error as Error).message).not.toContain('/var/lib/private')
    expect(adminJobReconcileErrorInfo(error)).toEqual({
      code: 'proof_insufficient',
      message:
        'Proof is still insufficient. No job state, reservation, or volume guard was changed.',
    })
  })

  it('maps 409 not-reconcilable and 404 not-found to bounded messages', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: { code: 'job_not_reconcilable' } }, 409))
    )
    const notReconcilable = await reconcileAdminJob(jobId, 'operator checked the runtime').catch(
      (reason: unknown) => reason
    )
    expect(adminJobReconcileErrorInfo(notReconcilable)).toEqual({
      code: 'job_not_reconcilable',
      message:
        'This job is already terminal or no longer reconcilable. Refresh the list to see its current state.',
    })

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: { code: 'job_not_found' } }, 404))
    )
    const notFound = await reconcileAdminJob(jobId, 'operator checked the runtime').catch(
      (reason: unknown) => reason
    )
    expect(adminJobReconcileErrorInfo(notFound)).toEqual({
      code: 'job_not_found',
      message: 'The job no longer exists. Refresh the list and try again.',
    })
  })

  it('rejects an invalid reason before making a request', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const error = await reconcileAdminJob(jobId, 'short').catch((reason: unknown) => reason)

    expect(error).toMatchObject({ status: 422, code: 'invalid_reason' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('normalizes bounded outcome fields and labels proof sources', () => {
    expect(sanitizeAdminJobEntry(entry({ can_reconcile: true })).can_reconcile).toBe(true)
    expect(
      sanitizeAdminJobEntry(entry({ id: 'not-a-uuid', can_reconcile: true })).can_reconcile
    ).toBe(false)

    const result = sanitizeAdminJobReconcileResult(
      reconcilePayload({
        outcome: 'unexpected',
        applied: false,
        already_terminal: true,
        terminal_state: '/private/path',
        proof_source: 'executor_absent',
        reason_code: 'password=secret',
      })
    )

    expect(result.outcome).toBe('already_terminal')
    expect(result.terminal_state).toBeNull()
    expect(result.proof_source).toBe('executor_absent')
    expect(result.reason_code).toBeNull()
    expect(adminJobProofSourceLabel(result.proof_source)).toBe('Executor absent')
    expect(adminJobProofSourceLabel('/private/path')).toBe('Not reported')
  })
})

describe('admin jobs presentation', () => {
  it('maps every bounded state to a label and tone', () => {
    const expected: Record<AdminJobState, string> = {
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
    for (const [state, label] of Object.entries(expected)) {
      expect(adminJobStatePresentation(state)).toMatchObject({ label })
    }
    expect(adminJobStatePresentation('unexpected')).toEqual({ tone: 'info', label: 'Unknown' })
    expect(isAdminJobActive('running')).toBe(true)
    expect(isAdminJobActive('succeeded')).toBe(false)
    expect(isAdminJobRecoveryRequired('recovery_required')).toBe(true)
    expect(isAdminJobRecoveryRequired('failed')).toBe(false)
  })

  it('only renders safe reason codes and highlights recovery', () => {
    expect(adminJobReasonPresentation('recovery_required')).toEqual({
      tone: 'warning',
      label: 'Operator verification required',
    })
    expect(adminJobReasonPresentation('waiting_capacity')).toEqual({
      tone: 'info',
      label: 'Waiting for capacity',
    })
    expect(adminJobReasonPresentation('/private/host/path')).toBeNull()
    expect(safeAdminJobCode('runtime_unverifiable')).toBe('runtime_unverifiable')
    expect(safeAdminJobCode('password=secret')).toBeNull()
  })

  it('uses bounded owner and target labels with safe fallbacks', () => {
    const named = entry()
    expect(adminJobOwnerLabel(named)).toBe('@alice')
    expect(adminJobEnvironmentLabel(named)).toBe('Approved runtime — approved 2026-11-20')
    expect(adminJobPlanLabel(named)).toBe('Small')
    expect(adminJobVolumeLabel(named)).toBe('pilot-data')

    const fallback = entry({
      owner_username: null,
      environment_name: null,
      environment_display_label: null,
      plan_name: null,
      volume_display_name: null,
    })
    expect(adminJobOwnerLabel(fallback)).toBe('11111111')
    expect(adminJobEnvironmentLabel(fallback)).toBe('Environment unavailable')
    expect(adminJobPlanLabel(fallback)).toBe('Plan unavailable')
    expect(adminJobVolumeLabel(fallback)).toBe('Volume unavailable')
    expect(adminJobOwnerLabel(entry({ owner_username: 'bad\u0007owner' }))).toBe('@badowner')
  })

  it('labels log, cleanup, heartbeat, and age fields without inventing values', () => {
    expect(adminJobLogStateLabel('pending')).toBe('Pending')
    expect(adminJobLogStateLabel('truncated')).toBe('Truncated')
    expect(adminJobLogStateLabel('../../private')).toBe('Unknown')
    expect(adminJobCleanupStateLabel('in_progress')).toBe('In progress')
    expect(adminJobCleanupStateLabel('/private/path')).toBe('Unknown')
    expect(adminJobHeartbeatLabel(30)).toBe('30s')
    expect(adminJobHeartbeatLabel(null)).toBe('No heartbeat')
    expect(adminJobCreatedLabel('not-a-date')).toBe('—')
    expect(adminJobCreatedLabel(null)).toBe('—')
    expect(shortAdminJobReference(jobId)).toBe('22222222')
    expect(shortAdminJobReference('../../private')).toBe('Unknown')
  })

  it('defaults missing or malformed summaries to bounded zero counts', () => {
    const missing = sanitizeAdminJobPage({
      items: [],
      pagination: { limit: 20, offset: 0, total: 5, has_more: false },
    } as unknown as Parameters<typeof sanitizeAdminJobPage>[0])

    expect(missing.summary).toEqual(emptyAdminJobSummary())
    expect(
      sanitizeAdminJobSummary({
        total: -4,
        queued: 2.9,
        starting: Number.POSITIVE_INFINITY,
        running: '3',
        cancelling: 9,
        recovery_required: null,
        succeeded: 1,
        failed: 0,
        cancelled: 0,
        timed_out: 0,
        expired: 0,
      })
    ).toEqual({
      total: 0,
      queued: 2,
      starting: 0,
      running: 0,
      cancelling: 9,
      recovery_required: 0,
      succeeded: 1,
      failed: 0,
      cancelled: 0,
      timed_out: 0,
      expired: 0,
    })
  })
})
