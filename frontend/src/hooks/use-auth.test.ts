// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { beforeEach, describe, expect, it, vi } from 'vitest'

// The real store uses zustand/persist, which expects a DOM storage backend;
// replace it with a spy — the store contract is all logout() needs.
const setUserMock = vi.fn()
vi.mock('../stores/auth-store', () => ({
  useAuthStore: { getState: () => ({ setUser: setUserMock }) },
}))

// Minimal browser-global stubs (tests run in the node environment). They must
// be installed before './use-auth' is imported, so the module is loaded
// dynamically inside the tests.
const storage = new Map<string, string>()
const locationStub = { href: '' }
let cookieValue = ''

vi.stubGlobal('localStorage', {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => void storage.set(key, value),
  removeItem: (key: string) => void storage.delete(key),
  clear: () => storage.clear(),
})
vi.stubGlobal('window', { location: locationStub })
vi.stubGlobal('document', {
  get cookie() {
    return cookieValue
  },
  set cookie(value: string) {
    cookieValue = value
  },
})

async function loadLogout() {
  const mod = await import('./use-auth')
  return mod.logout
}

describe('logout', () => {
  beforeEach(() => {
    storage.clear()
    locationStub.href = ''
    cookieValue = ''
    storage.set('nukelab-token', 'access-tok')
    storage.set('nukelab-refresh', 'refresh-tok')
  })

  it('navigates to the provider end-session URL when the backend returns one', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({ oauth_logout_url: 'https://auth.example.com/logout?client_id=x' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const logout = await loadLogout()
    logout()

    await vi.waitFor(() =>
      expect(locationStub.href).toBe('https://auth.example.com/logout?client_id=x')
    )
    expect(storage.has('nukelab-token')).toBe(false)
    expect(storage.has('nukelab-refresh')).toBe(false)

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer access-tok')
    expect(JSON.parse(init.body as string)).toEqual({ refresh_token: 'refresh-tok' })
  })

  it('falls back to /login when the backend returns no provider URL', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ message: 'Logged out successfully' }),
      })
    )

    const logout = await loadLogout()
    logout()

    await vi.waitFor(() => expect(locationStub.href).toBe('/login'))
    expect(storage.has('nukelab-token')).toBe(false)
  })

  it('falls back to /login when the logout request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))

    const logout = await loadLogout()
    logout()

    await vi.waitFor(() => expect(locationStub.href).toBe('/login'))
    expect(storage.has('nukelab-token')).toBe(false)
    expect(storage.has('nukelab-refresh')).toBe(false)
  })
})
