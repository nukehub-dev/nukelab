// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import {
  ADMIN_OPERATION_REASON_MAX_LENGTH,
  adminOperationKindLabel,
  canSubmitOperationReason,
  operationReasonValidationError,
} from '../../lib/admin-operations'
import type { AdminOperationErrorInfo } from '../../lib/admin-operations'
import type { AdminOperation } from '../../types/admin-operations'
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
import { OperationErrorNotice } from './operation-error-notice'

export interface OperationReconcileDialogProps {
  operation: AdminOperation
  busy: boolean
  error: AdminOperationErrorInfo | null
  onSubmit: (reason: string) => void
  onClose: () => void
}

export function OperationReconcileDialog({
  operation,
  busy,
  error,
  onSubmit,
  onClose,
}: OperationReconcileDialogProps) {
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState<string | null>(null)
  const submitEnabled = canSubmitOperationReason(reason, busy)

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    if (busy) return
    const validation = operationReasonValidationError(reason)
    if (validation) {
      setReasonError(validation)
      return
    }
    setReasonError(null)
    onSubmit(reason.trim())
  }

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            Reconcile {adminOperationKindLabel(operation.kind).toLowerCase()} operation
          </DialogTitle>
          <DialogDescription>
            Re-run the read-only inspection for this operation. Only a proof-backed result can
            change its state; there is no force or override control.
          </DialogDescription>
        </DialogHeader>

        <form id="operation-reconcile-form" onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div className="space-y-2">
            <Label htmlFor="operation-reconcile-reason">Reason</Label>
            <Textarea
              id="operation-reconcile-reason"
              data-testid="operation-reconcile-reason"
              value={reason}
              maxLength={ADMIN_OPERATION_REASON_MAX_LENGTH}
              disabled={busy}
              rows={3}
              autoResize={false}
              placeholder="Why is this reconciliation needed?"
              aria-invalid={reasonError ? true : undefined}
              onChange={(event) => {
                setReason(event.target.value)
                if (reasonError) setReasonError(null)
              }}
            />
            {reasonError && <p className="text-xs text-destructive">{reasonError}</p>}
            <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>Recorded in the audit log. Required, 1-255 characters.</span>
              <span className="shrink-0 font-mono">
                {reason.length}/{ADMIN_OPERATION_REASON_MAX_LENGTH}
              </span>
            </div>
          </div>

          {error && <OperationErrorNotice error={error} />}
        </form>

        <DialogFooter>
          <Button variant="outline" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="operation-reconcile-form"
            data-testid="operation-reconcile-submit"
            loading={busy}
            disabled={!submitEnabled}
          >
            Re-inspect and apply
          </Button>
        </DialogFooter>
        <DialogClose onClick={onClose} />
      </DialogContent>
    </Dialog>
  )
}
