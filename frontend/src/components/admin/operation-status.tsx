// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { StatusBadge } from '../data/status-badge'
import {
  operationLivenessPresentation,
  operationRuntimePresentation,
  operationStatePresentation,
} from '../../lib/admin-operations'
import type { AdminOperation } from '../../types/admin-operations'

export interface OperationStatusPillsProps {
  operation: Pick<
    AdminOperation,
    'kind' | 'state' | 'recovery_required' | 'liveness' | 'runtime_state'
  >
  showRuntime?: boolean
}

export function OperationStatusPills({ operation, showRuntime = true }: OperationStatusPillsProps) {
  const state = operationStatePresentation(operation.kind, operation.state)
  const liveness = operationLivenessPresentation(operation.liveness)
  const runtime = operationRuntimePresentation(operation.runtime_state)

  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="operation-status-pills">
      <StatusBadge status={state.status} label={state.label} size="sm" />
      {operation.recovery_required && operation.state !== 'recovery_required' && (
        <StatusBadge status="warning" label="Recovery required" size="sm" />
      )}
      {liveness && <StatusBadge status={liveness.status} label={liveness.label} size="sm" />}
      {showRuntime && runtime && (
        <StatusBadge status={runtime.status} label={runtime.label} size="sm" />
      )}
    </div>
  )
}
