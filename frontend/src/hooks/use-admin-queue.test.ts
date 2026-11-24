// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'

let keys: (typeof import('./use-admin-queue'))['adminQueueKeys']

beforeAll(async () => {
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn(), removeItem: vi.fn() })
  keys = (await import('./use-admin-queue')).adminQueueKeys
})

afterAll(() => {
  vi.unstubAllGlobals()
})

describe('admin queue query keys', () => {
  it('separates filters and pagination windows', () => {
    expect(keys.list({ limit: 20, offset: 0 })).not.toEqual(keys.list({ limit: 20, offset: 20 }))
    expect(keys.list({ statuses: ['starting'], limit: 20, offset: 0 })).not.toEqual(
      keys.list({ recovery_required: true, limit: 20, offset: 0 })
    )
    expect(
      keys.list({ owner_id: '11111111-1111-4111-8111-111111111111', limit: 20, offset: 0 })
    ).not.toEqual(keys.list({ owner_id: null, limit: 20, offset: 0 }))
  })

  it('keeps every list under one invalidation prefix', () => {
    const list = keys.list({ statuses: ['failed'], limit: 50, offset: 100 })
    expect(list.slice(0, keys.all.length)).toEqual(keys.all)
    expect(keys.lists().slice(0, keys.all.length)).toEqual(keys.all)
  })
})
