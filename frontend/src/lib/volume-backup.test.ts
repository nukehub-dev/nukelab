// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import {
  recoveryErrorMessage,
  recoveryIsActive,
  recoveryPollInterval,
  recoveryStatusLabel,
  restoreCapacity,
} from './volume-backup'

describe('truthful recovery state', () => {
  it('polls active work with bounded error backoff and pauses hidden tabs', () => {
    expect(recoveryIsActive('recovery_required')).toBe(true)
    expect(recoveryIsActive('completed')).toBe(false)
    expect(recoveryIsActive('delete_failed')).toBe(false)
    expect(recoveryPollInterval(true, 0, false)).toBe(5000)
    expect(recoveryPollInterval(true, 20, false)).toBe(30000)
    expect(recoveryPollInterval(true, 0, true)).toBe(false)
    expect(recoveryPollInterval(false, 0, false)).toBe(false)
    expect(recoveryStatusLabel('in_progress')).toBe('Working')
    expect(recoveryStatusLabel('recovery_required')).toBe('Needs attention')
  })
  it('requires explicit positive destination capacity that fits the logical data', () => {
    expect(restoreCapacity('1.5', 1024)).toBe(1610612736)
    for (const size of ['', '0', '-1', 'Infinity', 'bad'])
      expect(() => restoreCapacity(size, 1)).toThrow('positive size')
    expect(() => restoreCapacity('1', 2 * 1024 ** 3)).toThrow('logical data')
  })
  it('does not echo raw backend details for unknown operation codes', () => {
    expect(
      recoveryErrorMessage(Object.assign(new Error('/private/storage/path'), { code: 'unknown' }))
    ).not.toContain('/private')
    expect(
      recoveryErrorMessage(Object.assign(new Error('/private/storage/path'), { status: 500 }))
    ).not.toContain('/private')
    expect(
      recoveryErrorMessage(Object.assign(new Error('raw'), { code: 'artifact_corrupt' }))
    ).toContain('integrity')
  })
})
