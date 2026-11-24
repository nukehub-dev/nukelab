// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import { AlertTriangle, Ban, ShieldCheck } from 'lucide-react'
import {
  canSubmitRevisionAction,
  REVISION_REASON_MAX_LENGTH,
  revisionPortabilityLabel,
  revisionReasonValidationError,
  shortRevisionId,
} from '../../lib/environment-revisions'
import type { EnvironmentRevisionErrorInfo } from '../../lib/environment-revisions'
import type { EnvironmentRevisionSummary } from '../../types/environment-revisions'
import { Button } from '../ui/button'
import { Checkbox } from '../ui/checkbox'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog'
import { Input } from '../ui/input'
import { Label } from '../ui/label'

export interface EnvironmentRevisionActionValues {
  reason: string
  confirmLastRevision: boolean
}

export interface EnvironmentRevisionActionDialogProps {
  mode: 'verify' | 'revoke'
  environmentName: string
  revision?: EnvironmentRevisionSummary | null
  busy: boolean
  error: EnvironmentRevisionErrorInfo | null
  onSubmit: (values: EnvironmentRevisionActionValues) => void
  onClose: () => void
}

export function EnvironmentRevisionActionDialog({
  mode,
  environmentName,
  revision,
  busy,
  error,
  onSubmit,
  onClose,
}: EnvironmentRevisionActionDialogProps) {
  const [reason, setReason] = useState('')
  const [reasonError, setReasonError] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState(false)

  const requiresConfirmation = error?.requiresLastRevisionConfirmation === true
  const submitEnabled = canSubmitRevisionAction({
    reason,
    busy,
    requiresConfirmation,
    confirmed,
  })
  const verifying = mode === 'verify'

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    if (busy) return
    if (requiresConfirmation && !confirmed) return
    const validation = revisionReasonValidationError(reason)
    if (validation) {
      setReasonError(validation)
      return
    }
    setReasonError(null)
    onSubmit({
      reason: reason.trim(),
      confirmLastRevision: requiresConfirmation && confirmed,
    })
  }

  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {verifying ? (
              <ShieldCheck className="h-5 w-5 text-primary" />
            ) : (
              <Ban className="h-5 w-5 text-red-400" />
            )}
            {verifying ? 'Verify current artifacts' : 'Revoke revision'}
          </DialogTitle>
          <DialogDescription>
            {verifying
              ? `Resolve the approved image references for ${environmentName} through the registry, verify the exact platform digests, and capture or reuse a revision.`
              : `Revoke revision ${revision ? shortRevisionId(revision.id) : ''} for ${environmentName}. New launches will no longer select it; existing servers and history are preserved.`}
          </DialogDescription>
        </DialogHeader>

        {revision && !verifying && (
          <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="rounded-full border border-border/50 bg-muted/50 px-2 py-0.5">
              {revisionPortabilityLabel(revision.portability)}
            </span>
            <code className="rounded-md bg-muted/50 px-1.5 py-0.5 font-mono text-[11px]">
              {revision.id}
            </code>
          </div>
        )}

        <form
          id="environment-revision-action-form"
          onSubmit={handleSubmit}
          className="mt-4 space-y-4"
        >
          <div className="space-y-2">
            <Label htmlFor="environment-revision-reason">Reason</Label>
            <Input
              id="environment-revision-reason"
              value={reason}
              maxLength={REVISION_REASON_MAX_LENGTH}
              disabled={busy}
              placeholder="Why is this action needed?"
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
                {reason.length}/{REVISION_REASON_MAX_LENGTH}
              </span>
            </div>
          </div>

          {error && (
            <div
              className={
                requiresConfirmation
                  ? 'space-y-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3'
                  : 'space-y-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3'
              }
            >
              <div
                className={
                  requiresConfirmation
                    ? 'flex items-start gap-2 text-xs text-amber-300'
                    : 'flex items-start gap-2 text-xs text-destructive'
                }
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="min-w-0 space-y-1">
                  <p className="font-medium">{error.message}</p>
                  {error.code && (
                    <code className="inline-block rounded bg-background/40 px-1.5 py-0.5 font-mono text-[10px]">
                      {error.code}
                    </code>
                  )}
                </div>
              </div>

              {requiresConfirmation && (
                <div className="space-y-3 border-t border-amber-500/20 pt-3">
                  <p className="text-xs text-amber-100/90">
                    Revoking this revision leaves {error.selectableRevisionCount} selectable
                    revision{error.selectableRevisionCount === 1 ? '' : 's'} for this environment.
                    {error.replacementAvailable
                      ? ' A replacement revision is available.'
                      : ' No replacement revision will be created.'}{' '}
                    Running servers continue, but new launches cannot select this environment until
                    artifacts are verified again.
                  </p>
                  <div className="flex items-start gap-3">
                    <Checkbox
                      id="environment-revision-confirm-last"
                      data-testid="last-revision-confirmation"
                      checked={confirmed}
                      disabled={busy}
                      aria-label="Confirm revoking the last selectable revision"
                      onChange={setConfirmed}
                      className="mt-0.5"
                    />
                    <button
                      type="button"
                      disabled={busy}
                      className="text-left text-xs text-amber-100/90 hover:text-amber-50 disabled:opacity-50"
                      onClick={() => setConfirmed((value) => !value)}
                    >
                      I understand this leaves the environment with no selectable revision and no
                      replacement.
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </form>

        <DialogFooter>
          <Button variant="outline" type="button" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="environment-revision-action-form"
            data-testid="environment-revision-action-submit"
            loading={busy}
            variant={verifying ? 'default' : 'destructive'}
            disabled={!submitEnabled}
          >
            {verifying
              ? 'Verify artifacts'
              : requiresConfirmation
                ? 'Revoke last revision'
                : 'Revoke revision'}
          </Button>
        </DialogFooter>
        <DialogClose onClick={onClose} />
      </DialogContent>
    </Dialog>
  )
}
