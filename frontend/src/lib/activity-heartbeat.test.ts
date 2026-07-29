// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import {
  ACTIVITY_HEARTBEAT_INTERVAL_MS,
  ACTIVITY_INPUT_WINDOW_MS,
  shouldPingActivity,
} from './activity-heartbeat'

describe('shouldPingActivity', () => {
  const now = 1_000_000

  it('returns false when there was no interaction', () => {
    expect(shouldPingActivity(null, now)).toBe(false)
  })

  it('returns true for a fresh interaction', () => {
    expect(shouldPingActivity(now - 1_000, now)).toBe(true)
  })

  it('returns true at the exact window boundary', () => {
    expect(shouldPingActivity(now - ACTIVITY_INPUT_WINDOW_MS, now)).toBe(true)
  })

  it('returns false once the interaction is older than the window', () => {
    expect(shouldPingActivity(now - ACTIVITY_INPUT_WINDOW_MS - 1, now)).toBe(false)
  })

  it('returns false for interactions far in the past', () => {
    expect(shouldPingActivity(0, now)).toBe(false)
  })

  it('honours a custom window', () => {
    expect(shouldPingActivity(now - 5_000, now, 10_000)).toBe(true)
    expect(shouldPingActivity(now - 15_000, now, 10_000)).toBe(false)
  })
})

describe('heartbeat constants', () => {
  it('input window stays below the 5-minute minimum idle shutdown timeout', () => {
    // The backend clamps idle_shutdown_timeout to >= 5 minutes. The input
    // window must be shorter so the final ping always precedes the earliest
    // possible idle shutdown.
    expect(ACTIVITY_INPUT_WINDOW_MS).toBeLessThan(5 * 60_000)
  })

  it('several heartbeat ticks fit inside the input window', () => {
    expect(ACTIVITY_INPUT_WINDOW_MS).toBeGreaterThanOrEqual(ACTIVITY_HEARTBEAT_INTERVAL_MS * 2)
  })
})
