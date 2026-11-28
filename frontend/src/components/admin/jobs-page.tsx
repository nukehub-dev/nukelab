// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMemo, useState } from 'react'
import { Activity, AlertTriangle, Clock, Filter, ShieldCheck, Terminal } from 'lucide-react'
import { ResourcePageLayout } from '../layout/resource-page-layout'
import { Button } from '../ui/button'
import { Select, SelectItem } from '../ui/select'
import { AdminJobsTable } from './jobs-table'
import { AdminJobCancelDialog, AdminJobCancelOutcome } from './job-cancel-dialog'
import { AdminJobReconcileDialog, AdminJobReconcileOutcome } from './job-reconcile-dialog'
import { useAdminJobs, useCancelAdminJob, useReconcileAdminJob } from '../../hooks/use-admin-jobs'
import { useDataTable } from '../../hooks/use-data-table'
import { usePageGuard } from '../../hooks/use-page-guard'
import {
  ADMIN_JOB_AGE_OPTIONS,
  ADMIN_JOB_READ_ANY_PERMISSIONS,
  adminJobAccess,
  adminJobCancelErrorInfo,
  adminJobReconcileErrorInfo,
  adminJobsLoadErrorInfo,
  emptyAdminJobSummary,
  sanitizeAdminJobSummary,
  type AdminJobAgeFilter,
  type AdminJobErrorInfo,
} from '../../lib/admin-jobs'
import { PERMISSIONS, useAuthStore } from '../../stores/auth-store'
import { useThemeStore } from '../../stores/theme-store'
import type {
  AdminJobCancelResult,
  AdminJobEntry,
  AdminJobFilters,
  AdminJobListState,
  AdminJobReconcileResult,
} from '../../types/admin-jobs'

const STATE_OPTIONS: Array<{ value: AdminJobListState; label: string }> = [
  { value: 'all', label: 'All jobs' },
  { value: 'active', label: 'Active' },
  { value: 'history', label: 'History' },
]

export function AdminJobsPageContent() {
  const density = useThemeStore((state) => state.density)
  const { state: tableState, setPage, setLimit } = useDataTable({ defaultLimit: 20 })
  const [stateFilter, setStateFilter] = useState<AdminJobListState>('all')
  const [ageFilter, setAgeFilter] = useState<AdminJobAgeFilter>('all')

  const filters = useMemo<AdminJobFilters>(
    () => ({
      state: stateFilter,
      age_min_seconds:
        ADMIN_JOB_AGE_OPTIONS.find((option) => option.value === ageFilter)?.seconds ?? null,
      limit: tableState.limit,
      offset: (tableState.page - 1) * tableState.limit,
    }),
    [stateFilter, ageFilter, tableState.limit, tableState.page]
  )

  const { data, isLoading, isError, error, refetch, isFetching } = useAdminJobs(filters)
  const entries = data?.items ?? []
  const total = data?.pagination.total ?? 0
  const summary = data?.summary ? sanitizeAdminJobSummary(data.summary) : emptyAdminJobSummary()
  const pageCount = Math.max(1, Math.ceil(total / tableState.limit))
  const hasFilters = stateFilter !== 'all' || ageFilter !== 'all'
  const activeCount = summary.queued + summary.starting + summary.running + summary.cancelling
  const failedCount = summary.failed + summary.timed_out

  const canManage = useAuthStore(
    (state) =>
      adminJobAccess(
        (permissions) => state.hasAllPermissions(permissions),
        (permissions) => state.hasAnyPermission(permissions)
      ).canManage
  )
  const reconcile = useReconcileAdminJob()
  const cancel = useCancelAdminJob()
  const [reconcileEntry, setReconcileEntry] = useState<AdminJobEntry | null>(null)
  const [reconcileResult, setReconcileResult] = useState<AdminJobReconcileResult | null>(null)
  const [reconcileError, setReconcileError] = useState<AdminJobErrorInfo | null>(null)
  const [cancelEntry, setCancelEntry] = useState<AdminJobEntry | null>(null)
  const [cancelResult, setCancelResult] = useState<AdminJobCancelResult | null>(null)
  const [cancelError, setCancelError] = useState<AdminJobErrorInfo | null>(null)

  const openReconcile = (entry: AdminJobEntry) => {
    if (!canManage || !entry.can_reconcile) return
    reconcile.reset()
    setReconcileError(null)
    setReconcileEntry(entry)
  }

  const closeReconcile = () => {
    if (reconcile.isPending) return
    setReconcileEntry(null)
    setReconcileError(null)
  }

  const submitReconcile = (reason: string) => {
    if (!reconcileEntry) return
    setReconcileError(null)
    reconcile.mutate(
      { id: reconcileEntry.id, reason },
      {
        onSuccess: (result) => {
          setReconcileError(null)
          setReconcileResult(result)
          setReconcileEntry(null)
        },
        onError: (mutationError) => {
          setReconcileResult(null)
          setReconcileError(adminJobReconcileErrorInfo(mutationError))
        },
      }
    )
  }

  const openCancel = (entry: AdminJobEntry) => {
    if (!canManage || !entry.can_cancel) return
    cancel.reset()
    setCancelError(null)
    setCancelEntry(entry)
  }

  const closeCancel = () => {
    if (cancel.isPending) return
    setCancelEntry(null)
    setCancelError(null)
  }

  const submitCancel = (reason: string) => {
    if (!cancelEntry) return
    setCancelError(null)
    cancel.mutate(
      { id: cancelEntry.id, reason },
      {
        onSuccess: (result) => {
          setCancelError(null)
          setCancelResult(result)
          setCancelEntry(null)
        },
        onError: (mutationError) => {
          setCancelResult(null)
          setCancelError(adminJobCancelErrorInfo(mutationError))
        },
      }
    )
  }

  const clearFilters = () => {
    setStateFilter('all')
    setAgeFilter('all')
    setPage(1)
  }

  return (
    <div data-testid="admin-jobs-page">
      <ResourcePageLayout
        title="Batch Jobs"
        subtitle="Cross-owner job state, safe cancellation, and proof-backed recovery"
        icon={Terminal}
        backTo="/admin"
        stats={[
          {
            title: 'Jobs',
            value: summary.total,
            subtitle: 'Age filter applied; all pages',
            icon: Activity,
            iconColor: 'text-blue-400',
            bgColor: 'bg-blue-500/10',
          },
          {
            title: 'Active',
            value: activeCount,
            subtitle: 'Queued through cancelling',
            icon: Clock,
            iconColor: activeCount > 0 ? 'text-blue-400' : 'text-emerald-400',
            bgColor: 'bg-blue-500/10',
          },
          {
            title: 'Recovery Required',
            value: summary.recovery_required,
            subtitle: 'Operator verification needed',
            icon: AlertTriangle,
            iconColor: summary.recovery_required > 0 ? 'text-amber-400' : 'text-emerald-400',
            bgColor: summary.recovery_required > 0 ? 'bg-amber-500/10' : 'bg-emerald-500/10',
          },
          {
            title: 'Failed / Timed out',
            value: failedCount,
            subtitle: 'All pages',
            icon: ShieldCheck,
            iconColor: failedCount > 0 ? 'text-red-400' : 'text-emerald-400',
            bgColor: 'bg-red-500/10',
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
            <p className="text-sm font-medium">Proof-backed recovery and safe cancellation</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Command arguments, logs, and environment values stay with the job owner. Operators
              with manage permission can request cancellation of a queued, starting, or running job
              with a recorded reason. A started job stops only after verified runtime termination;
              cancellation never force-releases a reservation, volume guard, or credit hold. A
              recovery-required row is reconcile-only, and reconcile reruns read-only proof
              inspection without a force path.
            </p>
          </div>
        </div>

        {cancelResult && (
          <AdminJobCancelOutcome result={cancelResult} onDismiss={() => setCancelResult(null)} />
        )}

        {reconcileResult && (
          <AdminJobReconcileOutcome
            result={reconcileResult}
            onDismiss={() => setReconcileResult(null)}
          />
        )}

        <div className="bubble space-y-3 p-4">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            <Filter className="h-3.5 w-3.5" />
            Filters
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">State</span>
              <Select
                value={stateFilter}
                onChange={(value) => {
                  setStateFilter(value as AdminJobListState)
                  setPage(1)
                }}
                data-testid="admin-jobs-state-filter"
              >
                {STATE_OPTIONS.map((option) => (
                  <SelectItem
                    key={option.value}
                    value={option.value}
                    data-testid={`admin-jobs-state-${option.value}`}
                  >
                    {option.label}
                  </SelectItem>
                ))}
              </Select>
            </div>
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">Age</span>
              <Select
                value={ageFilter}
                onChange={(value) => {
                  setAgeFilter(value as AdminJobAgeFilter)
                  setPage(1)
                }}
                data-testid="admin-jobs-age-filter"
              >
                {ADMIN_JOB_AGE_OPTIONS.map((option) => (
                  <SelectItem
                    key={option.value}
                    value={option.value}
                    data-testid={`admin-jobs-age-${option.value}`}
                  >
                    {option.label}
                  </SelectItem>
                ))}
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

        <AdminJobsTable
          entries={entries}
          totalCount={total}
          page={tableState.page}
          pageCount={pageCount}
          limit={tableState.limit}
          isLoading={isLoading}
          isError={isError}
          errorMessage={isError ? adminJobsLoadErrorInfo(error).message : undefined}
          hasFilters={hasFilters}
          canManage={canManage}
          onClearFilters={clearFilters}
          onPageChange={setPage}
          onLimitChange={setLimit}
          onRetry={() => void refetch()}
          onCancel={openCancel}
          onReconcile={openReconcile}
          density={density}
        />
      </ResourcePageLayout>

      {cancelEntry && (
        <AdminJobCancelDialog
          entry={cancelEntry}
          busy={cancel.isPending}
          error={cancelError}
          onSubmit={submitCancel}
          onClose={closeCancel}
        />
      )}

      {reconcileEntry && (
        <AdminJobReconcileDialog
          entry={reconcileEntry}
          busy={reconcile.isPending}
          error={reconcileError}
          onSubmit={submitReconcile}
          onClose={closeReconcile}
        />
      )}
    </div>
  )
}

export function AdminJobsPage() {
  const allowed = usePageGuard({
    permission: PERMISSIONS.ADMIN_ACCESS,
    anyPermission: [...ADMIN_JOB_READ_ANY_PERMISSIONS],
    redirectTo: '/admin',
  })

  if (!allowed) return null

  return <AdminJobsPageContent />
}
