// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { User } from '../types/api'

let state: (typeof import('../stores/auth-store'))['useAuthStore']
let client: (typeof import('../lib/api'))['queryClient']
let keys: (typeof import('./use-server-queue'))['queueKeys']

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
  state = (await import('../stores/auth-store')).useAuthStore
  client = (await import('../lib/api')).queryClient
  keys = (await import('./use-server-queue')).queueKeys
})
afterEach(() => {
  state.getState().setUser(null)
  client.clear()
})
afterAll(() => vi.unstubAllGlobals())

describe('owner queue cache isolation', () => {
  it('uses distinct owner keys and removes old capabilities, list and detail on account change', () => {
    state.getState().setUser(owner('first'))
    const first = [
      keys.capabilities('first'),
      keys.list('first', 1),
      keys.detail('first', 'owned-request'),
    ]
    first.forEach((key) => client.setQueryData(key, { private: 'first owner' }))
    expect(keys.list('first', 1)).not.toEqual(keys.list('second', 1))
    state.getState().setUser(owner('second'))
    first.forEach((key) => expect(client.getQueryData(key)).toBeUndefined())
    expect(client.getQueryData(keys.list('second', 1))).toBeUndefined()
  })

  it('clears cached request metadata on logout', () => {
    state.getState().setUser(owner('owner'))
    client.setQueryData(keys.detail('owner', 'request'), { private: true })
    state.getState().setUser(null)
    expect(client.getQueryData(keys.detail('owner', 'request'))).toBeUndefined()
  })

  it('does not repopulate a removed owner cache when its old in-flight fetch completes', async () => {
    state.getState().setUser(owner('first'))
    let complete!: (value: { private: string }) => void
    const pending = new Promise<{ private: string }>((resolve) => {
      complete = resolve
    })
    const waiting = client
      .fetchQuery({ queryKey: keys.list('first', 1), queryFn: () => pending })
      .catch(() => undefined)
    state.getState().setUser(owner('second'))
    complete({ private: 'late first-owner payload' })
    await waiting
    expect(client.getQueryData(keys.list('first', 1))).toBeUndefined()
    expect(client.getQueryData(keys.list('second', 1))).toBeUndefined()
  })
})
