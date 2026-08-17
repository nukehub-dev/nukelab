// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute } from '@tanstack/react-router'
import { useState, useEffect, useRef } from 'react'
import type { ColumnDef, SortingState, ColumnFiltersState } from '@tanstack/react-table'
import {
  Activity,
  Server,
  User,
  Settings,
  CreditCard,
  HardDrive,
  Box,
  Shield,
  Clock,
  Hash,
  Eye,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Info,
  Terminal,
  Globe,
  Mail,
} from 'lucide-react'
import { ResourcePageLayout } from '../components/layout/resource-page-layout'
import { DataTable } from '../components/data/data-table'
import { useDataTable } from '../hooks/use-data-table'
import { useActivity, type ActivityItem } from '../hooks/use-activity'
import { formatDate, cn } from '../lib/utils'
import { useThemeStore } from '../stores/theme-store'
import { Dialog, DialogContent, DialogClose } from '../components/ui/dialog'

const actionIcons: Record<string, typeof Hash> = {
  server: Server,
  user: User,
  setting: Settings,
  config: Settings,
  credit: CreditCard,
  nuke: CreditCard,
  volume: HardDrive,
  environment: Box,
  plan: Box,
  admin: Shield,
  permission: Shield,
  login: User,
  logout: User,
}

const actionColors: Record<string, string> = {
  create: 'text-emerald-400 bg-emerald-400/10',
  spawn: 'text-emerald-400 bg-emerald-400/10',
  start: 'text-emerald-400 bg-emerald-400/10',
  enable: 'text-emerald-400 bg-emerald-400/10',
  update: 'text-amber-400 bg-amber-400/10',
  edit: 'text-amber-400 bg-amber-400/10',
  delete: 'text-red-400 bg-red-400/10',
  remove: 'text-red-400 bg-red-400/10',
  stop: 'text-red-400 bg-red-400/10',
  disable: 'text-red-400 bg-red-400/10',
  login: 'text-blue-400 bg-blue-400/10',
  auth: 'text-blue-400 bg-blue-400/10',
}

function getActionIcon(action: string) {
  const key = Object.keys(actionIcons).find((k) => action.toLowerCase().includes(k))
  return key ? actionIcons[key] : Activity
}

function getActionColor(action: string) {
  const key = Object.keys(actionColors).find((k) => action.toLowerCase().includes(k))
  return key ? actionColors[key] : 'text-muted-foreground bg-muted/30'
}

function formatActionName(action: string): string {
  return action.replace(/[_.]/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
}

function formatTargetType(targetType: string): string {
  return targetType.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
}

function getDetailIcon(key: string): typeof Hash {
  if (key.includes('username')) return User
  if (key.includes('email')) return Mail
  if (key.includes('role')) return Shield
  if (key.includes('actor')) return User
  if (key.includes('ip')) return Globe
  if (key.includes('path')) return Terminal
  if (key.includes('method')) return Terminal
  if (key.includes('status')) return CheckCircle2
  return Hash
}

function getStatusBadge(statusCode: number | undefined): {
  icon: typeof CheckCircle2
  color: string
  label: string
} {
  if (!statusCode) return { icon: Info, color: 'text-muted-foreground', label: 'Unknown' }
  if (statusCode >= 200 && statusCode < 300)
    return { icon: CheckCircle2, color: 'text-emerald-400', label: String(statusCode) }
  if (statusCode >= 400 && statusCode < 500)
    return { icon: AlertCircle, color: 'text-amber-400', label: String(statusCode) }
  if (statusCode >= 500) return { icon: XCircle, color: 'text-red-400', label: String(statusCode) }
  return { icon: Info, color: 'text-blue-400', label: String(statusCode) }
}

function formatDetailValue(_key: string, value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value).slice(0, 40)
  return String(value).slice(0, 60)
}

function DetailRow({
  label,
  value,
  mono = false,
}: {
  label: string
  value: React.ReactNode
  mono?: boolean
}) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-border/30 last:border-0">
      <span className="text-xs text-muted-foreground flex items-center gap-2">
        {typeof label === 'string' &&
          (() => {
            const Icon = getDetailIcon(label)
            return <Icon className="w-3.5 h-3.5 text-muted-foreground/70" />
          })()}
        {label}
      </span>
      <span
        className={
          mono ? 'font-mono text-xs text-foreground' : 'text-sm font-medium text-foreground'
        }
      >
        {value}
      </span>
    </div>
  )
}

function InfoCard({
  icon: Icon,
  label,
  value,
  subValue,
}: {
  icon: typeof Hash
  label: string
  value: React.ReactNode
  subValue?: React.ReactNode
}) {
  return (
    <div className="bubble p-3.5 flex items-start gap-3">
      <div className="p-1.5 rounded-md bg-primary/10 shrink-0">
        <Icon className="w-3.5 h-3.5 text-primary" />
      </div>
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">{label}</p>
        <p className="text-sm font-medium truncate">{value}</p>
        {subValue && (
          <div className="text-xs text-muted-foreground font-mono mt-0.5">{subValue}</div>
        )}
      </div>
    </div>
  )
}

export const Route = createFileRoute('/activity')({
  component: ActivityPage,
})

function ActivityPage() {
  const density = useThemeStore((state) => state.density)
  const [selectedActivity, setSelectedActivity] = useState<ActivityItem | null>(null)
  const [sorting, setSorting] = useState<SortingState>([{ id: 'timestamp', desc: true }])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])

  const {
    state: tableState,
    setPage,
    setLimit,
    setSearch,
    setFilter,
  } = useDataTable({ defaultLimit: 25, defaultSortBy: 'timestamp' })

  // Sync React Table column filters with API filter state
  const prevColumnFiltersRef = useRef<ColumnFiltersState>([])
  useEffect(() => {
    const currentIds = new Set(columnFilters.map((f) => f.id))

    columnFilters.forEach((filter) => {
      if (filter.value !== undefined && filter.value !== null) {
        setFilter(filter.id, String(filter.value))
      }
    })

    prevColumnFiltersRef.current.forEach((filter) => {
      if (!currentIds.has(filter.id)) {
        setFilter(filter.id, null)
      }
    })

    prevColumnFiltersRef.current = columnFilters
  }, [columnFilters, setFilter])

  const { data, isLoading, isError, error } = useActivity({
    page: tableState.page,
    limit: tableState.limit,
    action: tableState.filters.action as string,
    target_type: tableState.filters.target_type as string,
  })

  const activities = data?.activities || []
  const pagination = data?.pagination

  const columns: ColumnDef<ActivityItem>[] = [
    {
      accessorKey: 'action',
      header: 'Action',
      cell: ({ row }) => {
        const action = row.getValue('action') as string
        const Icon = getActionIcon(action)
        return (
          <div className="flex items-center gap-2">
            <div className={cn('p-1.5 rounded-md', getActionColor(action))}>
              <Icon className="w-3.5 h-3.5" />
            </div>
            <span className="font-medium text-sm">{formatActionName(action)}</span>
          </div>
        )
      },
    },
    {
      accessorKey: 'target_type',
      header: 'Target',
      cell: ({ row }) => {
        const targetType = row.getValue('target_type') as string
        const targetId = row.original.target_id
        return (
          <div className="text-sm">
            <span className="text-muted-foreground">{targetType}</span>
            {targetId && (
              <span className="ml-1.5 font-mono text-xs">{targetId.slice(0, 8)}...</span>
            )}
          </div>
        )
      },
    },
    {
      accessorKey: 'timestamp',
      header: 'Time',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">
            {formatDate(row.getValue('timestamp') as string)}
          </span>
        </div>
      ),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <button
          onClick={() => setSelectedActivity(row.original)}
          className="p-1.5 rounded-lg hover:bg-primary/10 text-primary transition-colors inline-flex"
        >
          <Eye className="w-4 h-4" />
        </button>
      ),
      enableSorting: false,
      size: 50,
    },
  ]

  const filters = [
    {
      key: 'action',
      label: 'Action',
      options: [
        { label: 'Create', value: 'create' },
        { label: 'Update', value: 'update' },
        { label: 'Delete', value: 'delete' },
        { label: 'Start', value: 'start' },
        { label: 'Stop', value: 'stop' },
        { label: 'Restart', value: 'restart' },
      ],
    },
    {
      key: 'target_type',
      label: 'Target',
      options: [
        { label: 'Servers', value: 'servers' },
        { label: 'Volumes', value: 'volumes' },
        { label: 'Users', value: 'users' },
      ],
    },
  ]

  const mobileCardRenderer = (item: ActivityItem) => {
    const Icon = getActionIcon(item.action)
    return (
      <div className="p-3 space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className={cn('p-1 rounded', getActionColor(item.action), 'shrink-0')}>
              <Icon className="w-3 h-3" />
            </div>
            <span className="font-medium text-sm truncate">{formatActionName(item.action)}</span>
          </div>
          <button
            onClick={() => setSelectedActivity(item)}
            className="p-1 rounded-md hover:bg-primary/10 text-primary transition-colors inline-flex shrink-0"
          >
            <Eye className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground flex-wrap">
          <span className="text-foreground font-medium">{item.target_type}</span>
          <span className="text-border">·</span>
          <span className="tabular-nums">{formatDate(item.timestamp)}</span>
        </div>
      </div>
    )
  }

  return (
    <>
      <ResourcePageLayout
        title="Activity"
        subtitle="Track your actions across the platform"
        icon={Activity}
      >
        <DataTable
          columns={columns}
          data={activities}
          totalCount={pagination?.total || 0}
          pageCount={pagination?.total_pages || 1}
          page={tableState.page}
          limit={tableState.limit}
          sorting={sorting}
          rowSelection={{}}
          columnFilters={[]}
          columnVisibility={{}}
          globalFilter={tableState.search}
          isLoading={isLoading}
          isError={isError}
          errorMessage={error?.message}
          onPageChange={setPage}
          onLimitChange={setLimit}
          onSortingChange={setSorting}
          onRowSelectionChange={() => {}}
          onColumnFiltersChange={setColumnFilters}
          onColumnVisibilityChange={() => {}}
          onGlobalFilterChange={setSearch}
          getRowId={(row) => row.id}
          filters={filters}
          searchable
          searchPlaceholder="Search activity..."
          density={density}
          mobileCardRenderer={mobileCardRenderer}
          enableRowSelection={false}
        />
      </ResourcePageLayout>

      {/* Detail Drawer */}
      <Dialog
        open={!!selectedActivity}
        onOpenChange={(open) => !open && setSelectedActivity(null)}
        size="lg"
      >
        <DialogContent className="pt-6">
          <DialogClose onClick={() => setSelectedActivity(null)} />
          {selectedActivity && (
            <div className="space-y-5">
              {/* Header */}
              <div className="flex items-start gap-3">
                <div
                  className={cn(
                    'p-2.5 rounded-xl',
                    getActionColor(selectedActivity.action),
                    'shrink-0'
                  )}
                >
                  {(() => {
                    const Icon = getActionIcon(selectedActivity.action)
                    return <Icon className="w-5 h-5" />
                  })()}
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold text-base leading-tight">
                    {formatActionName(selectedActivity.action)}
                  </h3>
                  <div className="flex flex-wrap items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                    {selectedActivity.target_type && (
                      <>
                        <span className="font-medium text-foreground capitalize">
                          {formatTargetType(selectedActivity.target_type)}
                        </span>
                        {selectedActivity.target_id && (
                          <span className="font-mono">
                            {selectedActivity.target_id.slice(0, 8)}...
                          </span>
                        )}
                        <span className="text-border">|</span>
                      </>
                    )}
                    <Clock className="w-3 h-3" />
                    <span>{formatDate(selectedActivity.timestamp)}</span>
                  </div>
                </div>
              </div>

              {/* Target */}
              {selectedActivity.target_type && (
                <InfoCard
                  icon={Hash}
                  label="Target"
                  value={<span>{formatTargetType(selectedActivity.target_type)}</span>}
                  subValue={selectedActivity.target_id || undefined}
                />
              )}

              {/* Request / Details */}
              {!!selectedActivity.details.method && (
                <div className="space-y-2">
                  <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    <Terminal className="w-3.5 h-3.5" />
                    Request
                  </div>
                  <div className="rounded-xl border border-border/50 bg-muted/30 overflow-hidden">
                    <div className="flex items-center gap-3 px-3.5 py-2.5 border-b border-border/30 bg-muted/50">
                      <span
                        className={cn(
                          'text-xs font-bold font-mono px-1.5 py-0.5 rounded',
                          (selectedActivity.details.method as string) === 'GET' &&
                            'bg-blue-400/10 text-blue-400',
                          (selectedActivity.details.method as string) === 'POST' &&
                            'bg-emerald-400/10 text-emerald-400',
                          (selectedActivity.details.method as string) === 'PUT' &&
                            'bg-amber-400/10 text-amber-400',
                          (selectedActivity.details.method as string) === 'DELETE' &&
                            'bg-red-400/10 text-red-400',
                          (selectedActivity.details.method as string) === 'PATCH' &&
                            'bg-violet-400/10 text-violet-400'
                        )}
                      >
                        {String(selectedActivity.details.method)}
                      </span>
                      <span className="text-xs font-mono text-foreground truncate">
                        {String(selectedActivity.details.path)}
                      </span>
                      {!!selectedActivity.details.status_code &&
                        (() => {
                          const {
                            icon: StatusIcon,
                            color,
                            label,
                          } = getStatusBadge(Number(selectedActivity.details.status_code))
                          return (
                            <span
                              className={`ml-auto flex items-center gap-1 text-xs font-medium ${color}`}
                            >
                              <StatusIcon className="w-3.5 h-3.5" />
                              {label}
                            </span>
                          )
                        })()}
                    </div>
                    {(() => {
                      const extraDetails = Object.entries(selectedActivity.details).filter(
                        ([k]) => !['method', 'path', 'status_code'].includes(k)
                      )
                      return extraDetails.length > 0 ? (
                        <div className="px-3.5 py-2.5">
                          {extraDetails.map(([key, value]) => (
                            <DetailRow
                              key={key}
                              label={key}
                              value={formatDetailValue(key, value)}
                              mono={typeof value === 'string' && value.length < 50}
                            />
                          ))}
                        </div>
                      ) : null
                    })()}
                  </div>
                </div>
              )}

              {/* Raw details when no HTTP block */}
              {Object.keys(selectedActivity.details).length > 0 &&
                !selectedActivity.details.method && (
                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      <Info className="w-3.5 h-3.5" />
                      Details
                    </div>
                    <div className="rounded-xl border border-border/50 bg-muted/30 overflow-hidden px-3.5">
                      {Object.entries(selectedActivity.details).map(([key, value]) => (
                        <DetailRow
                          key={key}
                          label={key}
                          value={formatDetailValue(key, value)}
                          mono
                        />
                      ))}
                    </div>
                  </div>
                )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
