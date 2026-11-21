// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'

let client: (typeof import('../lib/api'))['queryClient']
let keys: (typeof import('./use-admin-operations'))['adminOperationKeys']
let invalidate: (typeof import('./use-admin-operations'))['invalidateAdminOperationData']

beforeAll(async () => {
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn(), removeItem: vi.fn() })
  client = (await import('../lib/api')).queryClient
  const hook = await import('./use-admin-operations')
  keys = hook.adminOperationKeys
  invalidate = hook.invalidateAdminOperationData
})

afterAll(() => {
  client.clear()
  vi.unstubAllGlobals()
})

describe('admin operation query keys', () => {
  it('includes filters and separates list windows from detail evidence', () => {
    expect(keys.list({ kind: 'launch', limit: 20, offset: 0 })).not.toEqual(
      keys.list({ kind: 'backup', limit: 20, offset: 0 })
    )
    expect(keys.list({ kind: 'launch', limit: 20, offset: 0 })).not.toEqual(
      keys.list({ kind: 'launch', limit: 20, offset: 20 })
    )
    expect(keys.detail('launch', 'operation-1')).not.toEqual(keys.detail('launch', 'operation-2'))
    expect(keys.detail('launch', 'operation-1').slice(0, keys.all.length)).toEqual(keys.all)
  })

  it('invalidates list and detail evidence after a reconcile settles', async () => {
    const listKey = keys.list({ kind: 'launch', limit: 20, offset: 0 })
    const detailKey = keys.detail('launch', 'operation-1')
    client.setQueryData(listKey, { items: [], pagination: { total: 0 } })
    client.setQueryData(detailKey, { id: 'operation-1', applied: true })

    await invalidate(client)

    expect(client.getQueryState(listKey)?.isInvalidated).toBe(true)
    expect(client.getQueryState(detailKey)?.isInvalidated).toBe(true)
  })
})
