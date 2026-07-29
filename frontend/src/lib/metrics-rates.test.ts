// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import { counterRate } from './metrics-rates'

describe('counterRate', () => {
  it('returns 0 without a previous sample', () => {
    expect(counterRate(null, { t: 10_000, value: 500 })).toBe(0)
  })

  it('computes bytes per second from the delta', () => {
    const rate = counterRate({ t: 0, value: 1_000 }, { t: 5_000, value: 51_000 })
    expect(rate).toBe(10_000) // 50 kB over 5 s
  })

  it('returns 0 when the counter resets (container restart)', () => {
    expect(counterRate({ t: 0, value: 9_000_000 }, { t: 5_000, value: 100 })).toBe(0)
  })

  it('returns 0 for duplicate timestamps', () => {
    expect(counterRate({ t: 5_000, value: 100 }, { t: 5_000, value: 200 })).toBe(0)
  })

  it('returns 0 when the counter does not increase', () => {
    expect(counterRate({ t: 0, value: 500 }, { t: 5_000, value: 500 })).toBe(0)
  })
})
