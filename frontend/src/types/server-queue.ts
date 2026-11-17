// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

export type QueueStatus = 'pending' | 'scheduled' | 'starting' | 'started' | 'failed' | 'cancelled'

export interface QueueRequestSummary {
  name: string
  plan_id: string
  environment_id: string
  resources: { cpu: number; memory_mib: number; disk_mib: number; gpu_count: number }
}

export interface QueuedServerAcceptance {
  queued: true
  queue_id: string
  queue_position: number | null
  message: string
  request: QueueRequestSummary
}

export interface ServerQueueEntry {
  id: string
  request: QueueRequestSummary
  status: QueueStatus
  position: number | null
  reason_code: string | null
  message: string
  requested_at: string | null
  expires_at: string | null
  started_at: string | null
  server_id: string | null
  can_cancel: boolean
}

export interface ServerQueuePage {
  items: ServerQueueEntry[]
  total: number
  page: number
  page_size: number
}
