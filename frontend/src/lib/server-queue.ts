// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import type { Server } from '../types/api'
import type { QueuedServerAcceptance, ServerQueueEntry } from '../types/server-queue'

export function isQueuedServer(
  result: Server | QueuedServerAcceptance
): result is QueuedServerAcceptance {
  return 'queued' in result && result.queued === true
}

export function isQueueId(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value)
  )
}

export function parseQueueSearch(search: Record<string, unknown>): {
  tab?: 'queue'
  request?: string
  deploy?: true
} {
  const deploy = search.deploy === true || search.deploy === '1' || search.deploy === 'true'
  return {
    ...(search.tab === 'queue' ? { tab: 'queue' as const } : {}),
    ...(search.tab === 'queue' && isQueueId(search.request) ? { request: search.request } : {}),
    ...(deploy ? { deploy: true as const } : {}),
  }
}

export function isQueueActive(entry: Pick<ServerQueueEntry, 'status'>): boolean {
  return entry.status === 'pending' || entry.status === 'starting' || entry.status === 'scheduled'
}

export function canCancelQueuedRequest(
  entry: Pick<ServerQueueEntry, 'status' | 'can_cancel'>
): boolean {
  return entry.status === 'pending' && entry.can_cancel
}

export function queuePollInterval(
  active: boolean,
  failures: number,
  hidden: boolean
): number | false {
  if (!active || hidden) return false
  return Math.min(60_000, 5_000 * 2 ** Math.min(Math.max(0, failures), 4))
}
