// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import { AlertTriangle, Inbox, RefreshCw, ShieldCheck } from 'lucide-react'
import {
  environmentRevisionAccess,
  environmentRevisionErrorInfo,
  hasNoSelectableRevision,
  revisionPortabilityLabel,
  shortRevisionId,
} from '../../lib/environment-revisions'
import type { EnvironmentRevisionErrorInfo } from '../../lib/environment-revisions'
import { cn } from '../../lib/utils'
import { useAuthStore } from '../../stores/auth-store'
import { useToast } from '../../stores/toast-store'
import type { Environment } from '../../types/api'
import type { EnvironmentRevisionSummary } from '../../types/environment-revisions'
import {
  useEnvironmentRevisionActions,
  useEnvironmentRevisions,
} from '../../hooks/use-environment-revisions'
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
import { EnvironmentRevisionCard } from './environment-revision-card'
import {
  EnvironmentRevisionActionDialog,
  type EnvironmentRevisionActionValues,
} from './environment-revision-action-dialog'

const REVISION_PAGE_SIZE = 10

type RevisionOutcome =
  | { kind: 'verify'; revision: EnvironmentRevisionSummary }
  | {
      kind: 'revoke'
      revision: EnvironmentRevisionSummary
      selectableRevisionCount: number
      alreadyRevoked: boolean
    }

function RevisionActionOutcome({
  outcome,
  onVerify,
}: {
  outcome: RevisionOutcome
  onVerify: () => void
}) {
  if (outcome.kind === 'verify') {
    const portable = outcome.revision.portability === 'registry_verified'
    return (
      <div
        className={cn(
          'rounded-xl border p-3 text-xs',
          portable
            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
            : 'border-amber-500/30 bg-amber-500/10 text-amber-200'
        )}
      >
        <p className="font-medium">
          Artifacts verified · revision {shortRevisionId(outcome.revision.id)}
        </p>
        <p className={cn('mt-1', portable ? 'text-emerald-100/90' : 'text-amber-100/90')}>
          {portable
            ? 'The revision is registry verified and portable.'
            : `The revision remains ${revisionPortabilityLabel(outcome.revision.portability).toLowerCase()}. Review its limitations below before relying on it for another installation.`}
        </p>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'rounded-xl border p-3 text-xs',
        outcome.selectableRevisionCount > 0
          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
          : 'border-amber-500/30 bg-amber-500/10 text-amber-200'
      )}
    >
      <p className="font-medium">
        {outcome.alreadyRevoked ? 'Revision was already revoked' : 'Revision revoked'} ·{' '}
        {shortRevisionId(outcome.revision.id)}
      </p>
      <p className="mt-1">Selectable revisions remaining: {outcome.selectableRevisionCount}</p>
      {outcome.selectableRevisionCount === 0 && (
        <div className="mt-2 space-y-2">
          <p>No replacement revision was created. Running servers are not stopped.</p>
          <Button type="button" size="sm" variant="outline" onClick={onVerify}>
            <ShieldCheck className="h-3.5 w-3.5" />
            Verify current artifacts
          </Button>
        </div>
      )}
    </div>
  )
}

function RevisionErrorState({
  error,
  onRetry,
}: {
  error: EnvironmentRevisionErrorInfo
  onRetry: () => void
}) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4">
      <div className="flex items-start gap-2 text-sm text-destructive">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0 space-y-1">
          <p className="font-medium">Could not load revisions</p>
          <p className="text-xs">{error.message}</p>
          {error.code && (
            <code className="inline-block rounded bg-background/40 px-1.5 py-0.5 font-mono text-[10px]">
              {error.code}
            </code>
          )}
        </div>
      </div>
      <Button type="button" size="sm" variant="outline" className="mt-3" onClick={onRetry}>
        Retry
      </Button>
    </div>
  )
}

export interface EnvironmentRevisionsPanelProps {
  environment: Environment
  onClose: () => void
}

export function EnvironmentRevisionsPanel({
  environment,
  onClose,
}: EnvironmentRevisionsPanelProps) {
  const { success, warning } = useToast()
  const hasAllPermissions = useAuthStore((state) => state.hasAllPermissions)
  const { canRead, canManage } = environmentRevisionAccess(hasAllPermissions)
  const [offset, setOffset] = useState(0)
  const [dialogMode, setDialogMode] = useState<'verify' | 'revoke' | null>(null)
  const [selectedRevision, setSelectedRevision] = useState<EnvironmentRevisionSummary | null>(null)
  const [actionError, setActionError] = useState<EnvironmentRevisionErrorInfo | null>(null)
  const [highlightRevisionId, setHighlightRevisionId] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<RevisionOutcome | null>(null)

  const revisionsQuery = useEnvironmentRevisions({
    environmentId: environment.id,
    limit: REVISION_PAGE_SIZE,
    offset,
    enabled: canRead,
  })
  const { verifyArtifacts, revokeRevision } = useEnvironmentRevisionActions(environment.id)

  const revisions = revisionsQuery.data?.items ?? []
  const verifiedCount = revisions.filter(
    (revision) => revision.portability === 'registry_verified' && !revision.revoked
  ).length
  const localOnlyCount = revisions.filter(
    (revision) => revision.portability === 'local_only' && !revision.revoked
  ).length
  const revokedCount = revisions.filter((revision) => revision.revoked).length
  const pagination = revisionsQuery.data?.pagination
  const listError = revisionsQuery.isError
    ? environmentRevisionErrorInfo(revisionsQuery.error)
    : null
  const noSelectableLoaded = hasNoSelectableRevision(
    revisions,
    !!pagination && revisions.length >= pagination.total
  )
  const showNoSelectable =
    outcome?.kind !== 'verify' &&
    (noSelectableLoaded || (outcome?.kind === 'revoke' && outcome.selectableRevisionCount === 0))

  const closeActionDialog = () => {
    setDialogMode(null)
    setSelectedRevision(null)
    setActionError(null)
  }

  const openVerifyDialog = () => {
    verifyArtifacts.reset()
    revokeRevision.reset()
    setSelectedRevision(null)
    setActionError(null)
    setDialogMode('verify')
  }

  const openRevokeDialog = (revision: EnvironmentRevisionSummary) => {
    verifyArtifacts.reset()
    revokeRevision.reset()
    setSelectedRevision(revision)
    setActionError(null)
    setDialogMode('revoke')
  }

  const handleActionSubmit = ({ reason, confirmLastRevision }: EnvironmentRevisionActionValues) => {
    if (dialogMode === 'verify') {
      verifyArtifacts.mutate(reason, {
        onSuccess: (response) => {
          setOffset(0)
          setHighlightRevisionId(response.data.id)
          setOutcome({ kind: 'verify', revision: response.data })
          closeActionDialog()
          if (response.data.portability === 'registry_verified') {
            success(
              'Artifacts verified',
              `Revision ${shortRevisionId(response.data.id)} is registry verified.`
            )
          } else {
            warning(
              'Artifacts verified locally',
              'The captured revision remains local only. Review its limitations.'
            )
          }
        },
        onError: (error) => {
          setActionError(environmentRevisionErrorInfo(error))
        },
      })
      return
    }

    if (dialogMode !== 'revoke' || !selectedRevision) return
    revokeRevision.mutate(
      {
        revisionId: selectedRevision.id,
        reason,
        confirmLastRevision: confirmLastRevision === true,
      },
      {
        onSuccess: (response) => {
          setOutcome({
            kind: 'revoke',
            revision: response.data,
            selectableRevisionCount: response.selectable_revision_count,
            alreadyRevoked: response.already_revoked,
          })
          closeActionDialog()
          success(
            response.already_revoked ? 'Revision already revoked' : 'Revision revoked',
            `${response.selectable_revision_count} selectable revision${
              response.selectable_revision_count === 1 ? '' : 's'
            } remain.`
          )
        },
        onError: (error) => {
          setActionError(environmentRevisionErrorInfo(error))
        },
      }
    )
  }

  const actionBusy = verifyArtifacts.isPending || revokeRevision.isPending

  return (
    <>
      <Dialog open onOpenChange={(next) => !next && onClose()}>
        <DialogContent className="space-y-5">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-primary" />
              Environment revisions
            </DialogTitle>
            <DialogDescription>
              Sanitized, immutable history for {environment.name}. Environment-variable values and
              host paths are never shown.
            </DialogDescription>
          </DialogHeader>

          {!canRead ? (
            <div className="rounded-xl border border-border/60 bg-muted/30 p-4 text-sm text-muted-foreground">
              You do not have permission to view environment revisions.
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-emerald-400">
                  Verified {verifiedCount}
                </span>
                <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-amber-400">
                  Local only {localOnlyCount}
                </span>
                <span className="rounded-full border border-red-500/20 bg-red-500/10 px-2 py-0.5 text-red-400">
                  Revoked {revokedCount}
                </span>
                <span className="text-muted-foreground">On this page</span>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">
                  Newest first · immutable history · revoked revisions stay visible
                </p>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => void revisionsQuery.refetch()}
                    disabled={revisionsQuery.isFetching}
                  >
                    <RefreshCw
                      className={cn('h-3.5 w-3.5', revisionsQuery.isFetching && 'animate-spin')}
                    />
                    Refresh
                  </Button>
                  {canManage && (
                    <Button type="button" size="sm" onClick={openVerifyDialog}>
                      <ShieldCheck className="h-3.5 w-3.5" />
                      Verify current artifacts
                    </Button>
                  )}
                </div>
              </div>

              {outcome && <RevisionActionOutcome outcome={outcome} onVerify={openVerifyDialog} />}

              {showNoSelectable && (
                <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
                  <div className="flex items-start gap-2">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    <div className="space-y-1">
                      <p className="font-medium">No selectable revision remains</p>
                      <p>
                        New launches cannot select this environment until artifacts are verified and
                        a new revision is captured. Running servers are not stopped.
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {revisionsQuery.isLoading ? (
                <div className="space-y-3">
                  <Skeleton className="h-44 w-full rounded-xl" />
                  <Skeleton className="h-44 w-full rounded-xl" />
                </div>
              ) : listError ? (
                <RevisionErrorState
                  error={listError}
                  onRetry={() => void revisionsQuery.refetch()}
                />
              ) : revisions.length === 0 ? (
                <div className="rounded-xl border border-dashed border-border/60 p-8 text-center">
                  <Inbox className="mx-auto h-7 w-7 text-muted-foreground" />
                  <p className="mt-2 text-sm font-medium">No revisions captured yet</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Launch or verify this environment to capture its first immutable revision.
                  </p>
                  {canManage && (
                    <Button type="button" size="sm" className="mt-3" onClick={openVerifyDialog}>
                      <ShieldCheck className="h-3.5 w-3.5" />
                      Verify current artifacts
                    </Button>
                  )}
                </div>
              ) : (
                <div className="space-y-3">
                  {revisions.map((revision) => (
                    <EnvironmentRevisionCard
                      key={revision.id}
                      revision={revision}
                      canManage={canManage}
                      highlighted={highlightRevisionId === revision.id}
                      onRevoke={openRevokeDialog}
                    />
                  ))}
                </div>
              )}

              {pagination && pagination.total > 0 && (
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 pt-3 text-xs text-muted-foreground">
                  <span>
                    Showing {pagination.offset + 1}-
                    {Math.min(pagination.offset + revisions.length, pagination.total)} of{' '}
                    {pagination.total}
                  </span>
                  <div className="flex items-center gap-2">
                    {pagination.offset > 0 && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => setOffset(0)}
                      >
                        Newest first
                      </Button>
                    )}
                    {pagination.has_more && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => setOffset(offset + REVISION_PAGE_SIZE)}
                      >
                        Load more
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          <DialogClose onClick={onClose} />
        </DialogContent>
      </Dialog>

      {dialogMode && (
        <EnvironmentRevisionActionDialog
          mode={dialogMode}
          environmentName={environment.name}
          revision={selectedRevision}
          busy={actionBusy}
          error={actionError}
          onSubmit={handleActionSubmit}
          onClose={closeActionDialog}
        />
      )}
    </>
  )
}
