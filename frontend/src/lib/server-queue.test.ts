// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import {
  canCancelQueuedRequest,
  isQueuedServer,
  isQueueActive,
  parseQueueSearch,
  queuePollInterval,
} from './server-queue'
import type { QueuedServerAcceptance } from '../types/server-queue'

const id = '06f2e09b-7ca3-4411-8d12-a62c5861bada'
const accepted: QueuedServerAcceptance = {
  queued: true,
  queue_id: id,
  queue_position: 1,
  message: 'Waiting for available capacity.',
  request: {
    name: 'my-simulation',
    plan_id: id,
    environment_id: id,
    resources: { cpu: 2, memory_mib: 4096, disk_mib: 10240, gpu_count: 0 },
  },
}

describe('launch acceptance', () => {
  it('distinguishes accepted waiting intent from an actual server identity', () => {
    expect(isQueuedServer(accepted)).toBe(true)
    expect(isQueuedServer({ id, name: 'my-simulation', status: 'running' })).toBe(false)
    expect(accepted).not.toHaveProperty('id')
    expect(accepted.request.name).toBe('my-simulation')
  })
})

describe('request navigation', () => {
  it('retains only validated queue search fields', () => {
    expect(parseQueueSearch({ tab: 'queue', request: id, other: 'ignored' })).toEqual({
      tab: 'queue',
      request: id,
    })
    expect(parseQueueSearch({ tab: 'queue', request: '../../secret' })).toEqual({ tab: 'queue' })
    expect(parseQueueSearch({ tab: 'servers', request: id })).toEqual({})
    expect(parseQueueSearch({ tab: ['queue'], request: { id } })).toEqual({})
  })
})

describe('deploy deep link', () => {
  it('accepts explicit deploy intent', () => {
    expect(parseQueueSearch({ deploy: true })).toEqual({ deploy: true })
    expect(parseQueueSearch({ deploy: '1' })).toEqual({ deploy: true })
    expect(parseQueueSearch({ deploy: 'true' })).toEqual({ deploy: true })
  })

  it('ignores unsupported deploy values', () => {
    expect(parseQueueSearch({ deploy: false })).toEqual({})
    expect(parseQueueSearch({ deploy: 'false' })).toEqual({})
    expect(parseQueueSearch({ deploy: '0' })).toEqual({})
    expect(parseQueueSearch({ deploy: 1 })).toEqual({})
    expect(parseQueueSearch({ deploy: ['true'] })).toEqual({})
    expect(parseQueueSearch({ deploy: { value: true } })).toEqual({})
  })

  it('retains queue context alongside deploy', () => {
    expect(parseQueueSearch({ tab: 'queue', request: id, deploy: '1' })).toEqual({
      tab: 'queue',
      request: id,
      deploy: true,
    })
    expect(parseQueueSearch({ tab: 'queue', request: '../../secret', deploy: true })).toEqual({
      tab: 'queue',
      deploy: true,
    })
  })
})

describe('pending cancellation', () => {
  it('requires both pending status and current server-provided permission', () => {
    expect(canCancelQueuedRequest({ status: 'pending', can_cancel: true })).toBe(true)
    expect(canCancelQueuedRequest({ status: 'pending', can_cancel: false })).toBe(false)
    expect(canCancelQueuedRequest({ status: 'starting', can_cancel: true })).toBe(false)
    expect(canCancelQueuedRequest({ status: 'started', can_cancel: true })).toBe(false)
  })
})

describe('bounded queue refresh', () => {
  it('polls only active requests and backs off after failures', () => {
    expect(isQueueActive({ status: 'pending' })).toBe(true)
    expect(isQueueActive({ status: 'starting' })).toBe(true)
    expect(isQueueActive({ status: 'cancelled' })).toBe(false)
    expect(isQueueActive({ status: 'failed' })).toBe(false)
    expect(queuePollInterval(true, 0, false)).toBe(5000)
    expect(queuePollInterval(true, 2, false)).toBe(20000)
    expect(queuePollInterval(true, 100, false)).toBe(60000)
    expect(queuePollInterval(true, 1, true)).toBe(false)
    expect(queuePollInterval(false, 0, false)).toBe(false)
  })
})
