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

function base64ToBinary(input: string): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
  const str = input.replace(/=+$/, '')
  let output = ''
  let buffer = 0
  let bits = 0
  for (const c of str) {
    const val = chars.indexOf(c)
    if (val === -1) continue
    buffer = (buffer << 6) | val
    bits += 6
    if (bits >= 8) {
      bits -= 8
      output += String.fromCharCode((buffer >> bits) & 0xff)
    }
  }
  return output
}

beforeEach(() => {
  vi.stubGlobal('window', {
    atob: (s: string) => base64ToBinary(s),
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
