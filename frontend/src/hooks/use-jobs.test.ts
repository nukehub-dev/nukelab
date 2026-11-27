// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { User } from '../types/api'

let state: (typeof import('../stores/auth-store'))['useAuthStore']
let client: (typeof import('../lib/api'))['queryClient']
let keys: (typeof import('./use-jobs'))['jobKeys']

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
  keys = (await import('./use-jobs')).jobKeys
})

afterEach(() => {
  state.getState().setUser(null)
  client.clear()
})

afterAll(() => vi.unstubAllGlobals())

describe('owner job cache isolation', () => {
  it('keys capabilities, revisions, list filters, detail and logs by owner', () => {
    expect(keys.capabilities('first')).not.toEqual(keys.capabilities('second'))
    expect(keys.list('first', 'active')).not.toEqual(keys.list('second', 'active'))
    expect(keys.list('owner', 'active')).not.toEqual(keys.list('owner', 'history'))
    expect(keys.detail('owner', 'job-1')).not.toEqual(keys.logs('owner', 'job-1'))
  })

  it('removes the old owner cache on account switch', () => {
    state.getState().setUser(owner('first'))
    const first = [
      keys.capabilities('first'),
      keys.eligibleRevisions('first'),
      keys.list('first', 'all'),
      keys.detail('first', 'job-1'),
      keys.logs('first', 'job-1'),
    ]
    first.forEach((key) => client.setQueryData(key, { private: 'first owner' }))
    state.getState().setUser(owner('second'))
    first.forEach((key) => expect(client.getQueryData(key)).toBeUndefined())
    expect(client.getQueryData(keys.list('second', 'all'))).toBeUndefined()
  })

  it('clears cached job metadata on logout', () => {
    state.getState().setUser(owner('owner'))
    client.setQueryData(keys.detail('owner', 'job-1'), { private: true })
    client.setQueryData(keys.logs('owner', 'job-1'), { private: true })
    state.getState().setUser(null)
    expect(client.getQueryData(keys.detail('owner', 'job-1'))).toBeUndefined()
    expect(client.getQueryData(keys.logs('owner', 'job-1'))).toBeUndefined()
  })

  it('does not repopulate a removed owner cache when an old fetch finishes', async () => {
    state.getState().setUser(owner('first'))
    let complete!: (value: { private: string }) => void
    const pending = new Promise<{ private: string }>((resolve) => {
      complete = resolve
    })
    const waiting = client
      .fetchQuery({ queryKey: keys.detail('first', 'job-1'), queryFn: () => pending })
      .catch(() => undefined)
    state.getState().setUser(owner('second'))
    complete({ private: 'late first-owner payload' })
    await waiting
    expect(client.getQueryData(keys.detail('first', 'job-1'))).toBeUndefined()
    expect(client.getQueryData(keys.detail('second', 'job-1'))).toBeUndefined()
  })
})
