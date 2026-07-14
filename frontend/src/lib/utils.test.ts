// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import { formatDate, formatRelativeTime, parseUtcDate } from './utils'

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

  it('produces the en-US date+time format', () => {
    expect(formatDate(new Date('2026-01-01T12:00:00Z'))).toMatch(
      /^[A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M$/
    )
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
