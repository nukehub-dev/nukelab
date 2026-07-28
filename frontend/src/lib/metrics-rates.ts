// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Rate derivation for cumulative counters.
 *
 * Container metrics (network bytes, disk I/O bytes) are emitted as
 * monotonically increasing counters since container start. Displaying them
 * as throughput requires a delta between two samples.
 */

export interface CounterSample {
  /** Epoch milliseconds of the sample. */
  t: number
  /** Cumulative counter value. */
  value: number
}

/**
 * Per-second rate between two cumulative counter samples.
 *
 * Returns 0 when there is no previous sample, when the time gap is not
 * positive (duplicate timestamps), or when the counter did not increase
 * (container restart resets counters to 0).
 */
export function counterRate(prev: CounterSample | null, curr: CounterSample): number {
  if (!prev) return 0
  const dt = (curr.t - prev.t) / 1000
  if (dt <= 0) return 0
  const delta = curr.value - prev.value
  if (delta <= 0) return 0
  return delta / dt
}
