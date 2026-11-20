// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

export interface RecoveryCapability {
  enabled: boolean
  reason_code: string | null
  message: string
}

export interface BackupEligibility {
  eligible: boolean
  reason_code: string | null
  message: string
}

export type BackupStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'failed'
  | 'deleting'
  | 'deleted'
  | 'delete_failed'
  | 'recovery_required'
export type RestoreStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'recovery_required'

export interface VolumeBackup {
  id: string
  source_volume_id: string | null
  source_display_name: string
  status: BackupStatus
  reason_code: string | null
  message: string
  description: string | null
  created_at: string
  completed_at: string | null
  expires_at: string | null
  compressed_bytes: number | null
  logical_bytes: number | null
  member_count: number | null
  can_restore: boolean
  can_delete: boolean
}

export interface VolumeBackupPage {
  items: VolumeBackup[]
  total: number
  page: number
  page_size: number
}

export interface VolumeRestore {
  id: string
  backup_id: string
  status: RestoreStatus
  reason_code: string | null
  message: string
  destination_volume_id: string | null
  destination_display_name: string
  created_at: string
  completed_at: string | null
}

export interface CreateBackupRequest {
  request_id: string
  description?: string
}

export interface RestoreBackupRequest {
  request_id: string
  display_name: string
  max_size_bytes: number
}

export interface VolumeRestorePage {
  items: VolumeRestore[]
  total: number
  page: number
  page_size: number
}
