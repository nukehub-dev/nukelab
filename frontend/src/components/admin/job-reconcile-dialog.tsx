// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import { AlertTriangle, CheckCircle2, ShieldCheck } from 'lucide-react'
import {
  ADMIN_JOB_REASON_MAX_LENGTH,
  ADMIN_JOB_REASON_MIN_LENGTH,
  adminJobProofSourceLabel,
  adminJobReasonValidationError,
  adminJobStatePresentation,
  canSubmitAdminJobReason,
  normalizeAdminJobReason,
  shortAdminJobReference,
} from '../../lib/admin-jobs'
import type { AdminJobReconcileErrorInfo } from '../../lib/admin-jobs'
import type { AdminJobEntry, AdminJobReconcileResult } from '../../types/admin-jobs'
import { Button } from '../ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog'
import { Label } from '../ui/label'
import { Textarea } from '../ui/textarea'
import { AdminJobStatusPills } from './job-status'

function ReconcileErrorNotice({ error }: { error: AdminJobReconcileErrorInfo }) {
  const proofInsufficient = error.code === 'proof_insufficient'
  const notReconcilable = error.code === 'job_not_reconcilable'
  const title = proofInsufficient
    ? 'Proof still insufficient'
    : notReconcilable
      ? 'Job not reconcilable'
      : 'Reconciliation failed'

  return (
    <div
      role="alert"
      data-testid="admin-job-reconcile-error"
      className={
        proofInsufficient
          ? 'rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-amber-200'
          : 'rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-destructive'
      }
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium">{title}</p>
          <p className="text-xs">{error.message}</p>
        </div>
      </div>
    </div>
  )
}

export interface AdminJobReconcileDialogProps {
  entry: AdminJobEntry
  busy: boolean
  error: AdminJobReconcileErrorInfo | null
  onSubmit: (reason: string) => void
  onClose: () => void
}

export function AdminJobReconcileDialog({
  entry,
  busy,
  error,
  onSubmit,
  onClose,
}: AdminJobReconcileDialogProps) {
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState<string | null>(null)
  const submitEnabled = canSubmitAdminJobReason(reason, busy)

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    if (busy) return
    const validation = adminJobReasonValidationError(reason)
    if (validation) {
      setReasonError(validation)
      return
    }
    setReasonError(null)
    onSubmit(normalizeAdminJobReason(reason))
  }

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent data-testid="admin-job-reconcile-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            Reconcile batch job
          </DialogTitle>
          <DialogDescription>
            Re-run the read-only proof inspection for job{' '}
            <span className="font-mono text-foreground">{shortAdminJobReference(entry.id)}</span>.
            Only runtime proof can change its state.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>Current state</span>
          <AdminJobStatusPills entry={entry} />
        </div>

        <div className="mt-4 flex items-start gap-2 rounded-xl border border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
          <p>
            This cannot force a state, retry the job, or release a reservation or volume guard.
            Ambiguous evidence changes nothing and leaves the job protected.
          </p>
        </div>

        <form id="admin-job-reconcile-form" onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div className="space-y-2">
            <Label htmlFor="admin-job-reconcile-reason">Reason</Label>
            <Textarea
              id="admin-job-reconcile-reason"
              data-testid="admin-job-reconcile-reason"
              value={reason}
              minLength={ADMIN_JOB_REASON_MIN_LENGTH}
              maxLength={ADMIN_JOB_REASON_MAX_LENGTH}
              disabled={busy}
              rows={3}
              autoResize={false}
              placeholder="Why is this reconciliation needed?"
              aria-invalid={reasonError ? true : undefined}
              aria-describedby="admin-job-reconcile-reason-help"
              onChange={(event) => {
                setReason(event.target.value)
                if (reasonError) setReasonError(null)
              }}
            />
            {reasonError && (
              <p className="text-xs text-destructive" role="alert">
                {reasonError}
              </p>
            )}
            <div
              id="admin-job-reconcile-reason-help"
              className="flex items-center justify-between gap-2 text-xs text-muted-foreground"
            >
              <span>
                Recorded in the audit log. Required, {ADMIN_JOB_REASON_MIN_LENGTH}-
                {ADMIN_JOB_REASON_MAX_LENGTH} characters.
              </span>
              <span className="shrink-0 font-mono">
                {reason.length}/{ADMIN_JOB_REASON_MAX_LENGTH}
              </span>
            </div>
          </div>

          {error && <ReconcileErrorNotice error={error} />}
        </form>

        <DialogFooter>
          <Button variant="outline" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="admin-job-reconcile-form"
            data-testid="admin-job-reconcile-submit"
            loading={busy}
            disabled={!submitEnabled}
          >
            Re-inspect and reconcile
          </Button>
        </DialogFooter>
        <DialogClose onClick={onClose} />
      </DialogContent>
    </Dialog>
  )
}

export function AdminJobReconcileOutcome({
  result,
  onDismiss,
}: {
  result: AdminJobReconcileResult
  onDismiss?: () => void
}) {
  const applied = result.outcome === 'applied'
  const alreadyTerminal = result.outcome === 'already_terminal'
  const title = applied
    ? 'Reconciliation applied'
    : alreadyTerminal
      ? 'Already terminal'
      : 'No change applied'
  const message = applied
    ? 'A proof-backed terminal state was applied. The refreshed row reflects the server result.'
    : alreadyTerminal
      ? 'The job was already terminal. Repeated reconciliation made no change.'
      : 'Proof did not support a terminal transition. The job remains protected; no reservation or volume guard was released.'

  return (
    <section
      role="status"
      data-testid="admin-job-reconcile-outcome"
      className={
        applied
          ? 'rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-emerald-200'
          : alreadyTerminal
            ? 'rounded-xl border border-border/60 bg-muted/30 p-4 text-foreground'
            : 'rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-amber-200'
      }
    >
      <div className="flex items-start gap-2">
        {applied ? (
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
        ) : (
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        )}
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-sm font-medium">{title}</p>
          <p className="text-xs opacity-90">{message}</p>
          <dl className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <div>
              <dt className="text-muted-foreground">Job</dt>
              <dd className="font-mono">{shortAdminJobReference(result.job.id)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Current state</dt>
              <dd className="font-medium">{adminJobStatePresentation(result.job.state).label}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Terminal state</dt>
              <dd className="font-medium">
                {result.terminal_state
                  ? adminJobStatePresentation(result.terminal_state).label
                  : 'No terminal transition'}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Proof source</dt>
              <dd className="font-medium">{adminJobProofSourceLabel(result.proof_source)}</dd>
            </div>
          </dl>
        </div>
        {onDismiss && (
          <Button variant="ghost" size="sm" type="button" onClick={onDismiss}>
            Dismiss
          </Button>
        )}
      </div>
    </section>
  )
}
