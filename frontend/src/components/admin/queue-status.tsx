// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { StatusBadge } from '../data/status-badge'
import { queueReasonPresentation, queueStatusPresentation } from '../../lib/admin-queue'
import type { AdminQueueEntry } from '../../types/admin-queue'

export interface QueueStatusPillsProps {
  entry: Pick<AdminQueueEntry, 'status' | 'reason_code'>
}

export function QueueStatusPills({ entry }: QueueStatusPillsProps) {
  const status = queueStatusPresentation(entry.status)
  const reason = queueReasonPresentation(entry.reason_code)

  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="queue-status-pills">
      <StatusBadge status={status.tone} label={status.label} size="sm" />
      {reason && <StatusBadge status={reason.tone} label={reason.label} size="sm" />}
    </div>
  )
}
