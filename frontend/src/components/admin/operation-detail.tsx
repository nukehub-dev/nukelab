// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { AlertTriangle, Clock, Fingerprint, RefreshCw, ShieldCheck, Wrench } from 'lucide-react'
import { useState } from 'react'
import {
  adminOperationErrorInfo,
  adminOperationKindLabel,
  adminOperationLoadErrorInfo,
  formatHeartbeatAge,
  isAdminOperationActive,
  operationActionLabel,
  operationLivenessPresentation,
  operationProofSourceLabel,
  operationReasonCodeLabel,
  operationRuntimePresentation,
  operationStateLabel,
  sanitizeOperationCounters,
  sanitizeOperationDiagnostics,
  shortOperationId,
} from '../../lib/admin-operations'
import type { AdminOperationErrorInfo, AdminOperationAccess } from '../../lib/admin-operations'
import { cn, formatDate } from '../../lib/utils'
import { useAdminOperation, useReconcileAdminOperation } from '../../hooks/use-admin-operations'
import type { AdminOperation, AdminOperationReconcileResult } from '../../types/admin-operations'
import { Button } from '../ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog'
import { Skeleton } from '../feedback/skeleton'
import { OperationStatusPills } from './operation-status'
import { OperationReconcileDialog } from './operation-reconcile-dialog'
import { OperationErrorNotice } from './operation-error-notice'

function timestamp(value: string | null): string {
  return value ? formatDate(value) : '—'
}

function DetailCard({
  icon: Icon,
  label,
  value,
  muted,
}: {
  icon: React.ElementType
  label: string
  value: React.ReactNode
  muted?: boolean
}) {
  return (
    <div className="rounded-xl border border-border/50 bg-muted/20 p-3">
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3 w-3" />
        {label}
      </div>
      <div className={cn('mt-1 text-sm font-medium', muted && 'text-muted-foreground')}>
        {value}
      </div>
    </div>
  )
}

export function OperationReconcileOutcome({ result }: { result: AdminOperationReconcileResult }) {
  const terminal = result.terminal_state
  const applied = result.applied === true
  const proofSupportsSuccess = terminal === 'succeeded' && !applied
  const alreadyTerminal = terminal === null && !applied

  let title = 'No state change applied'
  if (applied) title = 'Reconciliation applied'
  else if (alreadyTerminal) title = 'No change needed'

  let message =
    'Evidence did not produce an applicable transition. The operation remains protected.'
  if (applied) {
    message =
      'The proof-backed transition was applied. The audit log records the reason and proof source.'
  } else if (proofSupportsSuccess) {
    message =
      'Proof supports completion, but no state change was applied. Volume completion still requires the recovery service; the operation remains protected.'
  } else if (alreadyTerminal) {
    message = 'The operation was already terminal. Repeated reconciliation is a no-op.'
  }

  return (
    <section
      className={cn(
        'rounded-xl border p-4 text-sm',
        applied
          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
          : proofSupportsSuccess
            ? 'border-amber-500/30 bg-amber-500/10 text-amber-200'
            : 'border-border/60 bg-muted/30 text-foreground'
      )}
      data-testid="operation-reconcile-outcome"
    >
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-xs opacity-90">{message}</p>
      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">Applied</dt>
          <dd className="font-medium">{applied ? 'Yes' : 'No'}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Previous state</dt>
          <dd className="font-medium">{operationStateLabel(result.previous_state)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Current state</dt>
          <dd className="font-medium">{operationStateLabel(result.state)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Terminal state</dt>
          <dd className="font-medium">
            {terminal ? operationStateLabel(terminal) : 'No terminal transition'}
          </dd>
        </div>
      </dl>
    </section>
  )
}

export interface OperationDetailContentProps {
  operation: AdminOperation
  canManage: boolean
  onReconcile?: () => void
  outcome?: AdminOperationReconcileResult | null
  error?: AdminOperationErrorInfo | null
  loading?: boolean
  loadError?: AdminOperationErrorInfo | null
}

export function OperationDetailContent({
  operation,
  canManage,
  onReconcile,
  outcome,
  error,
  loading,
  loadError,
}: OperationDetailContentProps) {
  const active = isAdminOperationActive(operation.kind, operation.state)
  const liveness = operationLivenessPresentation(operation.liveness)
  const runtime = operationRuntimePresentation(operation.runtime_state)
  const diagnostics = sanitizeOperationDiagnostics(operation.diagnostics)
  const counters = sanitizeOperationCounters(operation.counters)

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-primary/10 p-2.5 text-primary">
          <Wrench className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold leading-tight">
            {adminOperationKindLabel(operation.kind)} operation
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            <span className="font-mono">{shortOperationId(operation.id)}</span>
            {operation.action ? ` · ${operationActionLabel(operation.action)}` : ''}
            {operation.owner_id ? ` · owner ${shortOperationId(operation.owner_id)}` : ''}
          </p>
        </div>
      </div>

      <OperationStatusPills operation={operation} />

      {operation.recovery_required && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <p>
              This operation needs operator review. Ambiguous work is not retried automatically, and
              a live worker is not failed from runtime health alone.
            </p>
          </div>
        </div>
      )}

      {loading && (
        <div className="space-y-2">
          <Skeleton className="h-16 w-full rounded-xl" />
          <Skeleton className="h-16 w-full rounded-xl" />
        </div>
      )}

      {loadError && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
          <p className="font-medium">Could not refresh evidence</p>
          <p className="mt-1">{loadError.message}</p>
          {loadError.code && (
            <code className="mt-1 inline-block rounded bg-background/40 px-1.5 py-0.5 font-mono text-[10px]">
              {loadError.code}
            </code>
          )}
        </div>
      )}

      {outcome && <OperationReconcileOutcome result={outcome} />}
      {error && <OperationErrorNotice error={error} />}

      <section className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <DetailCard
          icon={ShieldCheck}
          label="Liveness"
          value={liveness?.label ?? 'Not inspected'}
          muted={!liveness}
        />
        <DetailCard
          icon={Fingerprint}
          label="Proof source"
          value={operationProofSourceLabel(operation.proof_source)}
          muted={!operation.proof_source}
        />
        <DetailCard
          icon={RefreshCw}
          label="Runtime"
          value={runtime?.label ?? 'Not inspected'}
          muted={!runtime}
        />
        <DetailCard
          icon={Clock}
          label="Heartbeat age"
          value={
            operation.heartbeat_age_seconds === null
              ? 'No heartbeat'
              : formatHeartbeatAge(operation.heartbeat_age_seconds)
          }
          muted={operation.heartbeat_age_seconds === null}
        />
      </section>

      <section className="rounded-xl border border-border/50">
        <div className="border-b border-border/40 px-4 py-2.5">
          <h4 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            State and timestamps
          </h4>
        </div>
        <dl className="divide-y divide-border/30 text-sm">
          <div className="flex items-center justify-between gap-4 px-4 py-2.5">
            <dt className="text-xs text-muted-foreground">Current state</dt>
            <dd className="font-medium">{operationStateLabel(operation.state)}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-4 py-2.5">
            <dt className="text-xs text-muted-foreground">Evidence reason</dt>
            <dd className="font-mono text-xs">
              {operationReasonCodeLabel(operation.evidence_reason_code ?? operation.reason_code)}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-4 py-2.5">
            <dt className="text-xs text-muted-foreground">Created</dt>
            <dd className="text-xs">{timestamp(operation.created_at)}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-4 py-2.5">
            <dt className="text-xs text-muted-foreground">Updated</dt>
            <dd className="text-xs">{timestamp(operation.updated_at)}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-4 py-2.5">
            <dt className="text-xs text-muted-foreground">Finished</dt>
            <dd className="text-xs">{timestamp(operation.finished_at)}</dd>
          </div>
        </dl>
      </section>

      {diagnostics.length > 0 && (
        <section className="rounded-xl border border-border/50">
          <div className="border-b border-border/40 px-4 py-2.5">
            <h4 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Sanitized diagnostics
            </h4>
          </div>
          <ul className="divide-y divide-border/30 text-sm">
            {diagnostics.map((item) => (
              <li key={item.key} className="flex items-center justify-between gap-4 px-4 py-2.5">
                <span className="text-xs text-muted-foreground">{item.label}</span>
                <code className="rounded bg-muted/50 px-1.5 py-0.5 font-mono text-[11px]">
                  {item.value}
                </code>
              </li>
            ))}
          </ul>
        </section>
      )}

      {counters.length > 0 && (
        <section className="rounded-xl border border-border/50">
          <div className="border-b border-border/40 px-4 py-2.5">
            <h4 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Counters
            </h4>
          </div>
          <ul className="divide-y divide-border/30 text-sm">
            {counters.map((item) => (
              <li key={item.key} className="flex items-center justify-between gap-4 px-4 py-2.5">
                <span className="text-xs text-muted-foreground">{item.label}</span>
                <span className="font-mono text-xs">{item.value}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="rounded-xl border border-border/50 bg-muted/20 p-3 text-xs text-muted-foreground">
        Reconciliation runs the same read-only inspection and applies only a proof-backed terminal
        result. There is no force or override control, and no reservation is released from operator
        assertion alone.
      </div>

      {active ? (
        canManage ? (
          <Button type="button" className="w-full gap-2" onClick={onReconcile}>
            <Wrench className="h-4 w-4" />
            Reconcile operation
          </Button>
        ) : (
          <p className="text-xs text-muted-foreground">
            Reconcile requires operations manage and admin access.
          </p>
        )
      ) : (
        <p className="text-xs text-muted-foreground">
          Terminal operations are immutable; reconciliation would be a no-op.
        </p>
      )}
    </div>
  )
}

export interface OperationDetailDrawerProps {
  selected: AdminOperation
  access: AdminOperationAccess
  onClose: () => void
}

export function OperationDetailDrawer({ selected, access, onClose }: OperationDetailDrawerProps) {
  const detailQuery = useAdminOperation(selected.kind, selected.id)
  const reconcile = useReconcileAdminOperation()
  const [reconcileOpen, setReconcileOpen] = useState(false)
  const [outcome, setOutcome] = useState<AdminOperationReconcileResult | null>(null)
  const [actionError, setActionError] = useState<AdminOperationErrorInfo | null>(null)

  const operation = detailQuery.data ?? selected
  const loadError = detailQuery.isError ? adminOperationLoadErrorInfo(detailQuery.error) : null

  const openReconcile = () => {
    reconcile.reset()
    setActionError(null)
    setOutcome(null)
    setReconcileOpen(true)
  }

  const closeReconcile = () => {
    if (reconcile.isPending) return
    setReconcileOpen(false)
  }

  return (
    <>
      <Dialog open onOpenChange={(next) => !next && onClose()}>
        <DialogContent className="space-y-5">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Wrench className="h-5 w-5 text-primary" />
              Operation evidence
            </DialogTitle>
            <DialogDescription>
              Sanitized durable metadata and runtime evidence. Request payloads, mounts, environment
              values, tokens, and raw inspection output are never shown.
            </DialogDescription>
          </DialogHeader>

          <OperationDetailContent
            operation={operation}
            canManage={access.canManage}
            onReconcile={openReconcile}
            outcome={outcome}
            error={actionError}
            loading={detailQuery.isLoading}
            loadError={loadError}
          />

          <DialogClose onClick={onClose} />
        </DialogContent>
      </Dialog>

      {reconcileOpen && (
        <OperationReconcileDialog
          operation={operation}
          busy={reconcile.isPending}
          error={actionError}
          onSubmit={(reason) => {
            setActionError(null)
            reconcile.mutate(
              { kind: operation.kind, id: operation.id, reason },
              {
                onSuccess: (result) => {
                  setActionError(null)
                  setOutcome(result)
                  setReconcileOpen(false)
                },
                onError: (error) => {
                  setOutcome(null)
                  setActionError(adminOperationErrorInfo(error))
                },
              }
            )
          }}
          onClose={closeReconcile}
        />
      )}
    </>
  )
}
