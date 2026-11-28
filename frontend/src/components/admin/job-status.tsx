// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { StatusBadge } from '../data/status-badge'
import { adminJobReasonPresentation, adminJobStatePresentation } from '../../lib/admin-jobs'
import type { AdminJobEntry } from '../../types/admin-jobs'

export interface AdminJobStatusPillsProps {
  entry: Pick<AdminJobEntry, 'state' | 'reason_code'>
}

export function AdminJobStatusPills({ entry }: AdminJobStatusPillsProps) {
  const state = adminJobStatePresentation(entry.state)
  const reason = adminJobReasonPresentation(entry.reason_code)

  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="admin-job-status-pills">
      <StatusBadge status={state.tone} label={state.label} size="sm" />
      {reason && <StatusBadge status={reason.tone} label={reason.label} size="sm" />}
    </div>
  )
}
