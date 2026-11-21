// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ADMIN_OPERATION_MANAGE_PERMISSIONS,
  ADMIN_OPERATION_READ_PERMISSIONS,
  ADMIN_OPERATION_REASON_MAX_LENGTH,
  AdminOperationRequestError,
  adminOperationAccess,
  adminOperationErrorInfo,
  adminOperationLoadErrorInfo,
  adminOperationDetailPath,
  adminOperationKindLabel,
  adminOperationsPath,
  buildAdminOperationQuery,
  canSubmitOperationReason,
  fetchAdminOperation,
  fetchAdminOperations,
  formatHeartbeatAge,
  isAdminOperationActive,
  normalizeOperationReason,
  operationLivenessPresentation,
  operationProofSourceLabel,
  operationReasonValidationError,
  operationRuntimePresentation,
  operationStatePresentation,
  reconcileAdminOperation,
  sanitizeOperationCounters,
  sanitizeOperationDiagnostics,
} from './admin-operations'
import type { AdminOperation, AdminOperationReconcileResult } from '../types/admin-operations'

function operation(overrides: Partial<AdminOperation> = {}): AdminOperation {
  return {
    kind: 'launch',
    id: '11111111-1111-4111-8111-111111111111',
    state: 'executing',
    action: 'create',
    owner_id: '22222222-2222-4222-8222-222222222222',
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:01:00',
    finished_at: null,
    reason_code: null,
    evidence_reason_code: 'runtime_absent',
    recovery_required: false,
    heartbeat_age_seconds: 5,
    liveness: 'stopped',
    proof_source: 'graceful_marker',
    runtime_state: 'absent',
    diagnostics: { row_state: 'executing' },
    counters: { container_count: 0 },
    ...overrides,
  }
}

function result(
  overrides: Partial<AdminOperationReconcileResult> = {}
): AdminOperationReconcileResult {
  return {
    ...operation({ state: 'failed' }),
    previous_state: 'executing',
    applied: true,
    terminal_state: 'failed',
    ...overrides,
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

describe('operation access and reasons', () => {
  it('separates read from manage permissions', () => {
    expect(adminOperationAccess(granted([...ADMIN_OPERATION_READ_PERMISSIONS]))).toEqual({
      canRead: true,
      canManage: false,
    })
    expect(adminOperationAccess(granted([...ADMIN_OPERATION_MANAGE_PERMISSIONS]))).toEqual({
      canRead: false,
      canManage: true,
    })
    expect(adminOperationAccess(granted([]))).toEqual({ canRead: false, canManage: false })
  })

  it('trims and bounds the reconcile reason', () => {
    expect(normalizeOperationReason('  investigate runtime  ')).toBe('investigate runtime')
    expect(operationReasonValidationError('   ')).toBe('Enter a reason.')
    expect(operationReasonValidationError('x'.repeat(ADMIN_OPERATION_REASON_MAX_LENGTH))).toBeNull()
    expect(
      operationReasonValidationError('x'.repeat(ADMIN_OPERATION_REASON_MAX_LENGTH + 1))
    ).toContain('characters or fewer')
    expect(operationReasonValidationError('bad\u0007reason')).toContain('control characters')
    expect(canSubmitOperationReason('  ', false)).toBe(false)
    expect(canSubmitOperationReason('investigate', true)).toBe(false)
    expect(canSubmitOperationReason(' investigate ', false)).toBe(true)
  })
})

describe('operation filters and transport', () => {
  it('serializes every supported filter and bounded pagination', () => {
    const query = buildAdminOperationQuery({
      kind: 'backup',
      state: 'recovery_required',
      owner_id: 'owner-1',
      age_days: 2,
      older_than: '2026-01-01T00:00:00Z',
      recovery_required: false,
      limit: 10,
      offset: 20,
    })
    const params = new URLSearchParams(query)

    expect(params.get('kind')).toBe('backup')
    expect(params.get('state')).toBe('recovery_required')
    expect(params.get('owner_id')).toBe('owner-1')
    expect(params.get('age_days')).toBe('2')
    expect(params.get('older_than')).toBe('2026-01-01T00:00:00Z')
    expect(params.get('recovery_required')).toBe('false')
    expect(params.get('limit')).toBe('10')
    expect(params.get('offset')).toBe('20')
    expect(adminOperationsPath({ limit: 10, offset: 20 })).toBe(
      '/admin/operations?limit=10&offset=20'
    )
    expect(adminOperationDetailPath('restore', 'restore-1')).toBe(
      '/admin/operations/restore/restore-1'
    )
  })

  it('clamps pagination to the backend bounds', () => {
    const params = new URLSearchParams(buildAdminOperationQuery({ limit: 500, offset: -5 }))
    expect(params.get('limit')).toBe('100')
    expect(params.get('offset')).toBe('0')
  })

  it('lists and loads detail through the admin operations API', async () => {
    const page = {
      items: [operation()],
      pagination: { limit: 20, offset: 0, total: 1, has_more: false },
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(page))
      .mockResolvedValueOnce(jsonResponse(operation()))
    vi.stubGlobal('fetch', fetchMock)

    await fetchAdminOperations({ kind: 'launch', recovery_required: true, limit: 20, offset: 0 })
    await fetchAdminOperation('launch', operation().id)

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/admin/operations?kind=launch&recovery_required=true&limit=20&offset=0'
    )
    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({ Authorization: 'Bearer token' })
    expect(fetchMock.mock.calls[1][0]).toBe(
      '/api/admin/operations/launch/11111111-1111-4111-8111-111111111111'
    )
  })

  it('reconciles with a trimmed reason and no force field', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(result()))
    vi.stubGlobal('fetch', fetchMock)

    const response = await reconcileAdminOperation('launch', operation().id, '  verify absence  ')

    expect(response.applied).toBe(true)
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/admin/operations/launch/11111111-1111-4111-8111-111111111111/reconcile'
    )
    expect(fetchMock.mock.calls[0][1].method).toBe('POST')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ reason: 'verify absence' })
  })

  it('returns the 409 evidence without mutating or releasing reservations', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          detail: {
            code: 'recovery_required',
            recovery_required: true,
            applied: false,
            kind: 'launch',
            id: operation().id,
            state: 'executing',
            liveness: 'ambiguous',
            proof_source: 'worker_heartbeat_missing',
            runtime_state: 'absent',
            reason_code: 'runtime_absent',
            diagnostics: {
              row_state: 'executing',
              container_count: '2',
              helper: 'running',
              liveness_proof: 'worker_heartbeat_missing',
              raw_path: '/srv/private/token',
            },
          },
        },
        409
      )
    )
    vi.stubGlobal('fetch', fetchMock)

    const error = await reconcileAdminOperation('launch', operation().id, 'check runtime').catch(
      (reason: unknown) => reason
    )

    expect(error).toBeInstanceOf(AdminOperationRequestError)
    expect(error).toMatchObject({
      status: 409,
      code: 'recovery_required',
      recoveryRequired: true,
      applied: false,
    })
    expect(error).toHaveProperty('evidence', {
      state: 'executing',
      liveness: 'ambiguous',
      proof_source: 'worker_heartbeat_missing',
      runtime_state: 'absent',
      reason_code: 'runtime_absent',
      diagnostics: {
        row_state: 'executing',
        container_count: '2',
        helper: 'running',
        liveness_proof: 'worker_heartbeat_missing',
      },
    })
    expect(JSON.stringify(error)).not.toContain('/srv/private/token')
    expect(Object.keys(JSON.parse(fetchMock.mock.calls[0][1].body))).toEqual(['reason'])

    const info = adminOperationErrorInfo(error)
    expect(info.recoveryRequired).toBe(true)
    expect(info.applied).toBe(false)
    expect(info.message).toContain('No mutation or reservation release occurred')
  })

  it('keeps stable codes for missing operations and unavailable inspection', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ detail: { code: 'operation_not_found' } }, 404))
        .mockResolvedValueOnce(jsonResponse({ detail: { code: 'inspection_unavailable' } }, 503))
    )

    const missing = await reconcileAdminOperation('launch', 'missing', 'check').catch(
      (reason: unknown) => reason
    )
    const unavailable = await reconcileAdminOperation('launch', 'busy', 'check').catch(
      (reason: unknown) => reason
    )

    expect(missing).toMatchObject({ status: 404, code: 'operation_not_found' })
    expect(adminOperationErrorInfo(missing).message).toContain('no longer exists')
    expect(unavailable).toMatchObject({ status: 503, code: 'inspection_unavailable' })
    expect(adminOperationErrorInfo(unavailable).message).toContain('temporarily unavailable')
    expect(adminOperationErrorInfo(unavailable).message).toContain('No change was made')
  })
})

describe('operation presentation and sanitization', () => {
  it('maps launch and volume states to semantic pills', () => {
    expect(operationStatePresentation('launch', 'uncertain')).toEqual({
      status: 'warning',
      label: 'Uncertain',
    })
    expect(operationStatePresentation('backup', 'recovery_required')).toEqual({
      status: 'warning',
      label: 'Recovery required',
    })
    expect(operationStatePresentation('restore', 'completed')).toEqual({
      status: 'running',
      label: 'Completed',
    })
    expect(operationStatePresentation('launch', 'custom_state')).toEqual({
      status: 'info',
      label: 'Custom State',
    })
    expect(operationLivenessPresentation('ambiguous')).toEqual({
      status: 'warning',
      label: 'Liveness ambiguous',
    })
    expect(operationRuntimePresentation('absent')).toEqual({
      status: 'stopped',
      label: 'Runtime absent',
    })
    expect(operationProofSourceLabel('worker_heartbeat_missing')).toBe('Worker heartbeat missing')
    expect(operationProofSourceLabel('/srv/private/path')).toBe('Unavailable')
  })

  it('keeps only bounded allowlisted diagnostics and counters', () => {
    const diagnostics = sanitizeOperationDiagnostics({
      row_state: 'executing',
      container_count: '2',
      raw_docker_inspect: 'secret',
      health_status: 'healthy',
      long_value: 'x'.repeat(100),
    })
    expect(diagnostics).toEqual([
      { key: 'row_state', label: 'Row state', value: 'executing' },
      { key: 'container_count', label: 'Matching containers', value: '2' },
      { key: 'health_status', label: 'Health', value: 'healthy' },
    ])
    expect(sanitizeOperationDiagnostics({ helper: 'running/missing' })).toEqual([])
    expect(sanitizeOperationCounters({ container_count: 2, other: 9 })).toEqual([
      { key: 'container_count', label: 'Matching containers', value: 2 },
    ])
    expect(sanitizeOperationCounters({ container_count: -1 })).toEqual([])
  })

  it('formats heartbeat age without pretending missing evidence is fresh', () => {
    expect(formatHeartbeatAge(null)).toBe('No heartbeat')
    expect(formatHeartbeatAge(42)).toBe('42s')
    expect(formatHeartbeatAge(600)).toBe('10m')
    expect(formatHeartbeatAge(7200)).toBe('2h')
    expect(formatHeartbeatAge(172800)).toBe('2d')
  })

  it('treats only active states as reconcilable', () => {
    expect(isAdminOperationActive('launch', 'executing')).toBe(true)
    expect(isAdminOperationActive('backup', 'recovery_required')).toBe(true)
    expect(isAdminOperationActive('launch', 'failed')).toBe(false)
    expect(isAdminOperationActive('restore', 'completed')).toBe(false)
    expect(adminOperationKindLabel('restore')).toBe('Restore')
  })

  it('never surfaces raw exception text or unsafe load details', () => {
    const info = adminOperationErrorInfo(new Error('/srv/private/secret-token'))
    expect(info.message).not.toContain('/srv/private')
    expect(info.message).toContain('No change was confirmed')

    const load = adminOperationLoadErrorInfo(new Error('/srv/private/secret-token'))
    expect(load.message).not.toContain('/srv/private')
    expect(load.message).toContain('Could not load')
  })
})

describe('operation detail transport', () => {
  it('surfaces a 404 for a missing detail read', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: { code: 'operation_not_found' } }, 404))
    )

    const error = await fetchAdminOperation('launch', 'missing').catch((reason: unknown) => reason)

    expect(adminOperationLoadErrorInfo(error).message).toContain('no longer exists')
  })
})
