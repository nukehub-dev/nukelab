// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import type { BackupStatus, RestoreStatus } from '../types/volume-backup'

export function recoveryIsActive(status: BackupStatus | RestoreStatus): boolean {
  return ['pending', 'in_progress', 'deleting', 'recovery_required'].includes(status)
}

export function recoveryPollInterval(
  active: boolean,
  failures: number,
  hidden: boolean
): number | false {
  if (!active || hidden) return false
  return Math.min(30_000, 5_000 * 2 ** Math.min(failures, 3))
}

export function restoreCapacity(sizeGiB: string, minimumBytes: number): number {
  const bytes = Math.ceil(Number(sizeGiB) * 1024 ** 3)
  if (!Number.isSafeInteger(bytes) || bytes <= 0)
    throw new Error('Enter a positive size for the new volume.')
  if (bytes < minimumBytes)
    throw new Error('The new volume must fit the backup’s logical data size.')
  return bytes
}

const labels: Record<string, string> = {
  pending: 'Preparing',
  in_progress: 'Working',
  completed: 'Completed',
  failed: 'Failed',
  deleting: 'Deleting',
  deleted: 'Deleted',
  delete_failed: 'Deletion failed',
  recovery_required: 'Needs attention',
}
export function recoveryStatusLabel(status: BackupStatus | RestoreStatus): string {
  return labels[status] ?? 'Unavailable'
}

const messages: Record<string, string> = {
  recovery_disabled: 'Volume backups are not configured on this deployment.',
  backup_storage_unavailable: 'Backup storage is temporarily unavailable.',
  helper_unavailable: 'The backup service is temporarily unavailable.',
  volume_busy:
    'This volume is in use. Stop its workloads or wait for the active operation to finish.',
  backup_in_progress: 'A backup operation is already in progress. Refresh its status.',
  private_volume_required: 'Only private volumes without workspace associations can be backed up.',
  volume_not_private: 'Only private volumes without workspace associations can be backed up.',
  permission_revoked: 'You no longer have permission to perform this operation.',
  quota_exceeded: 'Your volume or backup storage quota would be exceeded.',
  artifact_missing: 'This backup’s archive is unavailable.',
  artifact_corrupt: 'Backup integrity could not be verified. No restored volume is ready for use.',
  backup_pinned: 'This backup is being restored and cannot be deleted yet.',
  restore_in_progress: 'This backup is being restored and cannot be deleted yet.',
  recovery_required:
    'The operation needs attention. Its data remains protected; do not retry it as a new operation.',
}
export function recoveryErrorMessage(error: unknown): string {
  if (error && typeof error === 'object' && ('code' in error || 'status' in error)) {
    const code = 'code' in error && typeof error.code === 'string' ? error.code : ''
    return (
      messages[code] ?? 'The operation could not be completed. Refresh its status and try again.'
    )
  }
  return error instanceof Error ? error.message : 'The backup service is temporarily unavailable.'
}
