// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import {
  AlertTriangle,
  Ban,
  Clock,
  HeartPulse,
  Inbox,
  ShieldCheck,
  Terminal,
  Timer,
  Wrench,
} from 'lucide-react'
import { DataTable } from '../data/data-table'
import { useIsDesktopViewport } from '../../hooks/use-is-desktop'
import { Button } from '../ui/button'
import { AdminJobStatusPills } from './job-status'
import {
  adminJobCleanupStateLabel,
  adminJobCreatedLabel,
  adminJobEnvironmentLabel,
  adminJobHeartbeatLabel,
  adminJobLogStateLabel,
  adminJobOwnerLabel,
  adminJobOwnerName,
  adminJobPlanLabel,
  adminJobReasonPresentation,
  adminJobTimestampLabel,
  adminJobVolumeLabel,
  isAdminJobRecoveryRequired,
  sanitizeAdminJobEntry,
  shortAdminJobReference,
} from '../../lib/admin-jobs'
import type { AdminJobEntry } from '../../types/admin-jobs'
import type { ColumnDef } from '@tanstack/react-table'

interface AdminJobsTableProps {
  entries: AdminJobEntry[]
  totalCount: number
  page: number
  pageCount: number
  limit: number
  isLoading?: boolean
  isError?: boolean
  errorMessage?: string
  hasFilters?: boolean
  canManage?: boolean
  onClearFilters?: () => void
  onPageChange: (page: number) => void
  onLimitChange: (limit: number) => void
  onRetry?: () => void
  onCancel?: (entry: AdminJobEntry) => void
  onReconcile?: (entry: AdminJobEntry) => void
  density?: 'compact' | 'comfortable'
}

function JobIdentityCell({ entry }: { entry: AdminJobEntry }) {
  return (
    <div className="max-w-56 space-y-0.5 whitespace-normal text-xs">
      <div className="font-mono text-[11px] text-foreground">
        Job {shortAdminJobReference(entry.id)}
      </div>
      <div className="text-muted-foreground">Created {adminJobCreatedLabel(entry.created_at)}</div>
      <div className="text-muted-foreground">
        Updated {adminJobTimestampLabel(entry.updated_at)}
      </div>
      {entry.finished_at && (
        <div className="text-muted-foreground">
          Finished {adminJobTimestampLabel(entry.finished_at)}
        </div>
      )}
    </div>
  )
}

function JobScopeCell({ entry }: { entry: AdminJobEntry }) {
  const ownerName = adminJobOwnerName(entry)
  return (
    <div className="max-w-72 space-y-0.5 whitespace-normal text-xs">
      <div className="break-words text-foreground">
        Owner {adminJobOwnerLabel(entry)}
        {ownerName && ownerName !== entry.owner_username ? ` · ${ownerName}` : ''}
      </div>
      <div className="break-words text-muted-foreground">
        Environment {adminJobEnvironmentLabel(entry)}
      </div>
      <div className="break-words text-muted-foreground">
        Plan {adminJobPlanLabel(entry)} · Volume {adminJobVolumeLabel(entry)}
      </div>
    </div>
  )
}

function JobProtectionCell({ entry }: { entry: AdminJobEntry }) {
  return (
    <div className="space-y-1 whitespace-normal text-xs">
      <div className="inline-flex items-center gap-1.5 text-foreground">
        <ShieldCheck className="h-3 w-3 shrink-0" />
        {entry.reservation_active ? 'Reservation held' : 'No reservation'}
      </div>
      <div className="text-muted-foreground">
        {entry.guard_active ? 'Volume guard active' : 'No active volume guard'}
      </div>
      <div className="inline-flex items-center gap-1 text-muted-foreground">
        <HeartPulse className="h-3 w-3 shrink-0" />
        Heartbeat {adminJobHeartbeatLabel(entry.heartbeat_age_seconds)}
      </div>
    </div>
  )
}

function JobEvidenceCell({ entry }: { entry: AdminJobEntry }) {
  return (
    <div className="space-y-1 whitespace-normal text-xs">
      <div className="text-foreground">Logs {adminJobLogStateLabel(entry.log_state)}</div>
      <div className="text-muted-foreground">
        Cleanup {adminJobCleanupStateLabel(entry.cleanup_state)}
        {entry.cleanup_attempts > 0 ? ` · ${entry.cleanup_attempts} attempts` : ''}
      </div>
      <div className="text-muted-foreground">No command or log content in this view</div>
    </div>
  )
}

function JobActionCell({
  entry,
  onCancel,
  onReconcile,
}: {
  entry: AdminJobEntry
  onCancel?: (entry: AdminJobEntry) => void
  onReconcile?: (entry: AdminJobEntry) => void
}) {
  const actions = []
  if (entry.can_cancel && onCancel) {
    actions.push(
      <Button
        key="cancel"
        type="button"
        size="sm"
        variant="outline"
        className="gap-1.5"
        aria-label={`Cancel job ${shortAdminJobReference(entry.id)}`}
        data-testid={`admin-job-cancel-${entry.id}`}
        onClick={() => onCancel(entry)}
      >
        <Ban className="h-3.5 w-3.5" />
        Cancel
      </Button>
    )
  }
  if (entry.can_reconcile && onReconcile) {
    actions.push(
      <Button
        key="reconcile"
        type="button"
        size="sm"
        variant="outline"
        className="gap-1.5"
        aria-label={`Reconcile job ${shortAdminJobReference(entry.id)}`}
        data-testid={`admin-job-reconcile-${entry.id}`}
        onClick={() => onReconcile(entry)}
      >
        <Wrench className="h-3.5 w-3.5" />
        Reconcile
      </Button>
    )
  }
  if (actions.length === 0) {
    return <span className="text-xs text-muted-foreground">—</span>
  }
  return <div className="flex flex-wrap gap-1.5">{actions}</div>
}

export function AdminJobMobileCard({
  entry,
  onCancel,
  onReconcile,
}: {
  entry: AdminJobEntry
  onCancel?: (entry: AdminJobEntry) => void
  onReconcile?: (entry: AdminJobEntry) => void
}) {
  const recovery = isAdminJobRecoveryRequired(entry.state)
  const reason = adminJobReasonPresentation(entry.reason_code)
  return (
    <div className="space-y-3 p-4" data-testid={`admin-job-card-${entry.id || 'unknown'}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-mono text-sm font-medium">Job {shortAdminJobReference(entry.id)}</p>
            <AdminJobStatusPills entry={entry} />
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Created {adminJobCreatedLabel(entry.created_at)}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="break-words">Owner {adminJobOwnerLabel(entry)}</span>
        <span className="break-words">Environment {adminJobEnvironmentLabel(entry)}</span>
        <span className="break-words">Plan {adminJobPlanLabel(entry)}</span>
        <span className="break-words">Volume {adminJobVolumeLabel(entry)}</span>
      </div>

      {reason && <p className="text-xs text-muted-foreground">Reason: {reason.label}</p>}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          Heartbeat {adminJobHeartbeatLabel(entry.heartbeat_age_seconds)}
        </span>
        <span className="inline-flex items-center gap-1">
          <ShieldCheck className="h-3 w-3" />
          {entry.reservation_active ? 'Reservation held' : 'No reservation'}
        </span>
        <span>{entry.guard_active ? 'Volume guard active' : 'No volume guard'}</span>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
        <span>Logs {adminJobLogStateLabel(entry.log_state)}</span>
        <span className="inline-flex items-center gap-1">
          <Timer className="h-3 w-3" />
          Cleanup {adminJobCleanupStateLabel(entry.cleanup_state)}
          {entry.cleanup_attempts > 0 ? ` · ${entry.cleanup_attempts} attempts` : ''}
        </span>
      </div>

      {entry.finished_at && (
        <p className="text-xs text-muted-foreground">
          Finished {adminJobTimestampLabel(entry.finished_at)}
        </p>
      )}

      {recovery ? (
        <p className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          Uncertain outcome. Proof-backed reconciliation is the only recovery action; it cannot
          force a state, and the reservation and volume guard stay in place until runtime proof is
          available.
        </p>
      ) : (
        entry.guard_active && (
          <p className="rounded-lg border border-sky-500/20 bg-sky-500/10 px-3 py-2 text-xs text-sky-200">
            The volume guard is still active. A cancellation request stops only after verified
            runtime termination, and the guard is never force-released.
          </p>
        )
      )}

      {onCancel && entry.can_cancel && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="w-full gap-1.5"
          aria-label={`Cancel job ${shortAdminJobReference(entry.id)}`}
          data-testid={`admin-job-card-cancel-${entry.id}`}
          onClick={() => onCancel(entry)}
        >
          <Ban className="h-3.5 w-3.5" />
          Request cancellation
        </Button>
      )}

      {onReconcile && entry.can_reconcile && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="w-full gap-1.5"
          aria-label={`Reconcile job ${shortAdminJobReference(entry.id)}`}
          data-testid={`admin-job-card-reconcile-${entry.id}`}
          onClick={() => onReconcile(entry)}
        >
          <Wrench className="h-3.5 w-3.5" />
          Reconcile with proof
        </Button>
      )}
    </div>
  )
}

function JobsEmptyState({
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
        <Terminal className="mx-auto h-8 w-8 text-muted-foreground" />
      )}
      <p className="mt-3 text-sm font-medium">
        {hasFilters ? 'No batch jobs match these filters' : 'No batch jobs recorded'}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {hasFilters
          ? 'Adjust the filters or refresh to check for newer jobs.'
          : 'Submitted jobs appear here with sanitized state and target labels.'}
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
 * Bounded job table. Only operators with manage permission see a row action,
 * and only when the server marks the row cancellable or reconcilable. It never
 * exposes retry, logs, argv, or raw runtime control.
 */
export function AdminJobsTable({
  entries,
  totalCount,
  page,
  pageCount,
  limit,
  isLoading = false,
  isError = false,
  errorMessage,
  hasFilters = false,
  canManage = false,
  onClearFilters,
  onPageChange,
  onLimitChange,
  onRetry,
  onCancel,
  onReconcile,
  density = 'comfortable',
}: AdminJobsTableProps) {
  const isDesktop = useIsDesktopViewport()
  const items = entries.map(sanitizeAdminJobEntry)

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
          <p className="text-sm font-medium">Could not load batch jobs</p>
          <p className="text-xs text-muted-foreground">
            {errorMessage ?? 'Job visibility could not be refreshed. Try again.'}
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

  const columns: ColumnDef<AdminJobEntry>[] = [
    {
      id: 'job',
      header: 'Job',
      enableSorting: false,
      cell: ({ row }) => <JobIdentityCell entry={row.original} />,
    },
    {
      id: 'state',
      header: 'State',
      enableSorting: false,
      cell: ({ row }) => <AdminJobStatusPills entry={row.original} />,
    },
    {
      id: 'scope',
      header: 'Owner / target',
      enableSorting: false,
      cell: ({ row }) => <JobScopeCell entry={row.original} />,
    },
    {
      id: 'protection',
      header: 'Protection',
      enableSorting: false,
      cell: ({ row }) => <JobProtectionCell entry={row.original} />,
    },
    {
      id: 'evidence',
      header: 'Logs / cleanup',
      enableSorting: false,
      cell: ({ row }) => <JobEvidenceCell entry={row.original} />,
    },
  ]

  if (canManage && (onCancel || onReconcile)) {
    columns.push({
      id: 'action',
      header: 'Action',
      enableSorting: false,
      cell: ({ row }) => (
        <JobActionCell entry={row.original} onCancel={onCancel} onReconcile={onReconcile} />
      ),
    })
  }

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
      getRowId={(entry) => entry.id || 'unknown-job'}
      filters={[]}
      searchable={false}
      emptyState={<JobsEmptyState hasFilters={hasFilters} onClearFilters={onClearFilters} />}
      mobileCardRenderer={(entry) => (
        <AdminJobMobileCard
          entry={entry}
          onCancel={canManage ? onCancel : undefined}
          onReconcile={canManage ? onReconcile : undefined}
        />
      )}
      enableRowSelection={false}
      defaultMobileView={!isDesktop}
      density={density}
    />
  )
}
