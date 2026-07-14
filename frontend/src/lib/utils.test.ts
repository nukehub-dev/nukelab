// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  formatDate,
  formatDateOnly,
  formatRelativeTime,
  parseLocalDate,
  parseUtcDate,
} from './utils'
import { useTimezoneStore } from '../stores/timezone-store'

afterEach(() => {
  vi.unstubAllEnvs()
  useTimezoneStore.getState().setPreference('auto')
})

describe('parseUtcDate', () => {
  it('treats a naive ISO datetime string as UTC', () => {
    expect(parseUtcDate('2026-01-01T12:00:00').getTime()).toBe(
      new Date('2026-01-01T12:00:00Z').getTime()
    )
  })

  it('treats a naive string with fractional seconds as UTC', () => {
    expect(parseUtcDate('2026-07-14T16:00:00.123456').getTime()).toBe(
      new Date('2026-07-14T16:00:00.123Z').getTime()
    )
  })

  it('leaves strings with a Z designator unchanged', () => {
    expect(parseUtcDate('2026-01-01T12:00:00Z').getTime()).toBe(
      new Date('2026-01-01T12:00:00Z').getTime()
    )
  })

  it('leaves strings with a numeric offset unchanged', () => {
    expect(parseUtcDate('2026-01-01T12:00:00+05:00').getTime()).toBe(
      new Date('2026-01-01T12:00:00+05:00').getTime()
    )
    expect(parseUtcDate('2026-01-01T12:00:00-08:00').getTime()).toBe(
      new Date('2026-01-01T12:00:00-08:00').getTime()
    )
  })

  it('passes date-only strings through (parsed as UTC per spec)', () => {
    expect(parseUtcDate('2026-01-01').getTime()).toBe(new Date('2026-01-01').getTime())
  })

  it('passes Date instances through by reference', () => {
    const d = new Date('2026-01-01T12:00:00Z')
    expect(parseUtcDate(d)).toBe(d)
  })
})

describe('formatDate', () => {
  it('formats a naive string the same as the equivalent Z-suffixed Date', () => {
    expect(formatDate('2026-01-01T12:00:00')).toBe(formatDate(new Date('2026-01-01T12:00:00Z')))
  })

  it('produces a localized date+time format with a short zone label', () => {
    expect(formatDate(new Date('2026-01-01T12:00:00Z'))).toMatch(
      /^[A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M \S+$/
    )
  })
})

describe('formatDate timezone handling', () => {
  it('renders the wall time and short zone label of the selected zone', () => {
    useTimezoneStore.getState().setPreference('UTC')
    expect(formatDate('2026-01-01T12:00:00')).toBe('Jan 1, 2026, 12:00 PM UTC')

    useTimezoneStore.getState().setPreference('America/New_York')
    expect(formatDate('2026-01-01T12:00:00')).toBe('Jan 1, 2026, 07:00 AM EST')
  })

  it("uses the browser zone when the preference is 'auto'", () => {
    vi.stubEnv('TZ', 'America/New_York')
    useTimezoneStore.getState().setPreference('auto')
    expect(formatDate('2026-01-01T12:00:00')).toBe('Jan 1, 2026, 07:00 AM EST')
  })

  it('falls back to auto for an invalid zone id', () => {
    useTimezoneStore.getState().setPreference('Not/AZone')
    expect(useTimezoneStore.getState().preference).toBe('auto')
  })
})

describe('formatDateOnly', () => {
  it('omits time fields but still applies the selected zone', () => {
    useTimezoneStore.getState().setPreference('UTC')
    expect(formatDateOnly('2026-01-01T12:00:00')).toBe('Jan 1, 2026')

    useTimezoneStore.getState().setPreference('Pacific/Kiritimati')
    expect(formatDateOnly('2026-01-01T12:00:00')).toBe('Jan 2, 2026')
  })
})

describe('parseLocalDate', () => {
  it.each(['America/New_York', 'Pacific/Kiritimati'])(
    'keeps the calendar day under TZ=%s',
    (tz) => {
      vi.stubEnv('TZ', tz)
      const d = parseLocalDate('2026-01-15')
      expect(d.getFullYear()).toBe(2026)
      expect(d.getMonth()).toBe(0)
      expect(d.getDate()).toBe(15)
    }
  )

  it('round-trips through formatDateOnly without shifting the day', () => {
    for (const tz of ['America/New_York', 'Pacific/Kiritimati']) {
      vi.stubEnv('TZ', tz)
      useTimezoneStore.getState().setPreference('auto')
      expect(formatDateOnly(parseLocalDate('2026-01-15'))).toBe('Jan 15, 2026')
    }
  })
})

describe('formatRelativeTime', () => {
  it('describes a past timestamp relative to now', () => {
    const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString()
    expect(formatRelativeTime(oneHourAgo)).toBe('1 hour ago')
  })

  it('treats naive strings as UTC when computing the offset', () => {
    // A naive string ~90 seconds in the past (UTC) must read "1 minute ago";
    // parsed as local time it could be hours off depending on the timezone.
    const naive = new Date(Date.now() - 90 * 1000).toISOString().replace('Z', '')
    expect(formatRelativeTime(naive)).toBe('1 minute ago')
  })

  it('falls back to formatDate for timestamps more than a year away', () => {
    const twoYearsAgo = new Date(Date.now() - 2 * 365 * 24 * 60 * 60 * 1000).toISOString()
    expect(formatRelativeTime(twoYearsAgo)).toBe(formatDate(twoYearsAgo))
  })
})
