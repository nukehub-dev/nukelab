// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMemo, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  CalendarDays,
  Clock,
  Filter,
  ListOrdered,
  ShieldCheck,
  X,
} from 'lucide-react'
import { ResourcePageLayout } from '../layout/resource-page-layout'
import { Button } from '../ui/button'
import { Calendar } from '../ui/calendar'
import { Combobox } from '../ui/combobox'
import { Input } from '../ui/input'
import { Select, SelectItem } from '../ui/select'
import { AdminQueueTable } from './queue-table'
import { useAdminQueue } from '../../hooks/use-admin-queue'
import { useDataTable } from '../../hooks/use-data-table'
import { usePageGuard } from '../../hooks/use-page-guard'
import { useUsers } from '../../hooks/use-users'
import {
  ADMIN_QUEUE_ANY_OWNER_LABEL,
  ADMIN_QUEUE_READ_PERMISSIONS,
  ADMIN_QUEUE_STATUSES,
  adminQueueLoadErrorInfo,
  adminQueueOwnerPickerAllowed,
  queueOwnerFilterValue,
  queueOwnerOptions,
  queueStatusLabel,
  sanitizeQueueSummary,
} from '../../lib/admin-queue'
import { cn, formatDateOnly, parseLocalDate } from '../../lib/utils'
import { useAuthStore } from '../../stores/auth-store'
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

/**
 * Mounted only when the actor can read the user directory, so queue filters
 * never issue a user query for roles without `users:read`.
 */
function QueueOwnerPicker({
  value,
  onChange,
}: {
  value: string
  onChange: (value: string) => void
}) {
  const [search, setSearch] = useState('')
  const { data, isLoading, isError } = useUsers(search ? { limit: 50, search } : { limit: 50 })
  const options = useMemo(() => queueOwnerOptions(data?.data ?? []), [data])

  return (
    <div className="space-y-1" data-testid="queue-owner-picker">
      <Combobox
        value={value}
        onChange={(next) => {
          setSearch('')
          onChange(next)
        }}
        options={options}
        placeholder={ADMIN_QUEUE_ANY_OWNER_LABEL}
        searchPlaceholder="Search owners..."
        disabled={isLoading}
        onSearchChange={setSearch}
      />
      {isLoading && <p className="text-[11px] text-muted-foreground">Loading owners…</p>}
      {isError && (
        <p className="text-[11px] text-amber-400">
          Owner names are unavailable. Refresh to try loading the user directory again.
        </p>
      )}
    </div>
  )
}

export function AdminQueuePageContent() {
  const density = useThemeStore((state) => state.density)
  const canPickOwner = useAuthStore((state) => adminQueueOwnerPickerAllowed(state.hasPermission))
  const { state: tableState, setPage, setLimit } = useDataTable({ defaultLimit: 20 })
  const [selectedStatuses, setSelectedStatuses] = useState<AdminQueueStatus[]>([])
  const [recoveryFilter, setRecoveryFilter] = useState<AdminQueueRecoveryFilter>('all')
  const [ageFilter, setAgeFilter] = useState<AgeFilter>('all')
  const [olderThanDate, setOlderThanDate] = useState('')
  const [dateOpen, setDateOpen] = useState(false)
  const dateTriggerRef = useRef<HTMLButtonElement>(null)
  const [ownerFilter, setOwnerFilter] = useState('')

  const ownerId = ownerFilter.trim()
  const ownerFilterId = queueOwnerFilterValue(ownerFilter)
  const ownerIdValid = ownerId === '' || ownerFilterId !== null
  const hasFilters =
    selectedStatuses.length > 0 ||
    recoveryFilter !== 'all' ||
    ageFilter !== 'all' ||
    olderThanDate !== '' ||
    ownerFilterId !== null
  const hasFilterInput = hasFilters || ownerId !== ''

  const filters = useMemo<AdminQueueFilters>(
    () => ({
      statuses: selectedStatuses,
      owner_id: ownerFilterId,
      age_days: ageFilter === 'all' ? null : Number(ageFilter),
      older_than: olderThanTimestamp(olderThanDate),
      recovery_required: recoveryFilter === 'all' ? null : recoveryFilter === 'required',
      limit: tableState.limit,
      offset: (tableState.page - 1) * tableState.limit,
    }),
    [
      selectedStatuses,
      ownerFilterId,
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
  const summary = sanitizeQueueSummary(data?.summary)
  const pageCount = Math.max(1, Math.ceil(total / tableState.limit))

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
          value: summary.total,
          subtitle: 'All statuses, all pages',
          icon: Activity,
          iconColor: 'text-blue-400',
          bgColor: 'bg-blue-500/10',
        },
        {
          title: 'Starting',
          value: summary.starting,
          subtitle: 'All pages',
          icon: Clock,
          iconColor: summary.starting > 0 ? 'text-amber-400' : 'text-emerald-400',
          bgColor: summary.starting > 0 ? 'bg-amber-500/10' : 'bg-emerald-500/10',
        },
        {
          title: 'Recovery Required',
          value: summary.recovery_required,
          subtitle: 'All pages',
          icon: AlertTriangle,
          iconColor: summary.recovery_required > 0 ? 'text-amber-400' : 'text-emerald-400',
          bgColor: summary.recovery_required > 0 ? 'bg-amber-500/10' : 'bg-emerald-500/10',
        },
        {
          title: 'Pending',
          value: summary.pending,
          subtitle: 'All pages',
          icon: Clock,
          iconColor: summary.pending > 0 ? 'text-blue-400' : 'text-emerald-400',
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
            <div className="flex items-center gap-1.5">
              <div className="relative min-w-0 flex-1">
                <button
                  ref={dateTriggerRef}
                  type="button"
                  data-testid="queue-older-than-filter"
                  aria-label="Older than UTC date"
                  aria-haspopup="dialog"
                  aria-expanded={dateOpen}
                  onClick={() => setDateOpen((open) => !open)}
                  className={cn(
                    'flex h-9 w-full items-center gap-2 rounded-lg border border-input bg-input/80 px-3 text-left text-sm shadow-sm backdrop-blur-sm transition-colors',
                    'hover:bg-accent focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
                    dateOpen && 'border-primary ring-2 ring-primary/30'
                  )}
                >
                  <CalendarDays className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className={cn('truncate', !olderThanDate && 'text-muted-foreground')}>
                    {olderThanDate ? formatDateOnly(parseLocalDate(olderThanDate)) : 'Any date'}
                  </span>
                </button>
                <Calendar
                  value={olderThanDate}
                  onSelect={(date) => {
                    setOlderThanDate(date)
                    setAgeFilter('all')
                    setPage(1)
                    setDateOpen(false)
                  }}
                  maxDate={new Date().toISOString().slice(0, 10)}
                  open={dateOpen}
                  onClose={() => setDateOpen(false)}
                  anchorRef={dateTriggerRef}
                />
              </div>
              {olderThanDate && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-label="Clear older-than date"
                  className="h-9 w-9 shrink-0 p-0"
                  onClick={() => {
                    setOlderThanDate('')
                    setPage(1)
                  }}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          </div>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">
              {canPickOwner ? 'Owner' : 'Owner ID'}
            </span>
            {canPickOwner ? (
              <QueueOwnerPicker
                value={ownerFilter}
                onChange={(value) => {
                  setOwnerFilter(value)
                  setPage(1)
                }}
              />
            ) : (
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
            )}
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
