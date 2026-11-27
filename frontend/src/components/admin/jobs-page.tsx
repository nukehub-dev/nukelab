// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMemo, useState } from 'react'
import { Activity, AlertTriangle, Clock, Filter, ShieldCheck, Terminal } from 'lucide-react'
import { ResourcePageLayout } from '../layout/resource-page-layout'
import { Button } from '../ui/button'
import { Select, SelectItem } from '../ui/select'
import { AdminJobsTable } from './jobs-table'
import { useAdminJobs } from '../../hooks/use-admin-jobs'
import { useDataTable } from '../../hooks/use-data-table'
import { usePageGuard } from '../../hooks/use-page-guard'
import {
  ADMIN_JOB_AGE_OPTIONS,
  ADMIN_JOB_READ_PERMISSIONS,
  adminJobsLoadErrorInfo,
  emptyAdminJobSummary,
  sanitizeAdminJobSummary,
  type AdminJobAgeFilter,
} from '../../lib/admin-jobs'
import { useThemeStore } from '../../stores/theme-store'
import type { AdminJobFilters, AdminJobListState } from '../../types/admin-jobs'

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

  const clearFilters = () => {
    setStateFilter('all')
    setAgeFilter('all')
    setPage(1)
  }

  return (
    <div data-testid="admin-jobs-page">
      <ResourcePageLayout
        title="Batch Jobs"
        subtitle="Read-only cross-owner job state, protection, and cleanup evidence"
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
            <p className="text-sm font-medium">Read-only operator visibility</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Command arguments, logs, and environment values stay with the job owner. Uncertain
              jobs require the operator recovery procedure; there is no manual release or reconcile
              action, and reservations or volume guards stay in place until runtime proof exists.
            </p>
          </div>
        </div>

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
          onClearFilters={clearFilters}
          onPageChange={setPage}
          onLimitChange={setLimit}
          onRetry={() => void refetch()}
          density={density}
        />
      </ResourcePageLayout>
    </div>
  )
}

export function AdminJobsPage() {
  const allowed = usePageGuard({
    permissions: [...ADMIN_JOB_READ_PERMISSIONS],
    requireAll: true,
    redirectTo: '/admin',
  })

  if (!allowed) return null

  return <AdminJobsPageContent />
}
