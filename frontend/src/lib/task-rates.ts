// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Derive current per-process resource usage from ps output.
 *
 * ps %CPU is a lifetime average on a per-core scale (16 busy threads report
 * 1600%) and %MEM is relative to host RAM — both misleading inside a
 * container. Instead we compute the current CPU rate from cumulative
 * cpu_time_seconds deltas between polls and express it as a percentage of
 * the server's allocated cores, and memory as RSS / allocated memory.
 */

import { counterRate } from './metrics-rates'

export interface TaskSnapshot {
  t: number
  byPid: Map<number, number>
}

export interface ComputedTask {
  pid: number
  cpu_time_seconds: number
  cpu_percent: number
  mem_percent: number
  rss_bytes: number
}

/**
 * Rewrite cpu_percent / mem_percent of each task to allocation-relative,
 * current values. Returns the enriched tasks plus the snapshot to pass back
 * as `prev` on the next poll. First poll (prev = null) reports 0% CPU —
 * there is no delta to compute yet.
 */
export function computeTaskRates<T extends ComputedTask>(
  tasks: T[],
  prev: TaskSnapshot | null,
  now: number,
  allocatedCpu?: number,
  allocatedMemoryBytes?: number
): { tasks: T[]; snapshot: TaskSnapshot } {
  const snapshot: TaskSnapshot = {
    t: now,
    byPid: new Map(tasks.map((t) => [t.pid, t.cpu_time_seconds])),
  }

  const enriched = tasks.map((t) => {
    const prevTime = prev?.byPid.get(t.pid)
    const cores =
      prev && prevTime !== undefined
        ? counterRate({ t: prev.t, value: prevTime }, { t: now, value: t.cpu_time_seconds })
        : 0
    const cpuPercent = allocatedCpu && allocatedCpu > 0 ? (cores / allocatedCpu) * 100 : cores * 100
    const memPercent =
      allocatedMemoryBytes && allocatedMemoryBytes > 0
        ? (t.rss_bytes / allocatedMemoryBytes) * 100
        : t.mem_percent
    return { ...t, cpu_percent: cpuPercent, mem_percent: memPercent }
  })

  return { tasks: enriched, snapshot }
}

/** Parse a plan memory string like "32g" or "512m" into bytes (1024-based). */
export function parseMemoryToBytes(value: string | undefined): number | undefined {
  if (!value) return undefined
  const match = value.trim().match(/^([\d.]+)\s*([a-z]*)$/i)
  if (!match) return undefined
  const num = parseFloat(match[1])
  if (Number.isNaN(num)) return undefined
  const multipliers: Record<string, number> = {
    '': 1,
    b: 1,
    k: 1024,
    kb: 1024,
    m: 1024 ** 2,
    mb: 1024 ** 2,
    g: 1024 ** 3,
    gb: 1024 ** 3,
    t: 1024 ** 4,
    tb: 1024 ** 4,
  }
  const mult = multipliers[match[2].toLowerCase()]
  return mult === undefined ? undefined : Math.round(num * mult)
}
