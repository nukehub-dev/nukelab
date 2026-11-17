// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'
import { isQueuedServer } from './server-queue'
import type { Server } from '../types/api'
import type { QueuedServerAcceptance } from '../types/server-queue'

const queueId = '06f2e09b-7ca3-4411-8d12-a62c5861bada'

beforeEach(() => {
  vi.stubGlobal('localStorage', { getItem: () => 'token' })
})
afterEach(() => vi.unstubAllGlobals())

describe('queued server transport', () => {
  it('accepts HTTP202 without inventing server identity or changing the submitted mounts', async () => {
    const request = {
      name: 'saved-name',
      plan_id: 'plan',
      environment_id: 'environment',
      volume_mounts: [
        { volume_id: '', mount_path: '/home/owner', mode: 'read_write', max_size_bytes: 1024 },
      ],
    }
    const response = {
      queued: true,
      queue_id: queueId,
      queue_position: 1,
      message: 'Waiting',
      request: {
        name: request.name,
        plan_id: 'plan',
        environment_id: 'environment',
        resources: { cpu: 1, memory_mib: 1024, disk_mib: 1024, gpu_count: 0 },
      },
    }
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), { status: 202 }))
    vi.stubGlobal('fetch', fetch)
    const result = await api.post<Server | QueuedServerAcceptance>('/servers/', request)
    expect(isQueuedServer(result)).toBe(true)
    expect(result).not.toHaveProperty('id')
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(request)
    expect(fetch).toHaveBeenCalledOnce()
  })

  it('preserves the owned existing-request reference on duplicate-name409', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: { code: 'request_already_exists', queue_id: queueId },
          }),
          { status: 409 }
        )
      )
    )
    try {
      await api.post('/servers/', {})
      expect.fail('Expected conflict')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect(error).toMatchObject({ status: 409, code: 'request_already_exists', queueId })
      expect((error as Error).message).toContain('already uses this name')
    }
  })

  it('does not turn an untrusted path into a request navigation reference', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: { code: 'request_already_exists', queue_id: '../../private' },
          }),
          { status: 409 }
        )
      )
    )
    await expect(api.post('/servers/', {})).rejects.toMatchObject({ queueId: undefined })
  })
})
