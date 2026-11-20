// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { beforeAll, afterAll, afterEach, describe, expect, it, vi } from 'vitest'
import type { User } from '../types/api'

let store: (typeof import('../stores/auth-store'))['useAuthStore']
let client: (typeof import('../lib/api'))['queryClient']
let keys: (typeof import('./use-server-provenance'))['provenanceKeys']
function owner(id: string): User {
  return {
    id,
    username: id,
    email: `${id}@example.test`,
    display_name: id,
    avatar_url: '',
    role: 'user',
    nuke_balance: 100,
    daily_allowance: 10,
    is_active: true,
    is_verified: true,
    login_count: 0,
  }
}

beforeAll(async () => {
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn(), removeItem: vi.fn() })
  store = (await import('../stores/auth-store')).useAuthStore
  client = (await import('../lib/api')).queryClient
  keys = (await import('./use-server-provenance')).provenanceKeys
})
afterEach(() => {
  store.getState().setUser(null)
  client.clear()
})
afterAll(() => vi.unstubAllGlobals())

describe('provenance owner cache isolation', () => {
  it('clears history and volume/plan catalogs on account switch and logout', () => {
    store.getState().setUser(owner('first'))
    const oldKeys = [
      keys.capabilities('first'),
      keys.detail('first', 'server'),
      keys.plans('first'),
      keys.volumes('first'),
    ]
    oldKeys.forEach((key) => client.setQueryData(key, { private: 'first owner' }))
    store.getState().setUser(owner('second'))
    oldKeys.forEach((key) => expect(client.getQueryData(key)).toBeUndefined())
    client.setQueryData(keys.detail('second', 'other'), { private: true })
    store.getState().setUser(null)
    expect(client.getQueryData(keys.detail('second', 'other'))).toBeUndefined()
  })
  it('does not repopulate an old owner when a late history query returns', async () => {
    store.getState().setUser(owner('first'))
    let complete!: (value: unknown) => void
    const pending = new Promise((resolve) => {
      complete = resolve
    })
    const waiting = client
      .fetchQuery({ queryKey: keys.detail('first', 'server'), queryFn: () => pending })
      .catch(() => undefined)
    store.getState().setUser(owner('second'))
    complete({ private: 'late payload' })
    await waiting
    expect(client.getQueryData(keys.detail('first', 'server'))).toBeUndefined()
  })
})
