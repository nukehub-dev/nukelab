// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getPushSubscription, subscribePush, unsubscribePush } from './register-sw'

const VALID_KEY = 'BNcRd' // short base64url string; only atob-decoded, never verified

function makeSubscription() {
  return {
    toJSON: () => ({
      endpoint: 'https://push.example.com/sub-1',
      keys: { p256dh: 'p256dh-value', auth: 'auth-value' },
    }),
    unsubscribe: vi.fn(async () => true),
  }
}

function makeRegistration(overrides: Record<string, unknown> = {}) {
  return {
    pushManager: {
      subscribe: vi.fn(async () => makeSubscription()),
      getSubscription: vi.fn(async () => makeSubscription()),
    },
    ...overrides,
  }
}

beforeEach(() => {
  vi.stubGlobal('window', {
    atob: (s: string) => Buffer.from(s, 'base64').toString('binary'),
    PushManager: class {},
  })
  vi.stubGlobal('Notification', { requestPermission: vi.fn(async () => 'granted') })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('subscribePush', () => {
  it('throws when service workers are unsupported', async () => {
    vi.stubGlobal('navigator', {})
    await expect(subscribePush(VALID_KEY, vi.fn())).rejects.toThrow(
      'Service workers are not supported'
    )
  })

  it('registers the service worker on demand when none is registered', async () => {
    const registration = makeRegistration()
    const register = vi.fn(async () => registration)
    vi.stubGlobal('navigator', {
      serviceWorker: {
        getRegistration: vi.fn(async () => undefined),
        register,
        ready: Promise.resolve(registration),
      },
    })
    const saveSubscription = vi.fn(async () => {})

    const info = await subscribePush(VALID_KEY, saveSubscription)

    expect(register).toHaveBeenCalledWith('/sw.js', { scope: '/' })
    expect(info?.endpoint).toBe('https://push.example.com/sub-1')
    expect(saveSubscription).toHaveBeenCalledWith({
      endpoint: 'https://push.example.com/sub-1',
      keys: { p256dh: 'p256dh-value', auth: 'auth-value' },
    })
  })

  it('rejects instead of hanging when activation never completes', async () => {
    vi.useFakeTimers()
    const registration = makeRegistration()
    vi.stubGlobal('navigator', {
      serviceWorker: {
        getRegistration: vi.fn(async () => registration),
        ready: new Promise(() => {}), // never resolves
      },
    })

    const promise = subscribePush(VALID_KEY, vi.fn())
    const assertion = expect(promise).rejects.toThrow('Service worker activation timed out')
    await vi.advanceTimersByTimeAsync(10_000)
    await assertion
  })
})

describe('unsubscribePush', () => {
  it('returns silently when no service worker is registered', async () => {
    vi.stubGlobal('navigator', {
      serviceWorker: { getRegistration: vi.fn(async () => undefined) },
    })
    const removeSubscription = vi.fn(async () => {})

    await expect(unsubscribePush(removeSubscription)).resolves.toBeUndefined()
    expect(removeSubscription).not.toHaveBeenCalled()
  })
})

describe('getPushSubscription', () => {
  it('returns null when no service worker is registered', async () => {
    vi.stubGlobal('navigator', {
      serviceWorker: { getRegistration: vi.fn(async () => undefined) },
    })
    await expect(getPushSubscription()).resolves.toBeNull()
  })
})
