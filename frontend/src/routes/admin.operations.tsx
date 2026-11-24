// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  Archive,
  Clock,
  Eye,
  Filter,
  Inbox,
  RefreshCw,
  Rocket,
  ShieldCheck,
  Wrench,
} from 'lucide-react'
import { ResourcePageLayout } from '../components/layout/resource-page-layout'
import { DataTable } from '../components/data/data-table'
import { Select, SelectItem } from '../components/ui/select'
import { Button } from '../components/ui/button'
import { Tooltip } from '../components/ui/tooltip'
import { OperationStatusPills } from '../components/admin/operation-status'
import { OperationDetailDrawer, OperationTargetSummary } from '../components/admin/operation-detail'
import { useAdminOperations } from '../hooks/use-admin-operations'
import { useDataTable } from '../hooks/use-data-table'
import { useIsDesktopViewport } from '../hooks/use-is-desktop'
import { usePageGuard } from '../hooks/use-page-guard'
import {
  ADMIN_OPERATION_READ_PERMISSIONS,
  adminOperationAccess,
  adminOperationLoadErrorInfo,
  formatHeartbeatAge,
  operationActionLabel,
  operationOwnerLabel,
} from '../lib/admin-operations'
import { formatDate, formatRelativeTime } from '../lib/utils'
import { useAuthStore } from '../stores/auth-store'
import { useThemeStore } from '../stores/theme-store'
import type {
  AdminOperation,
  AdminOperationFilters,
  AdminOperationKind,
} from '../types/admin-operations'
import type { ColumnDef } from '@tanstack/react-table'

export const Route = createFileRoute('/admin/operations')({
  component: AdminOperationsPage,
})

type KindFilter = 'all' | AdminOperationKind
type RecoveryFilter = 'all' | 'required' | 'not_required'

const KIND_OPTIONS: Array<{ value: KindFilter; label: string }> = [
  { value: 'all', label: 'All kinds' },
  { value: 'launch', label: 'Launch' },
  { value: 'backup', label: 'Backup' },
  { value: 'restore', label: 'Restore' },
]

const LAUNCH_STATES = ['prepared', 'executing', 'uncertain', 'succeeded', 'failed']
const RESTORE_STATES = ['pending', 'in_progress', 'recovery_required', 'completed', 'failed']
const BACKUP_STATES = [...RESTORE_STATES, 'deleting', 'delete_failed', 'deleted']

const STATE_LABELS: Record<string, string> = {
  prepared: 'Prepared',
  executing: 'Executing',
  uncertain: 'Uncertain',
  pending: 'Pending',
  in_progress: 'In progress',
  recovery_required: 'Recovery required',
  succeeded: 'Succeeded',
  completed: 'Completed',
  failed: 'Failed',
  deleting: 'Deleting',
  delete_failed: 'Delete failed',
  deleted: 'Deleted',
}

function stateOptionsFor(kind: KindFilter): Array<{ value: string; label: string }> {
  const states =
    kind === 'launch'
      ? LAUNCH_STATES
      : kind === 'backup'
        ? BACKUP_STATES
        : kind === 'restore'
          ? RESTORE_STATES
          : Array.from(new Set([...LAUNCH_STATES, ...BACKUP_STATES]))
  return [
    { value: 'all', label: 'All states' },
    ...states.map((state) => ({ value: state, label: STATE_LABELS[state] ?? state })),
  ]
}

function kindIcon(kind: AdminOperationKind) {
  if (kind === 'launch') return Rocket
  if (kind === 'backup') return Archive
  return RefreshCw
}

function AdminOperationsPage() {
  const allowed = usePageGuard({
    permissions: [...ADMIN_OPERATION_READ_PERMISSIONS],
    requireAll: true,
    redirectTo: '/admin',
  })

  if (!allowed) return null

  return <AdminOperationsContent />
}

function AdminOperationsContent() {
  const hasAllPermissions = useAuthStore((state) => state.hasAllPermissions)
  const access = adminOperationAccess(hasAllPermissions)
  const density = useThemeStore((state) => state.density)
  const isDesktop = useIsDesktopViewport()

  const { state: tableState, setPage, setLimit } = useDataTable({ defaultLimit: 20 })
  const [kindFilter, setKindFilter] = useState<KindFilter>('all')
  const [stateFilter, setStateFilter] = useState('all')
  const [recoveryFilter, setRecoveryFilter] = useState<RecoveryFilter>('all')
  const [selected, setSelected] = useState<AdminOperation | null>(null)

  const filters = useMemo<AdminOperationFilters>(
    () => ({
      kind: kindFilter === 'all' ? null : kindFilter,
      state: stateFilter === 'all' ? null : stateFilter,
      recovery_required: recoveryFilter === 'all' ? null : recoveryFilter === 'required',
      limit: tableState.limit,
      offset: (tableState.page - 1) * tableState.limit,
    }),
    [kindFilter, stateFilter, recoveryFilter, tableState.limit, tableState.page]
  )

  const { data, isLoading, isError, error, refetch, isFetching } = useAdminOperations(filters)
  const operations = data?.items ?? []
  const pagination = data?.pagination
  const total = pagination?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / tableState.limit))
  const hasFilters = kindFilter !== 'all' || stateFilter !== 'all' || recoveryFilter !== 'all'
  const stateOptions = stateOptionsFor(kindFilter)
  const recoveryCount = operations.filter((operation) => operation.recovery_required).length
  const ambiguousCount = operations.filter((operation) => operation.liveness === 'ambiguous').length
  const activeCount = operations.filter(
    (operation) =>
      !['succeeded', 'completed', 'failed', 'deleted', 'cancelled'].includes(operation.state)
  ).length

  const clearFilters = () => {
    setKindFilter('all')
    setStateFilter('all')
    setRecoveryFilter('all')
    setPage(1)
  }

  const changeKind = (value: string) => {
    const next = value as KindFilter
    setKindFilter(next)
    if (
      stateFilter !== 'all' &&
      !stateOptionsFor(next).some((item) => item.value === stateFilter)
    ) {
      setStateFilter('all')
    }
    setPage(1)
  }

  const columns: ColumnDef<AdminOperation>[] = [
    {
      id: 'target',
      header: 'Target',
      enableSorting: false,
      cell: ({ row }) => {
        const operation = row.original
        const Icon = kindIcon(operation.kind)
        return (
          <div className="flex max-w-64 items-center gap-2">
            <div className="shrink-0 rounded-md bg-primary/10 p-1.5 text-primary">
              <Icon className="h-3.5 w-3.5" />
            </div>
            <OperationTargetSummary operation={operation} />
          </div>
        )
      },
    },
    {
      id: 'state',
      header: 'State',
      enableSorting: false,
      cell: ({ row }) => <OperationStatusPills operation={row.original} showRuntime={false} />,
    },
    {
      id: 'action',
      header: 'Action',
      enableSorting: false,
      cell: ({ row }) => (
        <div className="space-y-0.5 text-sm text-muted-foreground">
          <div>{operationActionLabel(row.original.action)}</div>
          <div className="break-all text-[10px]">Owner {operationOwnerLabel(row.original)}</div>
        </div>
      ),
    },
    {
      id: 'age',
      header: 'Age / heartbeat',
      enableSorting: false,
      cell: ({ row }) => {
        const operation = row.original
        return (
          <div className="space-y-0.5 text-xs">
            <div className="text-foreground">
              {operation.created_at ? formatRelativeTime(operation.created_at) : '—'}
            </div>
            <div className="text-muted-foreground">
              Heartbeat: {formatHeartbeatAge(operation.heartbeat_age_seconds)}
            </div>
          </div>
        )
      },
    },
    {
      id: 'timestamps',
      header: 'Updated / finished',
      enableSorting: false,
      cell: ({ row }) => {
        const operation = row.original
        return (
          <div className="space-y-0.5 text-xs">
            <div className="text-foreground">
              {operation.updated_at ? formatDate(operation.updated_at) : '—'}
            </div>
            <div className="text-muted-foreground">
              {operation.finished_at ? formatDate(operation.finished_at) : 'Not finished'}
            </div>
          </div>
        )
      },
    },
    {
      id: 'actions',
      header: '',
      enableSorting: false,
      size: 50,
      cell: ({ row }) => (
        <Tooltip content="View evidence">
          <button
            type="button"
            onClick={() => setSelected(row.original)}
            className="inline-flex rounded-lg p-1.5 text-primary transition-colors hover:bg-primary/10"
            aria-label="View operation evidence"
          >
            <Eye className="h-4 w-4" />
          </button>
        </Tooltip>
      ),
    },
  ]

  const mobileCardRenderer = (operation: AdminOperation) => {
    const Icon = kindIcon(operation.kind)
    return (
      <div className="space-y-3 p-4">
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <div className="shrink-0 rounded-md bg-primary/10 p-1.5 text-primary">
              <Icon className="h-3.5 w-3.5" />
            </div>
            <OperationTargetSummary operation={operation} />
          </div>
          <button
            type="button"
            onClick={() => setSelected(operation)}
            className="inline-flex rounded-lg p-1.5 text-primary transition-colors hover:bg-primary/10"
            aria-label="View operation evidence"
          >
            <Eye className="h-4 w-4" />
          </button>
        </div>
        <OperationStatusPills operation={operation} showRuntime={false} />
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>Owner: {operationOwnerLabel(operation)}</span>
          <span>Action: {operationActionLabel(operation.action)}</span>
          <span>Age: {operation.created_at ? formatRelativeTime(operation.created_at) : '—'}</span>
          <span>Heartbeat: {formatHeartbeatAge(operation.heartbeat_age_seconds)}</span>
        </div>
        {operation.recovery_required && (
          <p className="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            Operator review required. The row and its protections stay in place until proof supports
            a terminal transition.
          </p>
        )}
        <div className="text-xs text-muted-foreground">
          Updated: {operation.updated_at ? formatDate(operation.updated_at) : '—'}
        </div>
      </div>
    )
  }

  const emptyState = (
    <div className="bubble p-8 text-center">
      <Inbox className="mx-auto h-8 w-8 text-muted-foreground" />
      <p className="mt-3 text-sm font-medium">
        {hasFilters ? 'No operations match these filters' : 'No operations recorded'}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {hasFilters
          ? 'Adjust the filters or refresh to check for newer operations.'
          : 'Launch, backup, and restore work will appear here when it starts.'}
      </p>
      {hasFilters && (
        <Button type="button" size="sm" variant="outline" className="mt-3" onClick={clearFilters}>
          Clear filters
        </Button>
      )}
    </div>
  )

  return (
    <>
      <ResourcePageLayout
        title="Recovery Operations"
        subtitle="Proof-backed launch, backup, and restore evidence"
        icon={Wrench}
        backTo="/admin"
        stats={[
          {
            title: 'Operations',
            value: total,
            subtitle: 'All matching records',
            icon: Activity,
            iconColor: 'text-blue-400',
            bgColor: 'bg-blue-500/10',
          },
          {
            title: 'Recovery Required',
            value: recoveryCount,
            subtitle: 'On this page',
            icon: AlertTriangle,
            iconColor: recoveryCount > 0 ? 'text-amber-400' : 'text-emerald-400',
            bgColor: recoveryCount > 0 ? 'bg-amber-500/10' : 'bg-emerald-500/10',
          },
          {
            title: 'Ambiguous Liveness',
            value: ambiguousCount,
            subtitle: 'On this page',
            icon: ShieldCheck,
            iconColor: ambiguousCount > 0 ? 'text-amber-400' : 'text-emerald-400',
            bgColor: ambiguousCount > 0 ? 'bg-amber-500/10' : 'bg-emerald-500/10',
          },
          {
            title: 'Active',
            value: activeCount,
            subtitle: 'On this page',
            icon: Clock,
            iconColor: activeCount > 0 ? 'text-blue-400' : 'text-emerald-400',
            bgColor: 'bg-blue-500/10',
          },
        ]}
        actions={[
          {
            action: 'refresh',
            onClick: () => void refetch(),
            loading: isFetching,
          },
        ]}
      >
        <div className="bubble flex items-start gap-3 p-4">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <div className="min-w-0">
            <p className="text-sm font-medium">Proof-only reconciliation</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Reconcile reruns the read-only inspector and applies only a proof-backed outcome.
              Ambiguous evidence leaves the row protected; there is no force or override control.
            </p>
          </div>
        </div>

        <div className="bubble space-y-3 p-4">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            <Filter className="h-3.5 w-3.5" />
            Filters
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">Kind</span>
              <Select value={kindFilter} onChange={changeKind} data-testid="operation-kind-filter">
                {KIND_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">State</span>
              <Select
                value={stateFilter}
                onChange={(value) => {
                  setStateFilter(value)
                  setPage(1)
                }}
                data-testid="operation-state-filter"
              >
                {stateOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">Recovery</span>
              <Select
                value={recoveryFilter}
                onChange={(value) => {
                  setRecoveryFilter(value as RecoveryFilter)
                  setPage(1)
                }}
                data-testid="operation-recovery-filter"
              >
                <SelectItem value="all">All operations</SelectItem>
                <SelectItem value="required">Recovery required</SelectItem>
                <SelectItem value="not_required">No recovery required</SelectItem>
              </Select>
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={clearFilters}
              disabled={!hasFilters}
            >
              Clear filters
            </Button>
          </div>
        </div>

        {!access.canRead ? (
          <div className="bubble p-8 text-center text-sm text-muted-foreground">
            You do not have permission to view operations.
          </div>
        ) : (
          <DataTable
            columns={columns}
            data={operations}
            totalCount={total}
            pageCount={pageCount}
            page={tableState.page}
            limit={tableState.limit}
            sorting={[]}
            rowSelection={{}}
            columnFilters={[]}
            columnVisibility={{}}
            globalFilter=""
            isLoading={isLoading}
            isError={isError}
            errorMessage={isError ? adminOperationLoadErrorInfo(error).message : undefined}
            onPageChange={setPage}
            onLimitChange={setLimit}
            onSortingChange={() => undefined}
            onRowSelectionChange={() => undefined}
            onColumnFiltersChange={() => undefined}
            onColumnVisibilityChange={() => undefined}
            onGlobalFilterChange={() => undefined}
            getRowId={(operation) => `${operation.kind}:${operation.id}`}
            filters={[]}
            searchable={false}
            emptyState={emptyState}
            mobileCardRenderer={mobileCardRenderer}
            enableRowSelection={false}
            defaultMobileView={!isDesktop}
            density={density}
          />
        )}
      </ResourcePageLayout>

      {selected && (
        <OperationDetailDrawer
          key={`${selected.kind}:${selected.id}`}
          selected={selected}
          access={access}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  )
}
