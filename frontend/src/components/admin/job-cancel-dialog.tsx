// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import { AlertTriangle, CheckCircle2, Clock, ShieldCheck } from 'lucide-react'
import {
  ADMIN_JOB_REASON_MAX_LENGTH,
  ADMIN_JOB_REASON_MIN_LENGTH,
  adminJobReasonValidationError,
  adminJobStatePresentation,
  canSubmitAdminJobReason,
  normalizeAdminJobReason,
  shortAdminJobReference,
} from '../../lib/admin-jobs'
import type { AdminJobErrorInfo } from '../../lib/admin-jobs'
import type { AdminJobCancelResult, AdminJobEntry } from '../../types/admin-jobs'
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

function CancelErrorNotice({ error }: { error: AdminJobErrorInfo }) {
  const notCancellable = error.code === 'job_not_cancellable'
  const title = notCancellable ? 'Recovery-only job' : 'Cancellation failed'

  return (
    <div
      role="alert"
      data-testid="admin-job-cancel-error"
      className={
        notCancellable
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

export interface AdminJobCancelDialogProps {
  entry: AdminJobEntry
  busy: boolean
  error: AdminJobErrorInfo | null
  onSubmit: (reason: string) => void
  onClose: () => void
}

export function AdminJobCancelDialog({
  entry,
  busy,
  error,
  onSubmit,
  onClose,
}: AdminJobCancelDialogProps) {
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
      <DialogContent data-testid="admin-job-cancel-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Clock className="h-5 w-5 text-primary" />
            Cancel batch job
          </DialogTitle>
          <DialogDescription>
            Record a reason and request cancellation for job{' '}
            <span className="font-mono text-foreground">{shortAdminJobReference(entry.id)}</span>.
            The server decides the safe transition from the current state.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>Current state</span>
          <AdminJobStatusPills entry={entry} />
        </div>

        <div className="mt-4 flex items-start gap-2 rounded-xl border border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <p>
            A queued job cancels immediately. A starting or running job records a stop request and
            stops only after verified runtime termination. Cancellation never force-releases a
            reservation, volume guard, or credit hold. Recovery-required jobs use proof-backed
            reconcile instead.
          </p>
        </div>

        <form id="admin-job-cancel-form" onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div className="space-y-2">
            <Label htmlFor="admin-job-cancel-reason">Reason</Label>
            <Textarea
              id="admin-job-cancel-reason"
              data-testid="admin-job-cancel-reason"
              value={reason}
              minLength={ADMIN_JOB_REASON_MIN_LENGTH}
              maxLength={ADMIN_JOB_REASON_MAX_LENGTH}
              disabled={busy}
              rows={3}
              autoResize={false}
              placeholder="Why is this cancellation needed?"
              aria-invalid={reasonError ? true : undefined}
              aria-describedby="admin-job-cancel-reason-help"
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
              id="admin-job-cancel-reason-help"
              className="flex items-center justify-between gap-2 text-xs text-muted-foreground"
            >
              <span>
                Recorded in the audit log and sent to the owner. Required,{' '}
                {ADMIN_JOB_REASON_MIN_LENGTH}-{ADMIN_JOB_REASON_MAX_LENGTH} characters.
              </span>
              <span className="shrink-0 font-mono">
                {reason.length}/{ADMIN_JOB_REASON_MAX_LENGTH}
              </span>
            </div>
          </div>

          {error && <CancelErrorNotice error={error} />}
        </form>

        <DialogFooter>
          <Button variant="outline" type="button" onClick={onClose} disabled={busy}>
            Keep job
          </Button>
          <Button
            type="submit"
            form="admin-job-cancel-form"
            data-testid="admin-job-cancel-submit"
            variant="destructive"
            loading={busy}
            disabled={!submitEnabled}
          >
            Request cancellation
          </Button>
        </DialogFooter>
        <DialogClose onClick={onClose} />
      </DialogContent>
    </Dialog>
  )
}

export function AdminJobCancelOutcome({
  result,
  onDismiss,
}: {
  result: AdminJobCancelResult
  onDismiss?: () => void
}) {
  const cancelled = result.outcome === 'cancelled'
  const requested = result.outcome === 'cancellation_requested'
  const alreadyTerminal = result.outcome === 'already_terminal'
  const title = cancelled
    ? 'Job cancelled'
    : requested
      ? 'Cancellation requested'
      : alreadyTerminal
        ? 'Already terminal'
        : 'Cancellation already requested'
  const message = cancelled
    ? 'The queued job was cancelled before runtime. Any credit hold for it was released in full.'
    : requested
      ? 'The job will stop only after verified runtime termination. Its reservation, volume guard, and credit hold remain in place until the terminal result.'
      : alreadyTerminal
        ? 'The job had already finished. No change was applied.'
        : 'No further change was applied. The job remains protected until runtime proof.'

  return (
    <section
      role="status"
      data-testid="admin-job-cancel-outcome"
      className={
        cancelled || requested
          ? 'rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-emerald-200'
          : 'rounded-xl border border-border/60 bg-muted/30 p-4 text-foreground'
      }
    >
      <div className="flex items-start gap-2">
        {cancelled || requested ? (
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
              <dt className="text-muted-foreground">Previous state</dt>
              <dd className="font-medium">
                {result.previous_state
                  ? adminJobStatePresentation(result.previous_state).label
                  : 'Unknown'}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Current state</dt>
              <dd className="font-medium">{adminJobStatePresentation(result.job.state).label}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Protection</dt>
              <dd className="font-medium">
                {result.job.reservation_active || result.job.guard_active ? 'Retained' : 'Not held'}
              </dd>
            </div>
          </dl>
        </div>
        {onDismiss && (
          <Button type="button" size="sm" variant="ghost" onClick={onDismiss}>
            Dismiss
          </Button>
        )}
      </div>
    </section>
  )
}
