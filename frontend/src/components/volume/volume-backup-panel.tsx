// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useRef, useState, type FormEvent } from 'react'
import { Link } from '@tanstack/react-router'
import {
  AlertTriangle,
  Archive,
  CalendarClock,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  Database,
  DatabaseBackup,
  HardDrive,
  History,
  Info,
  Loader2,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Trash2,
  type LucideIcon,
} from 'lucide-react'
import {
  useBackupEligibility,
  useRecoveryActions,
  useRecoveryCapabilities,
  useVolumeBackups,
  useVolumeRestores,
} from '../../hooks/use-volume-backups'
import { recoveryErrorMessage, recoveryStatusLabel, restoreCapacity } from '../../lib/volume-backup'
import { cn, formatBytes, formatDate } from '../../lib/utils'
import { PERMISSIONS, useAuthStore } from '../../stores/auth-store'
import { useToastStore } from '../../stores/toast-store'
import type { BackupStatus, RestoreStatus, VolumeBackup } from '../../types/volume-backup'
import { StatusBadge } from '../data/status-badge'
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
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Textarea } from '../ui/textarea'
import { useConfirmDialog } from '../ui/confirm-dialog'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  volumeId?: string
  volumeName?: string
}

type StatusTone = 'healthy' | 'pending' | 'stopped' | 'error' | 'warning'

const statusTones: Record<BackupStatus | RestoreStatus, StatusTone> = {
  pending: 'pending',
  in_progress: 'pending',
  completed: 'healthy',
  failed: 'error',
  deleting: 'pending',
  deleted: 'stopped',
  delete_failed: 'error',
  recovery_required: 'warning',
}

export function VolumeBackupPanel({ open, onOpenChange, volumeId, volumeName }: Props) {
  const owner = useAuthStore((state) => state.user?.id)
  return open && owner ? (
    <RecoveryHistory
      key={`${owner}:${volumeId ?? 'all'}`}
      {...{ onOpenChange, volumeId, volumeName }}
      owner={owner}
    />
  ) : null
}

function RecoveryHistory({
  onOpenChange,
  volumeId,
  volumeName,
  owner,
}: Omit<Props, 'open'> & { owner: string }) {
  const capabilities = useRecoveryCapabilities()
  const supported = !!capabilities.data && capabilities.data.reason_code !== 'unsupported'
  const enabled = capabilities.data?.enabled === true
  const canManage = useAuthStore((state) => state.hasPermission(PERMISSIONS.VOLUMES_WRITE_OWN))
  const [page, setPage] = useState(1)
  const [restorePage, setRestorePage] = useState(1)
  const [description, setDescription] = useState('')
  const [restoring, setRestoring] = useState<VolumeBackup | null>(null)
  const [failure, setFailure] = useState<unknown>(null)
  const createRequest = useRef<{ description: string; id: string } | null>(null)
  const submitting = useRef(false)
  const eligibility = useBackupEligibility(volumeId, enabled && canManage)
  const backups = useVolumeBackups(page, volumeId, supported)
  const restores = useVolumeRestores(restorePage, supported)
  const actions = useRecoveryActions()
  const { confirm, dialog } = useConfirmDialog()
  const current = () => useAuthStore.getState().user?.id === owner
  const refresh = () => {
    void capabilities.refetch()
    if (supported) {
      void backups.refetch()
      void restores.refetch()
      if (volumeId && canManage && enabled) void eligibility.refetch()
    }
  }

  const create = async () => {
    if (
      !volumeId ||
      !enabled ||
      !canManage ||
      !eligibility.data?.eligible ||
      submitting.current ||
      !current()
    )
      return
    submitting.current = true
    setFailure(null)
    const text = description.trim()
    if (createRequest.current?.description !== text)
      createRequest.current = { description: text, id: crypto.randomUUID() }
    try {
      await actions.create.mutateAsync({
        volume: volumeId,
        body: { request_id: createRequest.current.id, ...(text ? { description: text } : {}) },
      })
      if (!current()) return
      createRequest.current = null
      setDescription('')
      setPage(1)
      useToastStore.getState().addToast({
        type: 'info',
        title: 'Backup requested',
        message: 'The source stays unchanged while the backup is prepared.',
      })
    } catch (error) {
      if (current()) setFailure(error)
    } finally {
      submitting.current = false
    }
  }
  const remove = async (backup: VolumeBackup) => {
    if (!backup.can_delete || !enabled || !canManage) return
    if (
      !(await confirm({
        title: 'Delete backup?',
        description:
          'This removes the recovery point. The original volume is unchanged. An active restore may prevent deletion.',
        confirmLabel: 'Delete backup',
        cancelLabel: 'Keep backup',
        variant: 'danger',
      }))
    )
      return
    if (!current()) return
    setFailure(null)
    try {
      await actions.remove.mutateAsync(backup.id)
      if (current())
        useToastStore.getState().addToast({
          type: 'info',
          title: 'Backup deletion requested',
          message: 'History shows deletion until cleanup is confirmed.',
        })
    } catch (error) {
      if (current()) {
        setFailure(error)
        void backups.refetch()
      }
    }
  }

  const backupPages = backups.data
    ? Math.max(1, Math.ceil(backups.data.total / Math.max(1, backups.data.page_size)))
    : null
  const restorePages = restores.data
    ? Math.max(1, Math.ceil(restores.data.total / Math.max(1, restores.data.page_size)))
    : null
  const backupTotalLabel = backups.data
    ? backups.data.total.toLocaleString()
    : backups.isPending
      ? '…'
      : '—'
  const restoreTotalLabel = restores.data
    ? restores.data.total.toLocaleString()
    : restores.isPending
      ? '…'
      : '—'
  const backupHint = backups.data
    ? `Page ${page} of ${backupPages ?? 1}`
    : backups.isPending
      ? 'Loading history'
      : 'Unavailable'
  const restoreHint = restores.data
    ? `Page ${restorePage} of ${restorePages ?? 1}`
    : restores.isPending
      ? 'Loading history'
      : 'Unavailable'
  const refreshing = capabilities.isFetching || backups.isFetching || restores.isFetching

  return (
    <>
      <Dialog open onOpenChange={onOpenChange} size={volumeId ? 'xl' : '2xl'}>
        <DialogContent className="space-y-5">
          <DialogHeader className="space-y-3">
            <div className="flex items-start gap-3.5">
              <div className="shrink-0 rounded-2xl bg-primary/10 p-3 ring-1 ring-primary/15">
                <Database className="h-5 w-5 text-primary" />
              </div>
              <div className="min-w-0 flex-1 space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <DialogTitle className="text-xl">
                    {volumeName ? `Backups · ${volumeName}` : 'Volume backup history'}
                  </DialogTitle>
                  <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-400">
                    <ShieldCheck className="h-3 w-3" />
                    Private offline recovery
                  </span>
                </div>
                <DialogDescription className="max-w-2xl leading-relaxed">
                  Verified recovery points for private volumes. Backups never stop workloads
                  automatically, and every restore creates a new private volume while leaving the
                  original unchanged.
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          <div className="flex flex-wrap items-center justify-between gap-2 border-y border-border/40 py-2.5">
            <p className="text-xs text-muted-foreground">
              State is refreshed while work is active. No estimated completion time is available.
            </p>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Refresh backup history"
              onClick={refresh}
              className="-my-1 text-muted-foreground hover:text-foreground"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} />
              Refresh
            </Button>
          </div>

          {capabilities.isPending && (
            <div
              role="status"
              className="flex items-center gap-2 rounded-xl border border-border/50 bg-surface/40 px-3.5 py-3 text-sm text-muted-foreground"
            >
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              Checking recovery availability…
            </div>
          )}
          {capabilities.isError && (
            <div
              role="alert"
              className="flex items-start gap-2.5 rounded-xl border border-destructive/25 bg-destructive/[0.06] p-3.5 text-sm text-destructive"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>Recovery availability could not be checked. Refresh to retry.</p>
            </div>
          )}
          {capabilities.data && !enabled && (
            <div
              role="status"
              className="flex items-start gap-3 rounded-xl border border-amber-500/20 bg-amber-500/[0.07] p-3.5"
            >
              <div className="shrink-0 rounded-lg bg-amber-500/10 p-2">
                <AlertTriangle className="h-4 w-4 text-amber-400" />
              </div>
              <div className="min-w-0 space-y-1">
                <p className="text-sm font-medium">Backup actions are unavailable</p>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {capabilities.data.message ||
                    'Volume backups are not configured on this deployment.'}
                </p>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Existing history remains available when supported.
                </p>
              </div>
            </div>
          )}
          {!canManage && supported && (
            <div className="flex items-start gap-2.5 rounded-xl border border-border/50 bg-surface/40 p-3.5">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <p className="text-xs leading-relaxed text-muted-foreground">
                You can view backup history. Creating, restoring or deleting backups requires volume
                write permission.
              </p>
            </div>
          )}
          {failure != null && (
            <div
              role="alert"
              className="flex items-start gap-2.5 rounded-xl border border-destructive/25 bg-destructive/[0.06] p-3.5 text-sm text-destructive"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>{recoveryErrorMessage(failure)}</p>
            </div>
          )}

          {volumeId && enabled && canManage && (
            <section
              aria-label="Create volume backup"
              className="overflow-hidden rounded-2xl border border-primary/15 bg-gradient-to-br from-primary/[0.06] via-surface/40 to-surface/20 p-4 sm:p-5"
            >
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <div className="shrink-0 rounded-xl bg-primary/10 p-2.5 ring-1 ring-primary/10">
                    <Archive className="h-4 w-4 text-primary" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-sm font-semibold">Back up this volume</h3>
                      {eligibility.data && (
                        <span
                          className={cn(
                            'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider',
                            eligibility.data.eligible
                              ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
                              : 'border-amber-500/20 bg-amber-500/10 text-amber-400'
                          )}
                        >
                          {eligibility.data.eligible ? (
                            <CheckCircle2 className="h-3 w-3" />
                          ) : (
                            <AlertTriangle className="h-3 w-3" />
                          )}
                          {eligibility.data.eligible ? 'Eligible' : 'Not eligible'}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                      Requests an offline recovery point. NukeLab never stops workloads
                      automatically.
                    </p>
                  </div>
                </div>

                {eligibility.isPending ? (
                  <div
                    role="status"
                    className="flex items-center gap-2 rounded-lg border border-border/50 bg-background/40 px-3 py-2 text-xs text-muted-foreground"
                  >
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                    Checking private/offline eligibility…
                  </div>
                ) : eligibility.isError ? (
                  <div
                    role="alert"
                    className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/[0.07] px-3 py-2 text-xs"
                  >
                    <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                    <p className="leading-relaxed text-muted-foreground">
                      Eligibility could not be checked. Refresh before requesting a backup.
                    </p>
                  </div>
                ) : eligibility.data ? (
                  <div
                    className={cn(
                      'flex items-start gap-2.5 rounded-xl border p-3',
                      eligibility.data.eligible
                        ? 'border-emerald-500/20 bg-emerald-500/[0.06]'
                        : 'border-amber-500/20 bg-amber-500/[0.07]'
                    )}
                  >
                    {eligibility.data.eligible ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                    ) : (
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                    )}
                    <div className="min-w-0 space-y-0.5">
                      <p
                        className={cn(
                          'text-xs font-medium',
                          eligibility.data.eligible ? 'text-emerald-400' : 'text-amber-400'
                        )}
                      >
                        {eligibility.data.eligible
                          ? 'Eligible for offline backup'
                          : 'Backup unavailable right now'}
                      </p>
                      <p className="text-xs leading-relaxed text-muted-foreground">
                        {eligibility.data.message}
                      </p>
                      {!eligibility.data.eligible && (
                        <p className="text-xs leading-relaxed text-muted-foreground">
                          Attached volumes must be stopped before a backup can run. NukeLab does not
                          stop workloads automatically.
                        </p>
                      )}
                    </div>
                  </div>
                ) : null}

                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <Label htmlFor="backup-description">Description (optional)</Label>
                    <span className="pr-1 text-[10px] tabular-nums text-muted-foreground">
                      {description.length}/255
                    </span>
                  </div>
                  <Textarea
                    id="backup-description"
                    value={description}
                    maxLength={255}
                    placeholder="e.g. Before updating the experiment data"
                    disabled={actions.create.isPending}
                    className="bg-background/50"
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </div>

                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
                    <ShieldCheck className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
                    The source volume stays unchanged while this backup is prepared.
                  </p>
                  <Button
                    type="button"
                    data-testid="create-backup"
                    disabled={!eligibility.data?.eligible || actions.create.isPending}
                    onClick={() => void create()}
                    className="w-full shrink-0 sm:w-auto"
                  >
                    <Archive className="h-4 w-4" />
                    {actions.create.isPending ? 'Requesting…' : 'Create backup'}
                  </Button>
                </div>
              </div>
            </section>
          )}

          {supported && (
            <div className="grid grid-cols-1 divide-y divide-border/40 overflow-hidden rounded-xl border border-border/50 bg-surface/40 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
              <SummaryStat
                icon={Archive}
                label="Backups"
                value={backupTotalLabel}
                hint={backupHint}
              />
              <SummaryStat
                icon={History}
                label="Restores"
                value={restoreTotalLabel}
                hint={restoreHint}
              />
              <SummaryStat
                icon={CalendarClock}
                label="Retention"
                value="Per record"
                hint="Expiry shown on each backup"
              />
            </div>
          )}

          {supported && (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_17rem] lg:items-start">
              <section aria-label="Backups" className="min-w-0 space-y-3">
                <SectionHeading
                  icon={Archive}
                  title="Backups"
                  total={backups.data?.total}
                  caption={
                    volumeName
                      ? `Recovery points for ${volumeName}`
                      : 'All retained recovery points'
                  }
                />
                {backups.isPending && (
                  <SectionState
                    icon={Loader2}
                    spinning
                    role="status"
                    title="Loading backup history…"
                    description="Retained recovery points will appear here."
                  />
                )}
                {backups.isError && (
                  <SectionState
                    icon={AlertTriangle}
                    tone="danger"
                    role="alert"
                    title="Backup history unavailable"
                    description="Displayed records may be out of date. Select Refresh to try again."
                  />
                )}
                {backups.data?.items.length === 0 && (
                  <SectionState
                    icon={Archive}
                    title="No backups yet"
                    description={
                      volumeId
                        ? 'Request a backup above once this private volume is offline.'
                        : 'Backups appear here after you request one from a private volume. Deleted-source recovery points stay reachable in this history.'
                    }
                  />
                )}
                {backups.data?.items.map((backup) => (
                  <article
                    key={backup.id}
                    data-testid={`backup-${backup.id}`}
                    className={cn(
                      'space-y-3 rounded-xl border p-3.5',
                      !backup.source_volume_id
                        ? 'border-dashed border-border/60 bg-surface/25'
                        : 'border-border/50 bg-surface/40'
                    )}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <h4 className="truncate text-sm font-semibold">
                          {backup.source_display_name}
                        </h4>
                        {backup.description ? (
                          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                            {backup.description}
                          </p>
                        ) : null}
                      </div>
                      <RecoveryStatusBadge status={backup.status} />
                    </div>
                    {!backup.source_volume_id && (
                      <div className="flex items-start gap-2 rounded-lg border border-amber-500/15 bg-amber-500/[0.05] px-3 py-2">
                        <DatabaseBackup className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                        <p className="text-xs font-medium leading-relaxed text-foreground/80">
                          Source volume deleted{' '}
                          <span className="font-normal text-muted-foreground">
                            · retained recovery point
                          </span>
                        </p>
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                      <MetaItem
                        icon={Clock}
                        label="Created"
                        value={formatDate(backup.created_at)}
                      />
                      <MetaItem
                        icon={CalendarClock}
                        label="Expires"
                        value={backup.expires_at ? formatDate(backup.expires_at) : 'No expiry'}
                      />
                      <MetaItem
                        icon={Archive}
                        label="Archive size"
                        value={
                          backup.compressed_bytes !== null
                            ? formatBytes(backup.compressed_bytes)
                            : 'Not measured'
                        }
                      />
                      <MetaItem
                        icon={Database}
                        label="Logical data"
                        value={
                          backup.logical_bytes !== null
                            ? formatBytes(backup.logical_bytes)
                            : 'Not measured'
                        }
                      />
                      <MetaItem
                        icon={HardDrive}
                        label="Member count"
                        value={
                          backup.member_count !== null
                            ? `${backup.member_count.toLocaleString()} entries`
                            : 'Not measured'
                        }
                      />
                    </div>
                    <div className="flex items-start gap-2 rounded-lg bg-background/50 px-3 py-2">
                      <Info className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/70" />
                      <p className="text-xs leading-relaxed text-muted-foreground">
                        {backup.message}
                      </p>
                    </div>
                    {enabled && canManage && (backup.can_restore || backup.can_delete) ? (
                      <div className="flex flex-wrap items-center justify-end gap-2">
                        {backup.can_delete && (
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={actions.remove.isPending}
                            onClick={() => void remove(backup)}
                            className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                            {backup.status === 'delete_failed' ? 'Retry deletion' : 'Delete backup'}
                          </Button>
                        )}
                        {backup.can_restore && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setRestoring(backup)}
                            className="border-primary/30 text-primary hover:bg-primary/10 hover:text-primary"
                          >
                            <RotateCcw className="h-3.5 w-3.5" />
                            Restore to new volume
                          </Button>
                        )}
                      </div>
                    ) : null}
                  </article>
                ))}
                <Pagination
                  page={page}
                  total={backups.data?.total ?? 0}
                  size={backups.data?.page_size ?? 10}
                  onPage={setPage}
                />
              </section>

              <section aria-label="Restore history" className="min-w-0 space-y-3">
                <SectionHeading
                  icon={History}
                  title="Restores"
                  total={restores.data?.total}
                  caption="New private destinations"
                />
                {restores.isPending && (
                  <SectionState
                    icon={Loader2}
                    spinning
                    role="status"
                    title="Loading restore history…"
                    description="Accepted restores will appear here."
                  />
                )}
                {restores.isError && (
                  <SectionState
                    icon={AlertTriangle}
                    tone="danger"
                    role="alert"
                    title="Restore history unavailable"
                    description="Refresh to find accepted requests after a connection failure."
                  />
                )}
                {restores.data?.items.length === 0 && (
                  <SectionState
                    icon={History}
                    title="No restores yet"
                    description="Restores create a separate private volume and never overwrite the source."
                  />
                )}
                {restores.data?.items.map((restore) => (
                  <article
                    key={restore.id}
                    data-testid={`restore-${restore.id}`}
                    className="space-y-2.5 rounded-xl border border-border/50 bg-surface/40 p-3.5"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="min-w-0 flex-1 break-words text-sm font-medium">
                        {restore.destination_display_name}
                      </p>
                      <RecoveryStatusBadge status={restore.status} />
                    </div>
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      {restore.message}
                    </p>
                    <p className="flex items-center gap-1 text-[11px] text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      Requested {formatDate(restore.created_at)}
                    </p>
                    {restore.status === 'completed' ? (
                      <div className="space-y-2 rounded-lg border border-emerald-500/20 bg-emerald-500/[0.06] p-2.5">
                        <div className="flex items-start gap-1.5">
                          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
                          <p className="text-xs leading-relaxed text-foreground/80">
                            {restore.destination_display_name} is ready. Your original volume was
                            not changed.
                          </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-3 pl-5">
                          <Link
                            to="/volumes"
                            onClick={() => onOpenChange(false)}
                            className="text-xs font-medium text-primary hover:underline"
                          >
                            View volumes
                          </Link>
                          <Link
                            to="/servers"
                            className="text-xs font-medium text-primary hover:underline"
                          >
                            Use in a server
                          </Link>
                        </div>
                      </div>
                    ) : (
                      <p className="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
                        <ShieldCheck className="mt-0.5 h-3 w-3 shrink-0" />
                        The destination is unavailable for use until verification completes.
                      </p>
                    )}
                  </article>
                ))}
                <Pagination
                  page={restorePage}
                  total={restores.data?.total ?? 0}
                  size={restores.data?.page_size ?? 10}
                  onPage={setRestorePage}
                />
              </section>
            </div>
          )}
          <DialogClose onClick={() => onOpenChange(false)} />
        </DialogContent>
      </Dialog>
      {restoring && (
        <RestoreDialog
          key={`${owner}:${restoring.id}`}
          backup={restoring}
          owner={owner}
          onClose={() => setRestoring(null)}
          onAccepted={() => {
            setRestoring(null)
            setRestorePage(1)
            void restores.refetch()
          }}
        />
      )}
      {dialog}
    </>
  )
}

function RecoveryStatusBadge({ status }: { status: BackupStatus | RestoreStatus }) {
  return <StatusBadge status={statusTones[status]} label={recoveryStatusLabel(status)} size="sm" />
}

function SummaryStat({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: LucideIcon
  label: string
  value: string
  hint: string
}) {
  return (
    <div className="min-w-0 px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3 w-3 shrink-0" />
        <span className="truncate">{label}</span>
      </div>
      <p className="mt-0.5 truncate text-sm font-semibold">{value}</p>
      <p className="truncate text-[10px] text-muted-foreground">{hint}</p>
    </div>
  )
}

function SectionHeading({
  icon: Icon,
  title,
  total,
  caption,
}: {
  icon: LucideIcon
  title: string
  total?: number
  caption: string
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2.5">
        <div className="shrink-0 rounded-lg bg-primary/10 p-2 text-primary">
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{title}</h3>
          <p className="truncate text-[11px] text-muted-foreground">{caption}</p>
        </div>
      </div>
      {typeof total === 'number' && (
        <span className="shrink-0 rounded-full border border-border/50 bg-surface/50 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
          {total.toLocaleString()}
        </span>
      )}
    </div>
  )
}

function SectionState({
  icon: Icon,
  title,
  description,
  tone = 'muted',
  spinning = false,
  role,
}: {
  icon: LucideIcon
  title: string
  description: string
  tone?: 'muted' | 'danger'
  spinning?: boolean
  role?: 'status' | 'alert'
}) {
  return (
    <div
      role={role}
      className={cn(
        'rounded-xl border border-dashed px-4 py-5 text-center',
        tone === 'danger'
          ? 'border-destructive/25 bg-destructive/[0.04]'
          : 'border-border/60 bg-surface/30'
      )}
    >
      <div
        className={cn(
          'mx-auto mb-2 flex h-9 w-9 items-center justify-center rounded-xl',
          tone === 'danger' ? 'bg-destructive/10' : 'bg-muted/50'
        )}
      >
        <Icon
          className={cn(
            'h-4 w-4',
            spinning && 'animate-spin',
            tone === 'danger' ? 'text-destructive' : 'text-muted-foreground'
          )}
        />
      </div>
      <p className="text-sm font-medium">{title}</p>
      <p className="mx-auto mt-1 max-w-xs text-xs leading-relaxed text-muted-foreground">
        {description}
      </p>
    </div>
  )
}

function MetaItem({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon
  label: string
  value: string
}) {
  return (
    <div className="flex min-w-0 items-start gap-1.5">
      <Icon className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/70" />
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground/80">{label}</p>
        <p className="break-words text-xs font-medium leading-snug">{value}</p>
      </div>
    </div>
  )
}

function Pagination({
  page,
  total,
  size,
  onPage,
}: {
  page: number
  total: number
  size: number
  onPage: (page: number) => void
}) {
  if (total <= size && page === 1) return null
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border border-border/40 bg-surface/30 px-2 py-1.5">
      <span className="pl-1 text-[11px] text-muted-foreground">
        Page {page} of {Math.max(1, Math.ceil(total / size))}
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          <ChevronLeft className="h-3.5 w-3.5" />
          Previous
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          disabled={page * size >= total}
          onClick={() => onPage(page + 1)}
        >
          Next
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}

function RestoreDialog({
  backup,
  owner,
  onClose,
  onAccepted,
}: {
  backup: VolumeBackup
  owner: string
  onClose: () => void
  onAccepted: () => void
}) {
  const [name, setName] = useState('')
  const [size, setSize] = useState('')
  const [failure, setFailure] = useState<unknown>(null)
  const request = useRef<{ payload: string; id: string } | null>(null)
  const submitting = useRef(false)
  const { restore } = useRecoveryActions()
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (submitting.current || useAuthStore.getState().user?.id !== owner) return
    setFailure(null)
    try {
      const display_name = name.trim()
      if (!display_name || display_name.length > 255)
        throw new Error('Enter a new volume name (up to 255 characters).')
      const max_size_bytes = restoreCapacity(size, backup.logical_bytes ?? 0)
      const payload = JSON.stringify({ display_name, max_size_bytes })
      if (request.current?.payload !== payload)
        request.current = { payload, id: crypto.randomUUID() }
      submitting.current = true
      await restore.mutateAsync({
        backup: backup.id,
        body: { request_id: request.current.id, display_name, max_size_bytes },
      })
      if (useAuthStore.getState().user?.id !== owner) return
      useToastStore.getState().addToast({
        type: 'info',
        title: 'Restore requested',
        message: 'A new private volume is being prepared. The original is unchanged.',
      })
      onAccepted()
    } catch (error) {
      if (useAuthStore.getState().user?.id === owner) setFailure(error)
    } finally {
      submitting.current = false
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !restore.isPending) onClose()
      }}
      size="lg"
    >
      <DialogContent className="space-y-5">
        <DialogHeader className="space-y-3">
          <div className="flex items-start gap-3.5">
            <div className="shrink-0 rounded-2xl bg-primary/10 p-3 ring-1 ring-primary/15">
              <RotateCcw className="h-5 w-5 text-primary" />
            </div>
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <DialogTitle className="text-xl">Restore to a new private volume</DialogTitle>
                <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-400">
                  <ShieldCheck className="h-3 w-3" />
                  Private
                </span>
              </div>
              <DialogDescription className="leading-relaxed">
                This creates a separate volume from the verified backup. It never overwrites the
                original. The destination remains unavailable until verification succeeds.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-3 rounded-xl border border-border/50 bg-surface/50 p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2.5">
              <div className="shrink-0 rounded-lg bg-primary/10 p-2 text-primary">
                <Database className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Source backup
                </p>
                <p className="truncate text-sm font-semibold">{backup.source_display_name}</p>
              </div>
            </div>
            <span className="inline-flex items-center gap-1 rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-primary">
              <HardDrive className="h-3 w-3" />
              New volume
            </span>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            <MetaItem
              icon={Clock}
              label="Completed"
              value={backup.completed_at ? formatDate(backup.completed_at) : 'Not recorded'}
            />
            <MetaItem
              icon={Archive}
              label="Archive"
              value={
                backup.compressed_bytes !== null
                  ? formatBytes(backup.compressed_bytes)
                  : 'Not measured'
              }
            />
            <MetaItem
              icon={Database}
              label="Logical data"
              value={
                backup.logical_bytes !== null ? formatBytes(backup.logical_bytes) : 'Not measured'
              }
            />
            <MetaItem
              icon={HardDrive}
              label="Members"
              value={
                backup.member_count !== null
                  ? `${backup.member_count.toLocaleString()} entries`
                  : 'Not measured'
              }
            />
          </div>
        </div>

        <div className="flex items-start gap-2.5 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] p-3.5">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
          <div className="min-w-0">
            <p className="text-sm font-medium">Your original volume stays unchanged</p>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              The restored data goes into a new private volume. You can use it in a server only
              after its integrity has been verified.
            </p>
          </div>
        </div>

        <form noValidate onSubmit={(event) => void submit(event)} className="space-y-4">
          {failure != null && (
            <div
              role="alert"
              className="flex items-start gap-2.5 rounded-xl border border-destructive/25 bg-destructive/[0.07] p-3 text-sm text-destructive"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>{recoveryErrorMessage(failure)}</p>
            </div>
          )}
          <div className="space-y-4 rounded-xl border border-border/50 bg-surface/50 p-4">
            <div className="flex items-center gap-2">
              <HardDrive className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-semibold">Destination volume</h3>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor="restore-volume-name">New volume name</Label>
                <span className="pr-1 text-[10px] tabular-nums text-muted-foreground">
                  {name.length}/255
                </span>
              </div>
              <Input
                id="restore-volume-name"
                data-testid="restore-volume-name"
                value={name}
                maxLength={255}
                placeholder="e.g. Recovered experiment"
                disabled={restore.isPending}
                className="bg-background/50"
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="restore-volume-size">New volume capacity (GiB)</Label>
              <Input
                id="restore-volume-size"
                data-testid="restore-volume-size"
                value={size}
                type="number"
                step="any"
                placeholder="e.g. 2"
                disabled={restore.isPending}
                className="bg-background/50"
                onChange={(event) => setSize(event.target.value)}
              />
              <p className="text-xs leading-relaxed text-muted-foreground">
                Logical backup data:{' '}
                {backup.logical_bytes !== null ? formatBytes(backup.logical_bytes) : 'unknown'}.
                Choose enough capacity to fit the restored data. Normal volume count and capacity
                quota apply.
              </p>
            </div>
          </div>
          <DialogFooter className="sticky bottom-0 z-10 -mx-6 -mb-6 mt-2 rounded-b-2xl border-t border-border/50 bg-card/95 px-6 py-4 backdrop-blur-xl">
            <Button type="button" variant="outline" disabled={restore.isPending} onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" data-testid="restore-backup-submit" disabled={restore.isPending}>
              {restore.isPending ? 'Requesting…' : 'Create restored volume'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
