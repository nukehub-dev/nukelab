// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { AlertTriangle } from 'lucide-react'
import {
  operationLivenessPresentation,
  operationProofSourceLabel,
  operationReasonCodeLabel,
  operationRuntimePresentation,
  sanitizeOperationDiagnostics,
} from '../../lib/admin-operations'
import type { AdminOperationErrorInfo } from '../../lib/admin-operations'

export function OperationErrorNotice({ error }: { error: AdminOperationErrorInfo }) {
  const diagnostics = sanitizeOperationDiagnostics(error.evidence?.diagnostics)
  if (error.recoveryRequired) {
    return (
      <div
        className="space-y-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-amber-200"
        data-testid="operation-recovery-required"
      >
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 space-y-1">
            <p className="text-sm font-medium">Recovery still required</p>
            <p className="text-xs text-amber-100/90">{error.message}</p>
            <p className="text-xs text-amber-100/90">
              No mutation or reservation release occurred. The operation remains protected and is
              not retried automatically.
            </p>
          </div>
        </div>
        {error.evidence && (
          <div className="grid grid-cols-2 gap-2 border-t border-amber-500/20 pt-3 text-xs">
            <div>
              <p className="text-amber-100/70">Liveness</p>
              <p className="font-medium">
                {operationLivenessPresentation(error.evidence.liveness)?.label ?? 'Not inspected'}
              </p>
            </div>
            <div>
              <p className="text-amber-100/70">Runtime</p>
              <p className="font-medium">
                {operationRuntimePresentation(error.evidence.runtime_state)?.label ??
                  'Not inspected'}
              </p>
            </div>
            <div>
              <p className="text-amber-100/70">Proof source</p>
              <p className="font-medium">
                {operationProofSourceLabel(error.evidence.proof_source)}
              </p>
            </div>
            <div>
              <p className="text-amber-100/70">Evidence reason</p>
              <p className="font-mono text-[11px]">
                {operationReasonCodeLabel(error.evidence.reason_code)}
              </p>
            </div>
            {diagnostics.length > 0 && (
              <div className="col-span-2">
                <p className="text-amber-100/70">Sanitized diagnostics</p>
                <ul className="mt-1 space-y-1">
                  {diagnostics.map((item) => (
                    <li key={item.key} className="flex items-center justify-between gap-3">
                      <span className="text-amber-100/80">{item.label}</span>
                      <code className="rounded bg-background/30 px-1.5 py-0.5 font-mono text-[11px]">
                        {item.value}
                      </code>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-destructive">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium">Reconciliation failed</p>
          <p className="text-xs">{error.message}</p>
          {error.code && (
            <code className="inline-block rounded bg-background/40 px-1.5 py-0.5 font-mono text-[10px]">
              {error.code}
            </code>
          )}
        </div>
      </div>
    </div>
  )
}
