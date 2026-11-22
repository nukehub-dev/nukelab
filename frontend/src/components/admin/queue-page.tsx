// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMemo, useState } from 'react'
import { Activity, AlertTriangle, Clock, Filter, ListOrdered, ShieldCheck } from 'lucide-react'
import { ResourcePageLayout } from '../layout/resource-page-layout'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Select, SelectItem } from '../ui/select'
import { AdminQueueTable } from './queue-table'
import { useAdminQueue } from '../../hooks/use-admin-queue'
import { useDataTable } from '../../hooks/use-data-table'
import { usePageGuard } from '../../hooks/use-page-guard'
import {
  ADMIN_QUEUE_READ_PERMISSIONS,
  ADMIN_QUEUE_STATUSES,
  adminQueueLoadErrorInfo,
  isQueueRecoveryRequired,
  isQueueReference,
  queueStatusLabel,
} from '../../lib/admin-queue'
import { cn } from '../../lib/utils'
import { useThemeStore } from '../../stores/theme-store'
import type {
  AdminQueueFilters,
  AdminQueueRecoveryFilter,
  AdminQueueStatus,
} from '../../types/admin-queue'

const AGE_OPTIONS = [
  { value: 'all', label: 'Any age' },
  { value: '1', label: 'At least 1 day old' },
  { value: '3', label: 'At least 3 days old' },
  { value: '7', label: 'At least 7 days old' },
  { value: '30', label: 'At least 30 days old' },
] as const

type AgeFilter = (typeof AGE_OPTIONS)[number]['value']

function olderThanTimestamp(value: string): string | null {
  if (!value) return null
  const parsed = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString() : null
}

export function AdminQueuePageContent() {
  const density = useThemeStore((state) => state.density)
  const { state: tableState, setPage, setLimit } = useDataTable({ defaultLimit: 20 })
  const [selectedStatuses, setSelectedStatuses] = useState<AdminQueueStatus[]>([])
  const [recoveryFilter, setRecoveryFilter] = useState<AdminQueueRecoveryFilter>('all')
  const [ageFilter, setAgeFilter] = useState<AgeFilter>('all')
  const [olderThanDate, setOlderThanDate] = useState('')
  const [ownerFilter, setOwnerFilter] = useState('')

  const ownerId = ownerFilter.trim()
  const ownerIdValid = ownerId === '' || isQueueReference(ownerId)
  const hasFilters =
    selectedStatuses.length > 0 ||
    recoveryFilter !== 'all' ||
    ageFilter !== 'all' ||
    olderThanDate !== '' ||
    (ownerId !== '' && ownerIdValid)
  const hasFilterInput = hasFilters || ownerId !== ''

  const filters = useMemo<AdminQueueFilters>(
    () => ({
      statuses: selectedStatuses,
      owner_id: ownerIdValid && ownerId ? ownerId : null,
      age_days: ageFilter === 'all' ? null : Number(ageFilter),
      older_than: olderThanTimestamp(olderThanDate),
      recovery_required: recoveryFilter === 'all' ? null : recoveryFilter === 'required',
      limit: tableState.limit,
      offset: (tableState.page - 1) * tableState.limit,
    }),
    [
      selectedStatuses,
      ownerId,
      ownerIdValid,
      ageFilter,
      olderThanDate,
      recoveryFilter,
      tableState.limit,
      tableState.page,
    ]
  )

  const { data, isLoading, isError, error, refetch, isFetching } = useAdminQueue(filters)
  const entries = data?.items ?? []
  const total = data?.pagination.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / tableState.limit))
  const recoveryCount = entries.filter((entry) => isQueueRecoveryRequired(entry.reason_code)).length
  const startingCount = entries.filter((entry) => entry.status === 'starting').length
  const pendingCount = entries.filter((entry) => entry.status === 'pending').length

  const clearFilters = () => {
    setSelectedStatuses([])
    setRecoveryFilter('all')
    setAgeFilter('all')
    setOlderThanDate('')
    setOwnerFilter('')
    setPage(1)
  }

  const toggleStatus = (status: AdminQueueStatus) => {
    setSelectedStatuses((current) =>
      current.includes(status) ? current.filter((item) => item !== status) : [...current, status]
    )
    setPage(1)
  }

  return (
    <ResourcePageLayout
      title="Server Queue"
      subtitle="Read-only waiting, starting, and completed requests"
      icon={ListOrdered}
      backTo="/admin"
      stats={[
        {
          title: 'Requests',
          value: total,
          subtitle: 'All matching records',
          icon: Activity,
          iconColor: 'text-blue-400',
          bgColor: 'bg-blue-500/10',
        },
        {
          title: 'Starting',
          value: startingCount,
          subtitle: 'On this page',
          icon: Clock,
          iconColor: startingCount > 0 ? 'text-amber-400' : 'text-emerald-400',
          bgColor: startingCount > 0 ? 'bg-amber-500/10' : 'bg-emerald-500/10',
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
          title: 'Pending',
          value: pendingCount,
          subtitle: 'On this page',
          icon: Clock,
          iconColor: pendingCount > 0 ? 'text-blue-400' : 'text-emerald-400',
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
          <p className="text-sm font-medium">Read-only queue visibility</p>
          <p className="mt-1 text-xs text-muted-foreground">
            This view cannot cancel or retry requests. Owner cancellation is available only while a
            request is pending; starting and recovery-required requests are resolved through
            operation reconciliation.
          </p>
        </div>
      </div>

      <div className="bubble space-y-3 p-4">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          <Filter className="h-3.5 w-3.5" />
          Filters
        </div>

        <div className="space-y-1">
          <span className="text-xs text-muted-foreground">Status</span>
          <div role="group" aria-label="Queue status filters" className="flex flex-wrap gap-1.5">
            {ADMIN_QUEUE_STATUSES.map((status) => {
              const selected = selectedStatuses.includes(status)
              return (
                <button
                  key={status}
                  type="button"
                  aria-pressed={selected}
                  data-testid={`queue-status-filter-${status}`}
                  onClick={() => toggleStatus(status)}
                  className={cn(
                    'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                    selected
                      ? 'border-primary/40 bg-primary/10 text-primary'
                      : 'border-border/50 bg-surface/50 text-muted-foreground hover:text-foreground'
                  )}
                >
                  {queueStatusLabel(status)}
                </button>
              )
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Recovery</span>
            <Select
              value={recoveryFilter}
              onChange={(value) => {
                setRecoveryFilter(value as AdminQueueRecoveryFilter)
                setPage(1)
              }}
              data-testid="queue-recovery-filter"
            >
              <SelectItem value="all">All requests</SelectItem>
              <SelectItem value="required">Recovery required</SelectItem>
              <SelectItem value="not_required">No recovery required</SelectItem>
            </Select>
          </div>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Age</span>
            <Select
              value={ageFilter}
              onChange={(value) => {
                setAgeFilter(value as AgeFilter)
                setOlderThanDate('')
                setPage(1)
              }}
              data-testid="queue-age-filter"
            >
              {AGE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </Select>
          </div>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Older than (UTC date)</span>
            <Input
              type="date"
              value={olderThanDate}
              data-testid="queue-older-than-filter"
              aria-label="Older than UTC date"
              onChange={(event) => {
                setOlderThanDate(event.target.value)
                setAgeFilter('all')
                setPage(1)
              }}
            />
          </div>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Owner ID</span>
            <Input
              type="text"
              value={ownerFilter}
              placeholder="Owner UUID"
              maxLength={36}
              data-testid="queue-owner-filter"
              aria-label="Owner ID"
              onChange={(event) => {
                setOwnerFilter(event.target.value)
                setPage(1)
              }}
            />
            {!ownerIdValid && (
              <p className="text-[11px] text-amber-400">
                Enter a complete owner UUID, or leave the field empty.
              </p>
            )}
          </div>
        </div>

        <div className="flex justify-end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={clearFilters}
            disabled={!hasFilterInput}
          >
            Clear filters
          </Button>
        </div>
      </div>

      <AdminQueueTable
        entries={entries}
        totalCount={total}
        page={tableState.page}
        pageCount={pageCount}
        limit={tableState.limit}
        isLoading={isLoading}
        isError={isError}
        errorMessage={isError ? adminQueueLoadErrorInfo(error).message : undefined}
        hasFilters={hasFilters}
        onClearFilters={clearFilters}
        onPageChange={setPage}
        onLimitChange={setLimit}
        onRetry={() => void refetch()}
        density={density}
      />
    </ResourcePageLayout>
  )
}

export function AdminQueuePage() {
  const allowed = usePageGuard({
    permissions: [...ADMIN_QUEUE_READ_PERMISSIONS],
    requireAll: true,
    redirectTo: '/admin',
  })

  if (!allowed) return null

  return <AdminQueuePageContent />
}
