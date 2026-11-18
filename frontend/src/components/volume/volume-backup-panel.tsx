// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { RefreshCw } from 'lucide-react'
import {
  useBackupEligibility,
  useRecoveryActions,
  useRecoveryCapabilities,
  useVolumeBackups,
  useVolumeRestores,
} from '../../hooks/use-volume-backups'
import { recoveryErrorMessage, recoveryStatusLabel, restoreCapacity } from '../../lib/volume-backup'
import { formatBytes, formatDate } from '../../lib/utils'
import { PERMISSIONS, useAuthStore } from '../../stores/auth-store'
import { useToastStore } from '../../stores/toast-store'
import type { VolumeBackup } from '../../types/volume-backup'
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

  return (
    <>
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto" tabIndex={-1}>
          <DialogHeader>
            <DialogTitle>
              {volumeName ? `Backups · ${volumeName}` : 'Volume backup history'}
            </DialogTitle>
            <DialogDescription>
              Private offline volume recovery. Backups do not stop servers automatically. Restores
              always create a new private volume.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-5 mt-4">
            <div className="flex justify-between gap-3">
              <p className="text-sm text-muted-foreground">
                State is refreshed while work is active. No estimated completion time is available.
              </p>
              <Button
                variant="outline"
                size="sm"
                aria-label="Refresh backup history"
                onClick={refresh}
              >
                <RefreshCw className="h-4 w-4" />
                Refresh
              </Button>
            </div>
            {capabilities.isPending && <p role="status">Checking recovery availability…</p>}
            {capabilities.isError && (
              <p role="alert">Recovery availability could not be checked. Refresh to retry.</p>
            )}
            {capabilities.data && !enabled && (
              <p role="status" className="rounded-lg border border-border p-3">
                {capabilities.data.message ||
                  'Volume backups are not configured on this deployment.'}{' '}
                Existing history remains available when supported.
              </p>
            )}
            {!canManage && supported && (
              <p className="text-sm text-muted-foreground">
                You can view backup history. Creating, restoring or deleting backups requires volume
                write permission.
              </p>
            )}
            {failure != null && (
              <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-sm">
                {recoveryErrorMessage(failure)}
              </p>
            )}
            {volumeId && enabled && canManage && (
              <section
                className="rounded-lg border border-border p-4 space-y-3"
                aria-label="Create volume backup"
              >
                <h3 className="font-semibold">Back up this volume</h3>
                {eligibility.isPending ? (
                  <p role="status">Checking private/offline eligibility…</p>
                ) : eligibility.isError ? (
                  <p role="alert">
                    Eligibility could not be checked. Refresh before requesting a backup.
                  </p>
                ) : (
                  <p className="text-sm text-muted-foreground">{eligibility.data?.message}</p>
                )}
                <Label htmlFor="backup-description">Description (optional)</Label>
                <Textarea
                  id="backup-description"
                  value={description}
                  maxLength={255}
                  disabled={actions.create.isPending}
                  onChange={(event) => setDescription(event.target.value)}
                />
                <Button
                  type="button"
                  data-testid="create-backup"
                  disabled={!eligibility.data?.eligible || actions.create.isPending}
                  onClick={() => void create()}
                >
                  {actions.create.isPending ? 'Requesting…' : 'Create backup'}
                </Button>
              </section>
            )}
            {supported && (
              <section aria-label="Backups" className="space-y-3">
                <h3 className="font-semibold">Backups</h3>
                {backups.isPending ? (
                  <p role="status">Loading backup history…</p>
                ) : backups.isError ? (
                  <p role="alert">
                    Backup history could not be refreshed. Displayed records may be out of date.
                  </p>
                ) : backups.data?.items.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No backups yet. A deleted source volume’s retained backups appear in all-volume
                    history.
                  </p>
                ) : null}
                {backups.data?.items.map((backup) => (
                  <article
                    key={backup.id}
                    data-testid={`backup-${backup.id}`}
                    className="rounded-lg border border-border p-4 space-y-2"
                  >
                    <div className="flex flex-wrap justify-between gap-2">
                      <h4 className="font-medium">{backup.source_display_name}</h4>
                      <span role="status" className="text-sm">
                        {recoveryStatusLabel(backup.status)}
                      </span>
                    </div>
                    {!backup.source_volume_id && (
                      <p className="text-xs text-muted-foreground">
                        Source volume deleted · retained recovery point
                      </p>
                    )}
                    {backup.description && <p className="text-sm">{backup.description}</p>}
                    <p className="text-sm text-muted-foreground">
                      Created {formatDate(backup.created_at)}
                      {backup.expires_at ? ` · Expires ${formatDate(backup.expires_at)}` : ''}
                    </p>
                    <p className="text-sm">{backup.message}</p>
                    {backup.compressed_bytes !== null && (
                      <p className="text-xs text-muted-foreground">
                        Archive {formatBytes(backup.compressed_bytes)} · Logical data{' '}
                        {backup.logical_bytes !== null
                          ? formatBytes(backup.logical_bytes)
                          : 'not measured'}
                        {backup.member_count !== null
                          ? ` · ${backup.member_count.toLocaleString()} entries`
                          : ''}
                      </p>
                    )}
                    <div className="flex flex-wrap gap-2">
                      {enabled && canManage && backup.can_restore && (
                        <Button variant="outline" size="sm" onClick={() => setRestoring(backup)}>
                          Restore to new volume
                        </Button>
                      )}
                      {enabled && canManage && backup.can_delete && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={actions.remove.isPending}
                          onClick={() => void remove(backup)}
                        >
                          {backup.status === 'delete_failed' ? 'Retry deletion' : 'Delete backup'}
                        </Button>
                      )}
                    </div>
                  </article>
                ))}
                <Pagination
                  page={page}
                  total={backups.data?.total ?? 0}
                  size={backups.data?.page_size ?? 10}
                  onPage={setPage}
                />
              </section>
            )}
            {supported && (
              <section aria-label="Restore history" className="space-y-3">
                <h3 className="font-semibold">Restores</h3>
                {restores.isPending ? (
                  <p role="status">Loading restore history…</p>
                ) : restores.isError ? (
                  <p role="alert">
                    Restore history could not be refreshed. Refresh to find accepted requests after
                    a connection failure.
                  </p>
                ) : restores.data?.items.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No restore requests yet.</p>
                ) : null}
                {restores.data?.items.map((restore) => (
                  <article
                    key={restore.id}
                    data-testid={`restore-${restore.id}`}
                    className="rounded-lg border border-border p-4 space-y-2"
                  >
                    <span role="status" className="text-sm font-medium">
                      {recoveryStatusLabel(restore.status)}
                    </span>
                    <p className="text-sm">{restore.message}</p>
                    <p className="text-xs text-muted-foreground">
                      Requested {formatDate(restore.created_at)}
                    </p>
                    {restore.status === 'completed' ? (
                      <div className="space-y-2">
                        <p className="text-sm">
                          {restore.destination_display_name} is ready. Your original volume was not
                          changed.
                        </p>
                        <Link
                          to="/volumes"
                          onClick={() => onOpenChange(false)}
                          className="text-sm text-primary underline mr-3"
                        >
                          View volumes
                        </Link>
                        <Link to="/servers" className="text-sm text-primary underline">
                          Use in a server
                        </Link>
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">
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
            )}
          </div>
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
    <div className="flex items-center justify-between gap-2 text-sm">
      <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </Button>
      <span>
        Page {page} of {Math.max(1, Math.ceil(total / size))}
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={page * size >= total}
        onClick={() => onPage(page + 1)}
      >
        Next
      </Button>
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
  const submit = async (event: React.FormEvent) => {
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
    >
      <DialogContent tabIndex={-1}>
        <DialogHeader>
          <DialogTitle>Restore to a new private volume</DialogTitle>
          <DialogDescription>
            This creates a separate volume from the verified backup. It never overwrites the
            original. The destination remains unavailable until verification succeeds.
          </DialogDescription>
        </DialogHeader>
        <form noValidate onSubmit={(event) => void submit(event)} className="mt-4 space-y-4">
          {failure != null && (
            <p role="alert" className="text-sm text-destructive">
              {recoveryErrorMessage(failure)}
            </p>
          )}
          <div className="space-y-2">
            <Label htmlFor="restore-volume-name">New volume name</Label>
            <Input
              id="restore-volume-name"
              data-testid="restore-volume-name"
              value={name}
              maxLength={255}
              disabled={restore.isPending}
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
              disabled={restore.isPending}
              onChange={(event) => setSize(event.target.value)}
            />
            <p className="text-sm text-muted-foreground">
              Logical backup data:{' '}
              {backup.logical_bytes !== null ? formatBytes(backup.logical_bytes) : 'unknown'}.
              Normal volume count and capacity quota apply.
            </p>
          </div>
          <DialogFooter>
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
