// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { AlertTriangle, Inbox, ListOrdered, ShieldCheck } from 'lucide-react'
import { DataTable } from '../data/data-table'
import { Button } from '../ui/button'
import { QueueStatusPills } from './queue-status'
import {
  isQueueRecoveryRequired,
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

function QueueReferenceLine({ entry }: { entry: AdminQueueEntry }) {
  return (
    <div className="space-y-0.5 text-xs">
      <div className="text-foreground">Owner {shortQueueReference(entry.owner_id)}</div>
      <div className="text-muted-foreground">
        {entry.server_id ? `Server ${shortQueueReference(entry.server_id)}` : 'No linked server'}
      </div>
    </div>
  )
}

function QueueScopeLine({ entry }: { entry: AdminQueueEntry }) {
  return (
    <div className="space-y-0.5 text-xs">
      <div className="text-foreground">Environment {shortQueueReference(entry.environment_id)}</div>
      <div className="text-muted-foreground">Plan {shortQueueReference(entry.plan_id)}</div>
    </div>
  )
}

function QueuePositionLine({ entry }: { entry: AdminQueueEntry }) {
  const starting = entry.status === 'starting'
  return (
    <div className="space-y-0.5 text-xs">
      <div className="inline-flex items-center gap-1 text-foreground">
        <ListOrdered className="h-3 w-3" />
        {entry.position !== null ? `Position ${entry.position}` : 'No queue position'}
      </div>
      <div className="text-muted-foreground">Priority {entry.priority}</div>
      {starting && (
        <div className="flex items-start gap-1 text-amber-400/90">
          <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
          <span>
            {isQueueRecoveryRequired(entry.reason_code)
              ? 'Awaiting operator verification; no admin cancel or retry is available.'
              : 'No admin cancel or retry is available for starting requests.'}
          </span>
        </div>
      )}
    </div>
  )
}

function QueueTimeline({ entry }: { entry: AdminQueueEntry }) {
  return (
    <div className="space-y-0.5 text-xs" data-testid={`queue-timeline-${entry.id || 'unknown'}`}>
      <div className="text-foreground">
        Requested {queueRelativeTimestampLabel(entry.requested_at)}
      </div>
      <div className="text-muted-foreground">{queueTimestampLabel(entry.requested_at)}</div>
      <div className="text-muted-foreground">Started {queueTimestampLabel(entry.started_at)}</div>
      <div className="text-muted-foreground">Failed {queueTimestampLabel(entry.failed_at)}</div>
      <div className="text-muted-foreground">Expires {queueTimestampLabel(entry.expires_at)}</div>
    </div>
  )
}

export function QueueMobileCard({ entry }: { entry: AdminQueueEntry }) {
  return (
    <div className="space-y-3 p-4" data-testid={`admin-queue-card-${entry.id || 'unknown'}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{entry.server_name}</p>
          <p className="font-mono text-[10px] text-muted-foreground">
            Request {shortQueueReference(entry.id)}
          </p>
        </div>
        <QueueStatusPills entry={entry} />
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <QueueReferenceLine entry={entry} />
        <QueueScopeLine entry={entry} />
      </div>
      <QueuePositionLine entry={entry} />
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="col-span-2">
          Requested {queueRelativeTimestampLabel(entry.requested_at)} ·{' '}
          {queueTimestampLabel(entry.requested_at)}
        </span>
        <span>Started {queueTimestampLabel(entry.started_at)}</span>
        <span>Failed {queueTimestampLabel(entry.failed_at)}</span>
        <span>Expires {queueTimestampLabel(entry.expires_at)}</span>
      </div>
      <p className="text-[11px] text-muted-foreground">
        Read-only request metadata. Request payloads, mounts, tokens, and environment values are
        never shown here.
      </p>
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

function columnHeader(label: string) {
  return <span>{label}</span>
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
      header: () => columnHeader('Request'),
      enableSorting: false,
      cell: ({ row }) => (
        <div className="max-w-56 space-y-0.5">
          <div className="truncate text-sm font-medium">{row.original.server_name}</div>
          <div className="font-mono text-[10px] text-muted-foreground">
            Request {shortQueueReference(row.original.id)}
          </div>
        </div>
      ),
    },
    {
      id: 'status',
      header: () => columnHeader('Status'),
      enableSorting: false,
      cell: ({ row }) => <QueueStatusPills entry={row.original} />,
    },
    {
      id: 'queue',
      header: () => columnHeader('Position / priority'),
      enableSorting: false,
      cell: ({ row }) => <QueuePositionLine entry={row.original} />,
    },
    {
      id: 'references',
      header: () => columnHeader('Owner / server'),
      enableSorting: false,
      cell: ({ row }) => <QueueReferenceLine entry={row.original} />,
    },
    {
      id: 'scope',
      header: () => columnHeader('Plan / environment'),
      enableSorting: false,
      cell: ({ row }) => <QueueScopeLine entry={row.original} />,
    },
    {
      id: 'timeline',
      header: () => columnHeader('Timeline'),
      enableSorting: false,
      cell: ({ row }) => <QueueTimeline entry={row.original} />,
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
      density={density}
    />
  )
}
