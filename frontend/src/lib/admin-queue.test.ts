// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import {
  ADMIN_QUEUE_READ_PERMISSIONS,
  adminQueueAccess,
  adminQueueLoadErrorInfo,
  adminQueuePath,
  buildAdminQueueQuery,
  fetchAdminQueue,
  isQueueRecoveryRequired,
  queueReasonPresentation,
  queueRelativeTimestampLabel,
  queueStatusPresentation,
  queueTimestampLabel,
  safeQueueReasonCode,
  safeQueueServerName,
  sanitizeQueueEntry,
  shortQueueReference,
} from './admin-queue'
import type { AdminQueueEntry, AdminQueueStatus } from '../types/admin-queue'

const ownerId = '11111111-1111-4111-8111-111111111111'
const requestId = '22222222-2222-4222-8222-222222222222'
const serverId = '33333333-3333-4333-8333-333333333333'
const environmentId = '44444444-4444-4444-8444-444444444444'
const planId = '55555555-5555-4555-8555-555555555555'

function entry(overrides: Partial<AdminQueueEntry> = {}): AdminQueueEntry {
  return {
    id: requestId,
    owner_id: ownerId,
    server_id: serverId,
    server_name: 'saved-request',
    environment_id: environmentId,
    plan_id: planId,
    status: 'pending',
    reason_code: 'capacity_wait',
    position: 2,
    priority: 5,
    requested_at: '2026-01-01T00:00:00',
    started_at: null,
    failed_at: null,
    expires_at: '2026-01-01T01:00:00',
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

describe('admin queue access', () => {
  it('requires both cross-user server read and admin access', () => {
    expect([...ADMIN_QUEUE_READ_PERMISSIONS]).toEqual(['servers:read_all', 'admin:access'])
    expect(adminQueueAccess(granted([...ADMIN_QUEUE_READ_PERMISSIONS]))).toEqual({
      canRead: true,
    })
    expect(adminQueueAccess(granted(['servers:read_all']))).toEqual({ canRead: false })
    expect(adminQueueAccess(granted(['admin:access']))).toEqual({ canRead: false })
    expect(adminQueueAccess(granted([]))).toEqual({ canRead: false })
  })
})

describe('admin queue filters and transport', () => {
  it('serializes repeatable statuses, recovery, owner, age and bounded pagination', () => {
    const query = buildAdminQueueQuery({
      statuses: ['starting', 'failed', 'starting', 'unknown' as AdminQueueStatus],
      owner_id: ownerId,
      age_days: 3,
      older_than: '2026-01-01T00:00:00Z',
      recovery_required: true,
      limit: 500,
      offset: -1,
    })
    const params = new URLSearchParams(query)

    expect(params.getAll('status')).toEqual(['starting', 'failed'])
    expect(params.get('owner_id')).toBe(ownerId)
    expect(params.get('age_days')).toBe('3')
    expect(params.get('older_than')).toBe('2026-01-01T00:00:00Z')
    expect(params.get('recovery_required')).toBe('true')
    expect(params.get('limit')).toBe('100')
    expect(params.get('offset')).toBe('0')
    expect(adminQueuePath({ limit: 10, offset: 20 })).toBe('/admin/server-queue?limit=10&offset=20')
  })

  it('omits invalid references and serializes recovery=false', () => {
    const params = new URLSearchParams(
      buildAdminQueueQuery({
        statuses: [],
        owner_id: '../../private',
        older_than: 'not-a-date',
        recovery_required: false,
        limit: 10,
        offset: 0,
      })
    )

    expect(params.getAll('status')).toEqual([])
    expect(params.get('owner_id')).toBeNull()
    expect(params.get('older_than')).toBeNull()
    expect(params.get('recovery_required')).toBe('false')
  })

  it('lists a bounded page through the read-only admin queue API', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        items: [entry()],
        pagination: { limit: 20, offset: 40, total: 61, has_more: true },
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    const page = await fetchAdminQueue({ limit: 20, offset: 40 })

    expect(page.items).toHaveLength(1)
    expect(page.items[0].position).toBe(2)
    expect(page.pagination).toEqual({ limit: 20, offset: 40, total: 61, has_more: true })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/admin/server-queue?limit=20&offset=40')
    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({
      Authorization: 'Bearer token',
    })
  })

  it('sanitizes malformed rows and pagination before the page renders them', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          items: [
            entry({
              server_name: 'bad\u0000name',
              reason_code: '/private/host/path',
              position: 0,
              priority: -2,
              requested_at: 'not-a-date',
            }),
          ],
          pagination: { limit: 0, offset: 5000, total: -3, has_more: false },
        })
      )
    )

    const page = await fetchAdminQueue()

    expect(page.items[0].server_name).toBe('badname')
    expect(page.items[0].reason_code).toBeNull()
    expect(page.items[0].position).toBeNull()
    expect(page.items[0].priority).toBe(0)
    expect(page.items[0].requested_at).toBeNull()
    expect(page.pagination).toEqual({ limit: 50, offset: 0, total: 0, has_more: false })
  })

  it('preserves stable API error codes and gives bounded messages', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: { code: 'permission_denied' } }, 403))
    )

    const error = await fetchAdminQueue().catch((reason: unknown) => reason)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 403, code: 'permission_denied' })
    expect(adminQueueLoadErrorInfo(error)).toEqual({
      code: 'permission_denied',
      message: 'You do not have permission to view the server queue.',
    })
    expect(adminQueueLoadErrorInfo(new ApiError('unavailable', 503))).toMatchObject({
      message: 'Queue visibility is temporarily unavailable. Try again later.',
    })
    expect(adminQueueLoadErrorInfo(new Error('raw backend detail'))).toEqual({
      code: null,
      message: 'Could not load queue requests. Try again.',
    })
  })
})

describe('admin queue presentation', () => {
  it('maps every status to a bounded label and tone', () => {
    expect(queueStatusPresentation('pending')).toEqual({ tone: 'pending', label: 'Pending' })
    expect(queueStatusPresentation('scheduled')).toEqual({ tone: 'info', label: 'Scheduled' })
    expect(queueStatusPresentation('starting')).toEqual({ tone: 'warning', label: 'Starting' })
    expect(queueStatusPresentation('started')).toEqual({ tone: 'running', label: 'Started' })
    expect(queueStatusPresentation('failed')).toEqual({ tone: 'error', label: 'Failed' })
    expect(queueStatusPresentation('cancelled')).toEqual({ tone: 'stopped', label: 'Cancelled' })
    expect(queueStatusPresentation('unexpected')).toEqual({ tone: 'info', label: 'Unknown' })
  })

  it('only renders safe reason codes and highlights recovery', () => {
    expect(queueReasonPresentation('recovery_required')).toEqual({
      tone: 'warning',
      label: 'Recovery required',
    })
    expect(queueReasonPresentation('capacity_wait')).toEqual({
      tone: 'info',
      label: 'Capacity Wait',
    })
    expect(queueReasonPresentation('/private/host/path')).toBeNull()
    expect(safeQueueReasonCode('runtime_absent')).toBe('runtime_absent')
    expect(safeQueueReasonCode('password=secret')).toBeNull()
    expect(isQueueRecoveryRequired('recovery_required')).toBe(true)
    expect(isQueueRecoveryRequired('capacity_wait')).toBe(false)
  })

  it('keeps references short and timestamps bounded', () => {
    expect(shortQueueReference(requestId)).toBe('22222222')
    expect(shortQueueReference('../../private')).toBe('Unknown')
    expect(safeQueueServerName('  request\u0007name  ')).toBe('requestname')
    expect(safeQueueServerName('')).toBe('Unnamed request')
    expect(queueTimestampLabel('not-a-date')).toBe('—')
    expect(queueRelativeTimestampLabel(null)).toBe('—')
  })

  it('drops unsupported fields before rendering', () => {
    const raw = {
      ...entry(),
      request_payload: { claim_token: 'secret-token' },
      claim_token: 'secret-token',
      plan_snapshot: { mount_path: '/home/private' },
    } as AdminQueueEntry

    const sanitized = sanitizeQueueEntry(raw)

    expect(sanitized).not.toHaveProperty('request_payload')
    expect(sanitized).not.toHaveProperty('claim_token')
    expect(sanitized).not.toHaveProperty('plan_snapshot')
    expect(sanitized.server_name).toBe('saved-request')
  })
})
