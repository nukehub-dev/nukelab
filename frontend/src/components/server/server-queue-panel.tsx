// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useEffect, useRef, useId } from 'react'
import { useServers } from '../../hooks/use-servers'
import { Link } from '@tanstack/react-router'
import { Clock, RefreshCw } from 'lucide-react'
import {
  useCancelServerQueue,
  useServerQueue,
  useServerQueueEntry,
} from '../../hooks/use-server-queue'
import { ApiError } from '../../lib/api'
import { canCancelQueuedRequest } from '../../lib/server-queue'
import { formatDate } from '../../lib/utils'
import { PERMISSIONS, useAuthStore } from '../../stores/auth-store'
import { useToastStore } from '../../stores/toast-store'
import type { Environment, Plan } from '../../types/api'
import type { ServerQueueEntry } from '../../types/server-queue'
import { Button } from '../ui/button'
import { useConfirmDialog } from '../ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from '../ui/dialog'

interface QueuePanelProps {
  requestId?: string
  plans: Plan[]
  environments: Environment[]
  onSelect: (id?: string) => void
}

const statusLabels = {
  pending: 'Waiting',
  starting: 'Starting',
  scheduled: 'Scheduled',
  started: 'Started',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

function QueueErrorState({ error, retry }: { error: Error | null; retry: () => void }) {
  const message =
    error instanceof ApiError && error.status === 403
      ? 'You do not have permission to view these requests.'
      : error instanceof ApiError && error.status === 404
        ? 'This request is unavailable or no longer exists.'
        : 'Requests could not be refreshed. Displayed information may be out of date.'
  return (
    <div
      role="alert"
      className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 space-y-2"
    >
      <p className="text-sm">{message}</p>
      <Button variant="outline" size="sm" onClick={retry}>
        Retry
      </Button>
    </div>
  )
}

export function ServerQueuePanel({ requestId, plans, environments, onSelect }: QueuePanelProps) {
  const [page, setPage] = useState(1)
  const headingId = useId()
  const descriptionId = useId()
  const detailRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!requestId) return
    const previous = document.activeElement
    const frame = requestAnimationFrame(() => detailRef.current?.focus())
    return () => {
      cancelAnimationFrame(frame)
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [requestId])
  const queue = useServerQueue(page, true)
  const { data: servers = [] } = useServers()
  const detail = useServerQueueEntry(requestId, true)
  const cancel = useCancelServerQueue()
  const { confirm, dialog } = useConfirmDialog()
  const canManage = useAuthStore((state) => state.hasPermission(PERMISSIONS.SERVERS_WRITE_OWN))
  const username = useAuthStore((state) => state.user?.username)
  const ownerId = useAuthStore((state) => state.user?.id)

  const cancelRequest = async (entry: ServerQueueEntry) => {
    if (!canCancelQueuedRequest(entry) || !canManage) return
    if (
      !(await confirm({
        title: 'Cancel waiting request?',
        description: `Cancel ${entry.request.name}? Its selected configuration will not be launched.`,
        confirmLabel: 'Cancel request',
        cancelLabel: 'Keep waiting',
        variant: 'warning',
      }))
    )
      return
    if (useAuthStore.getState().user?.id !== ownerId) return
    cancel.mutate(entry, {
      onSuccess: () => {
        if (useAuthStore.getState().user?.id !== ownerId) return
        useToastStore
          .getState()
          .addToast({ type: 'info', title: 'Request cancelled', message: entry.request.name })
      },
      onError: (error) =>
        useToastStore.getState().addToast({
          type: 'error',
          title:
            error instanceof ApiError && error.status === 409
              ? 'Launch already in progress'
              : 'Could not cancel request',
          message:
            error instanceof ApiError && error.status === 409
              ? 'Refresh the request to see its current status.'
              : 'The request is unchanged. Refresh and try again.',
        }),
    })
  }

  const renderRequest = (entry: ServerQueueEntry, detailed: boolean) => {
    const resources = entry.request.resources
    const launched = servers.find((server) => server.id === entry.server_id)
    return (
      <article
        className="rounded-xl border border-border bg-card p-4 space-y-3"
        data-testid={`queue-request-${entry.id}`}
      >
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h3 className="font-semibold break-all">{entry.request.name}</h3>
          <span className="rounded-full bg-muted px-2 py-1 text-xs font-medium" role="status">
            {statusLabels[entry.status]}
          </span>
        </div>
        <div className="text-sm text-muted-foreground space-y-1">
          <p>
            {plans.find((plan) => plan.id === entry.request.plan_id)?.name ?? 'Selected plan'} ·{' '}
            {environments.find((environment) => environment.id === entry.request.environment_id)
              ?.name ?? 'Selected environment'}
          </p>
          <p>
            {resources.cpu} CPU · {resources.memory_mib.toLocaleString()} MiB RAM ·{' '}
            {resources.disk_mib.toLocaleString()} MiB disk
            {resources.gpu_count > 0 ? ` · ${resources.gpu_count} GPU` : ''}
          </p>
          <p>
            Requested {entry.requested_at ? formatDate(entry.requested_at) : 'time unavailable'}
          </p>
          {entry.status === 'pending' && entry.position !== null && entry.position > 0 && (
            <p>Priority position {entry.position}</p>
          )}
          {entry.expires_at && entry.status === 'pending' && (
            <p>Expires {formatDate(entry.expires_at)}</p>
          )}
          {detailed && entry.started_at && <p>Started {formatDate(entry.started_at)}</p>}
        </div>
        <p className="text-sm">{entry.message}</p>
        <div className="flex flex-wrap gap-2">
          {!detailed && (
            <Button variant="outline" size="sm" onClick={() => onSelect(entry.id)}>
              View request
            </Button>
          )}
          {canManage && canCancelQueuedRequest(entry) && (
            <Button
              variant="outline"
              size="sm"
              disabled={cancel.isPending}
              onClick={() => void cancelRequest(entry)}
            >
              Cancel request
            </Button>
          )}
          {entry.status === 'started' && launched && username && (
            <Link
              to="/user/$username/$serverName"
              params={{ username: launched.username || username, serverName: launched.name }}
              className="inline-flex items-center rounded-md px-3 py-2 text-sm font-medium text-primary hover:underline"
            >
              View server
            </Link>
          )}
        </div>
      </article>
    )
  }

  return (
    <section aria-label="Waiting server requests" className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Clock className="h-5 w-5" /> Waiting requests
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Requests that fit available capacity may start sooner. Priority position does not
            guarantee a start time. Waiting is not billed.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          aria-label="Refresh waiting requests"
          disabled={queue.isFetching}
          onClick={() => void queue.refetch()}
        >
          <RefreshCw className={`h-4 w-4 ${queue.isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>
      {queue.isError && <QueueErrorState error={queue.error} retry={() => void queue.refetch()} />}
      {queue.isPending && (
        <p role="status" className="py-8 text-muted-foreground">
          Loading requests…
        </p>
      )}
      {queue.data?.items.length === 0 && (
        <div className="rounded-xl border border-dashed border-border p-8 text-center">
          <h3 className="font-medium">No waiting requests</h3>
          <p className="text-sm text-muted-foreground mt-1">
            Requests appear here when capacity is unavailable.
          </p>
        </div>
      )}
      {queue.data && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {queue.data.items.map((entry) => (
              <div key={entry.id}>{renderRequest(entry, false)}</div>
            ))}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span>
              {queue.data.total} requests · Page {page} of{' '}
              {Math.max(1, Math.ceil(queue.data.total / queue.data.page_size))}
            </span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={page <= 1 || queue.isFetching}
                onClick={() => setPage(page - 1)}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={page * queue.data.page_size >= queue.data.total || queue.isFetching}
                onClick={() => setPage(page + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
      <Dialog
        open={!!requestId}
        onOpenChange={(open) => {
          if (!open) onSelect()
        }}
      >
        <DialogContent
          ref={detailRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={headingId}
          aria-describedby={descriptionId}
          tabIndex={-1}
          onKeyDown={(event) => {
            if (event.key !== 'Tab') return
            const controls = detailRef.current?.querySelectorAll<HTMLElement>(
              'button:not(:disabled), a[href], [tabindex="0"]'
            )
            const first = controls?.[0]
            const last = controls?.[controls.length - 1]
            if (!first || !last) {
              event.preventDefault()
              return
            }
            if (
              event.shiftKey &&
              (document.activeElement === first || document.activeElement === detailRef.current)
            ) {
              event.preventDefault()
              last.focus()
            } else if (
              !event.shiftKey &&
              (document.activeElement === last || document.activeElement === detailRef.current)
            ) {
              event.preventDefault()
              first.focus()
            }
          }}
        >
          <DialogHeader>
            <DialogTitle id={headingId}>Server request</DialogTitle>
            <DialogDescription id={descriptionId}>
              Saved configuration and current launch status.
            </DialogDescription>
          </DialogHeader>
          {detail.isPending && <p role="status">Loading request…</p>}
          {detail.isError && (
            <QueueErrorState error={detail.error} retry={() => void detail.refetch()} />
          )}
          {detail.data && renderRequest(detail.data, true)}
          <DialogClose onClick={() => onSelect()} />
        </DialogContent>
      </Dialog>
      {dialog}
    </section>
  )
}
