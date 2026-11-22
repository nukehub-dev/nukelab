// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { AlertTriangle, Clock, Inbox, ListOrdered, ShieldCheck, Timer } from 'lucide-react'
import { DataTable } from '../data/data-table'
import { useIsDesktopViewport } from '../../hooks/use-is-desktop'
import { Button } from '../ui/button'
import { QueueResourceChips } from './queue-resources'
import { QueueStatusPills } from './queue-status'
import {
  isQueueRecoveryRequired,
  queueEnvironmentLabel,
  queueOwnerLabel,
  queuePlanLabel,
  queueReasonPresentation,
  queueRelativeTimestampLabel,
  queueTimestampLabel,
  sanitizeQueueEntry,
  shortQueueReference,
} from '../../lib/admin-queue'
import type { AdminQueueEntry } from '../../types/admin-queue'
import type { ColumnDef } from '@tanstack/react-table'

interface AdminQueueTableProps {
  entries: AdminQueueEntry[]
  totalCount: number
  page: number
  pageCount: number
  limit: number
  isLoading?: boolean
  isError?: boolean
  errorMessage?: string
  hasFilters?: boolean
  onClearFilters?: () => void
  onPageChange: (page: number) => void
  onLimitChange: (limit: number) => void
  onRetry?: () => void
  density?: 'compact' | 'comfortable'
}

function QueueScopeCell({ entry }: { entry: AdminQueueEntry }) {
  return (
    <div className="max-w-64 space-y-0.5 text-xs">
      <div className="break-words text-foreground">
        Owner {queueOwnerLabel(entry)} · Plan {queuePlanLabel(entry)}
      </div>
      <div className="break-words text-muted-foreground">
        Environment {queueEnvironmentLabel(entry)}
        {entry.server_id
          ? ` · Server ${shortQueueReference(entry.server_id)}`
          : ' · No linked server'}
      </div>
    </div>
  )
}

function QueuePositionLine({ entry }: { entry: AdminQueueEntry }) {
  const queued = entry.status === 'pending' || entry.status === 'scheduled'
  const starting = entry.status === 'starting'
  return (
    <div className="space-y-0.5 text-xs">
      <div className="inline-flex items-center gap-1 text-foreground">
        <ListOrdered className="h-3 w-3" />
        {queued && entry.position !== null ? `Position ${entry.position}` : 'Not queued'}
      </div>
      {queued && <div className="text-muted-foreground">Priority {entry.priority}</div>}
      {starting && (
        <div className="flex items-start gap-1 text-amber-400/90">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          <span>
            {isQueueRecoveryRequired(entry.reason_code)
              ? 'Operator verification required; read-only.'
              : 'Starting; no admin cancel or retry.'}
          </span>
        </div>
      )}
    </div>
  )
}

export function QueueMobileCard({ entry }: { entry: AdminQueueEntry }) {
  const queued = entry.status === 'pending' || entry.status === 'scheduled'
  const showRecovery = isQueueRecoveryRequired(entry.reason_code)
  return (
    <div className="space-y-3 p-4" data-testid={`admin-queue-card-${entry.id || 'unknown'}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium">{entry.server_name}</p>
            <QueueStatusPills entry={entry} />
          </div>
          <p className="mt-1 font-mono text-[10px] text-muted-foreground">
            Request {shortQueueReference(entry.id)}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="break-words">Owner {queueOwnerLabel(entry)}</span>
        <span className="break-words">Plan {queuePlanLabel(entry)}</span>
        <span className="break-words">Environment {queueEnvironmentLabel(entry)}</span>
        {entry.server_id && <span>Server {shortQueueReference(entry.server_id)}</span>}
      </div>

      <QueueResourceChips resources={entry.resources} compact />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          Requested {queueRelativeTimestampLabel(entry.requested_at)}
        </span>
        {entry.expires_at && (
          <span className="inline-flex items-center gap-1">
            <Timer className="h-3 w-3" />
            Expires {queueTimestampLabel(entry.expires_at)}
          </span>
        )}
        {queued && entry.position !== null && entry.position > 0 && (
          <span className="inline-flex items-center gap-1 font-medium text-foreground">
            <ListOrdered className="h-3 w-3" />
            Position {entry.position}
          </span>
        )}
        {entry.started_at && (
          <span className="inline-flex items-center gap-1">
            Started {queueTimestampLabel(entry.started_at)}
          </span>
        )}
      </div>

      {showRecovery ? (
        <p className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          Awaiting operator verification; no admin cancel or retry is available, and the linked
          operation remains protected.
        </p>
      ) : entry.status === 'failed' && entry.reason_code ? (
        <p className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {queueReasonPresentation(entry.reason_code)?.label ?? 'Request failed'}
        </p>
      ) : (
        entry.status === 'starting' && (
          <p className="text-xs text-muted-foreground">
            Starting work cannot be cancelled. Resolve it through operation reconciliation.
          </p>
        )
      )}
    </div>
  )
}

function QueueEmptyState({
  hasFilters,
  onClearFilters,
}: {
  hasFilters: boolean
  onClearFilters?: () => void
}) {
  return (
    <div className="bubble p-8 text-center">
      {hasFilters ? (
        <Inbox className="mx-auto h-8 w-8 text-muted-foreground" />
      ) : (
        <ShieldCheck className="mx-auto h-8 w-8 text-muted-foreground" />
      )}
      <p className="mt-3 text-sm font-medium">
        {hasFilters ? 'No queue requests match these filters' : 'No server requests queued'}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {hasFilters
          ? 'Adjust the filters or refresh to check for newer requests.'
          : 'Requests appear here when capacity is unavailable or a launch is starting. Starting rows stay visible even when no operation is linked.'}
      </p>
      {hasFilters && onClearFilters && (
        <Button type="button" size="sm" variant="outline" className="mt-3" onClick={onClearFilters}>
          Clear filters
        </Button>
      )}
    </div>
  )
}

/**
 * Bounded, read-only queue table. It intentionally has no row actions:
 * admin cancellation and retry do not exist for this view.
 */
export function AdminQueueTable({
  entries,
  totalCount,
  page,
  pageCount,
  limit,
  isLoading = false,
  isError = false,
  errorMessage,
  hasFilters = false,
  onClearFilters,
  onPageChange,
  onLimitChange,
  onRetry,
  density = 'comfortable',
}: AdminQueueTableProps) {
  const isDesktop = useIsDesktopViewport()
  const items = entries.map(sanitizeQueueEntry)

  if (isError) {
    return (
      <div
        role="alert"
        className="bubble flex flex-col gap-3 border border-destructive/20 p-4 sm:flex-row sm:items-start"
      >
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
          <AlertTriangle className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-sm font-medium">Could not load queue requests</p>
          <p className="text-xs text-muted-foreground">
            {errorMessage ?? 'Queue visibility could not be refreshed. Try again.'}
          </p>
        </div>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            Try again
          </Button>
        )}
      </div>
    )
  }

  const columns: ColumnDef<AdminQueueEntry>[] = [
    {
      id: 'request',
      header: 'Request',
      enableSorting: false,
      cell: ({ row }) => (
        <div className="max-w-64 space-y-0.5">
          <div className="truncate text-sm font-medium">{row.original.server_name}</div>
          <div className="font-mono text-[10px] text-muted-foreground">
            Request {shortQueueReference(row.original.id)}
          </div>
          <div className="text-[10px] text-muted-foreground">
            Requested {queueRelativeTimestampLabel(row.original.requested_at)}
            {row.original.expires_at
              ? ` · Expires ${queueRelativeTimestampLabel(row.original.expires_at)}`
              : ''}
          </div>
        </div>
      ),
    },
    {
      id: 'status',
      header: 'Status',
      enableSorting: false,
      cell: ({ row }) => <QueueStatusPills entry={row.original} />,
    },
    {
      id: 'resources',
      header: 'Resources',
      enableSorting: false,
      cell: ({ row }) => <QueueResourceChips resources={row.original.resources} compact />,
    },
    {
      id: 'queue',
      header: 'Position',
      enableSorting: false,
      cell: ({ row }) => <QueuePositionLine entry={row.original} />,
    },
    {
      id: 'scope',
      header: 'Owner / scope',
      enableSorting: false,
      cell: ({ row }) => <QueueScopeCell entry={row.original} />,
    },
  ]

  return (
    <DataTable
      columns={columns}
      data={items}
      totalCount={totalCount}
      pageCount={pageCount}
      page={page}
      limit={limit}
      sorting={[]}
      rowSelection={{}}
      columnFilters={[]}
      columnVisibility={{}}
      globalFilter=""
      isLoading={isLoading}
      onPageChange={onPageChange}
      onLimitChange={onLimitChange}
      onSortingChange={() => undefined}
      onRowSelectionChange={() => undefined}
      onColumnFiltersChange={() => undefined}
      onColumnVisibilityChange={() => undefined}
      onGlobalFilterChange={() => undefined}
      getRowId={(entry) => entry.id || 'unknown-request'}
      filters={[]}
      searchable={false}
      emptyState={<QueueEmptyState hasFilters={hasFilters} onClearFilters={onClearFilters} />}
      mobileCardRenderer={(entry) => <QueueMobileCard entry={entry} />}
      enableRowSelection={false}
      defaultMobileView={!isDesktop}
      density={density}
    />
  )
}
