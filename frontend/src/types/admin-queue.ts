// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

export type AdminQueueStatus =
  | 'pending'
  | 'scheduled'
  | 'starting'
  | 'started'
  | 'failed'
  | 'cancelled'

/**
 * One sanitized queue request returned by the read-only admin queue API.
 * Request payloads, claim tokens, mounts, environment values, plan snapshots,
 * and raw failure text are never part of this contract.
 */
export interface AdminQueueEntry {
  id: string
  owner_id: string
  server_id: string | null
  server_name: string
  environment_id: string
  plan_id: string
  status: AdminQueueStatus
  reason_code: string | null
  position: number | null
  priority: number
  requested_at: string | null
  started_at: string | null
  failed_at: string | null
  expires_at: string | null
}

export interface AdminQueuePagination {
  limit: number
  offset: number
  total: number
  has_more: boolean
}

export interface AdminQueuePage {
  items: AdminQueueEntry[]
  pagination: AdminQueuePagination
}

export interface AdminQueueFilters {
  statuses?: readonly AdminQueueStatus[] | null
  owner_id?: string | null
  age_days?: number | null
  older_than?: string | null
  recovery_required?: boolean | null
  limit?: number
  offset?: number
}

export type AdminQueueRecoveryFilter = 'all' | 'required' | 'not_required'
