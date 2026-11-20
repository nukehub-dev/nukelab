// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { beforeAll, afterAll, afterEach, describe, expect, it, vi } from 'vitest'
import type { User } from '../types/api'

let store: (typeof import('../stores/auth-store'))['useAuthStore']
let client: (typeof import('../lib/api'))['queryClient']
let keys: (typeof import('./use-volume-backups'))['backupKeys']
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
  keys = (await import('./use-volume-backups')).backupKeys
})
afterEach(() => {
  store.getState().setUser(null)
  client.clear()
})
afterAll(() => vi.unstubAllGlobals())
describe('recovery owner cache isolation', () => {
  it('clears history, eligibility and restores on account switch and logout', () => {
    store.getState().setUser(owner('first'))
    const prior = [
      keys.capabilities('first'),
      keys.eligibility('first', 'volume'),
      keys.list('first', 1),
      keys.restores('first', 1),
    ]
    prior.forEach((key) => client.setQueryData(key, { private: true }))
    store.getState().setUser(owner('second'))
    prior.forEach((key) => expect(client.getQueryData(key)).toBeUndefined())
    client.setQueryData(keys.list('second', 1), { private: true })
    store.getState().setUser(null)
    expect(client.getQueryData(keys.list('second', 1))).toBeUndefined()
  })
  it('cannot repopulate another account with a delayed history response', async () => {
    store.getState().setUser(owner('first'))
    let finish!: (value: unknown) => void
    const pending = new Promise((resolve) => {
      finish = resolve
    })
    const result = client
      .fetchQuery({ queryKey: keys.list('first', 1), queryFn: () => pending })
      .catch(() => undefined)
    store.getState().setUser(owner('second'))
    finish({ items: [{ private: true }] })
    await result
    expect(client.getQueryData(keys.list('first', 1))).toBeUndefined()
  })
})
