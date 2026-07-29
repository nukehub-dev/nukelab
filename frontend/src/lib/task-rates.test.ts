// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import { computeTaskRates, parseMemoryToBytes } from './task-rates'

function task(pid: number, cpuTimeSeconds: number, rssBytes = 0, memPercent = 1.5) {
  return {
    pid,
    cpu_time_seconds: cpuTimeSeconds,
    cpu_percent: 99.9, // ps lifetime value — must be overwritten
    mem_percent: memPercent,
    rss_bytes: rssBytes,
  }
}

describe('computeTaskRates', () => {
  it('reports 0% CPU on the first poll (no delta yet)', () => {
    const { tasks, snapshot } = computeTaskRates([task(1, 100)], null, 10_000, 16)
    expect(tasks[0].cpu_percent).toBe(0)
    expect(snapshot.byPid.get(1)).toBe(100)
  })

  it('computes CPU% of the allocation from the delta between polls', () => {
    const { snapshot } = computeTaskRates([task(1, 100)], null, 0, 16)
    // 10 CPU-seconds over 5s wall = 2 cores of 16 allocated = 12.5%
    const { tasks } = computeTaskRates([task(1, 110)], snapshot, 5_000, 16)
    expect(tasks[0].cpu_percent).toBeCloseTo(12.5)
  })

  it('caps nothing: full allocation busy reports 100%', () => {
    const { snapshot } = computeTaskRates([task(1, 0)], null, 0, 4)
    // 4 cores busy over 5s on a 4-core plan
    const { tasks } = computeTaskRates([task(1, 20)], snapshot, 5_000, 4)
    expect(tasks[0].cpu_percent).toBeCloseTo(100)
  })

  it('treats new pids as 0%', () => {
    const { snapshot } = computeTaskRates([task(1, 100)], null, 0, 16)
    const { tasks } = computeTaskRates([task(2, 500)], snapshot, 5_000, 16)
    expect(tasks[0].cpu_percent).toBe(0)
  })

  it('treats counter resets (process restart reusing pid) as 0%', () => {
    const { snapshot } = computeTaskRates([task(1, 500)], null, 0, 16)
    const { tasks } = computeTaskRates([task(1, 10)], snapshot, 5_000, 16)
    expect(tasks[0].cpu_percent).toBe(0)
  })

  it('falls back to per-core scale when no allocation is known', () => {
    const { snapshot } = computeTaskRates([task(1, 100)], null, 0)
    const { tasks } = computeTaskRates([task(1, 110)], snapshot, 5_000)
    expect(tasks[0].cpu_percent).toBeCloseTo(200) // 2 cores
  })

  it('computes MEM% from RSS against allocated memory', () => {
    const gib = 1024 ** 3
    const { tasks } = computeTaskRates([task(1, 0, 8 * gib)], null, 0, 16, 32 * gib)
    expect(tasks[0].mem_percent).toBeCloseTo(25)
  })

  it('keeps the ps MEM% when no allocation is known', () => {
    const { tasks } = computeTaskRates([task(1, 0, 1, 7.5)], null, 0)
    expect(tasks[0].mem_percent).toBe(7.5)
  })
})

describe('parseMemoryToBytes', () => {
  it('parses plan memory strings', () => {
    expect(parseMemoryToBytes('32g')).toBe(32 * 1024 ** 3)
    expect(parseMemoryToBytes('512m')).toBe(512 * 1024 ** 2)
    expect(parseMemoryToBytes('1GB')).toBe(1024 ** 3)
    expect(parseMemoryToBytes('1024')).toBe(1024)
  })

  it('returns undefined for missing or malformed values', () => {
    expect(parseMemoryToBytes(undefined)).toBeUndefined()
    expect(parseMemoryToBytes('lots')).toBeUndefined()
    expect(parseMemoryToBytes('')).toBeUndefined()
  })
})
