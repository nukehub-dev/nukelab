// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { User } from '../types/api'

let state: (typeof import('../stores/auth-store'))['useAuthStore']
let client: (typeof import('../lib/api'))['queryClient']
let keys: (typeof import('./use-admin-jobs'))['adminJobKeys']

function actor(id: string): User {
  return {
    id,
    username: id,
    email: `${id}@example.test`,
    display_name: id,
    avatar_url: '',
    role: 'admin',
    nuke_balance: 0,
    daily_allowance: 0,
    is_active: true,
    is_verified: true,
    login_count: 0,
    permissions: ['operations:read_all', 'admin:access'],
  }
}

beforeAll(async () => {
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: vi.fn(), removeItem: vi.fn() })
  state = (await import('../stores/auth-store')).useAuthStore
  client = (await import('../lib/api')).queryClient
  keys = (await import('./use-admin-jobs')).adminJobKeys
})

afterEach(() => {
  state.getState().setUser(null)
  client.clear()
})

afterAll(() => vi.unstubAllGlobals())

describe('admin job cache isolation', () => {
  it('keys every list window by actor and filters', () => {
    const filters = { state: 'active' as const, limit: 20, offset: 0 }
    expect(keys.list('first', filters)).not.toEqual(keys.list('second', filters))
    expect(keys.list('first', filters)).not.toEqual(
      keys.list('first', { ...filters, state: 'history' })
    )
    expect(keys.list('first', filters)).not.toEqual(keys.list('first', { ...filters, offset: 20 }))
    expect(keys.list('first', filters).slice(0, keys.owner('first').length)).toEqual(
      keys.owner('first')
    )
  })

  it('removes the old operator cache on account switch', () => {
    state.getState().setUser(actor('first'))
    const first = [keys.lists('first'), keys.list('first', { state: 'all' })]
    first.forEach((key) => client.setQueryData(key, { private: 'first operator' }))
    state.getState().setUser(actor('second'))
    first.forEach((key) => expect(client.getQueryData(key)).toBeUndefined())
    expect(client.getQueryData(keys.list('second', { state: 'all' }))).toBeUndefined()
  })

  it('clears cached job rows on logout', () => {
    state.getState().setUser(actor('operator'))
    client.setQueryData(keys.list('operator', { state: 'all' }), { private: true })
    state.getState().setUser(null)
    expect(client.getQueryData(keys.list('operator', { state: 'all' }))).toBeUndefined()
  })

  it('does not repopulate a removed operator cache when an old fetch finishes', async () => {
    state.getState().setUser(actor('first'))
    let complete!: (value: { private: string }) => void
    const pending = new Promise<{ private: string }>((resolve) => {
      complete = resolve
    })
    const waiting = client
      .fetchQuery({
        queryKey: keys.list('first', { state: 'active' }),
        queryFn: () => pending,
      })
      .catch(() => undefined)
    state.getState().setUser(actor('second'))
    complete({ private: 'late first-operator payload' })
    await waiting
    expect(client.getQueryData(keys.list('first', { state: 'active' }))).toBeUndefined()
    expect(client.getQueryData(keys.list('second', { state: 'active' }))).toBeUndefined()
  })
})
