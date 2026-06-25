import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState, useEffect, useRef, createElement } from 'react'
import {
  FileText,
  Shield,
  AlertTriangle,
  Activity,
  Eye,
  Clock,
  Server,
  User,
  Settings,
  CreditCard,
  Box,
  Globe,
  Terminal,
  Hash,
  Copy,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Info,
  Mail,
} from 'lucide-react'
import { ResourcePageLayout } from '../components/layout/resource-page-layout'
import { DataTable } from '../components/data/data-table'
import { useThemeStore } from '../stores/theme-store'
import { useAuthStore, PERMISSIONS } from '../stores/auth-store'
import { useDataTable } from '../hooks/use-data-table'
import { useAuditLogs } from '../hooks/use-audit-logs'
import { AuditLogDiff } from '../components/audit/audit-log-diff'
import { formatDate, cn } from '../lib/utils'
import { useToastStore } from '../stores/toast-store'
import { Dialog, DialogContent, DialogClose } from '../components/ui/dialog'
import { Tooltip } from '../components/ui/tooltip'

import type { ColumnDef, ColumnFiltersState, SortingState } from '@tanstack/react-table'
import type { ActivityLog } from '../hooks/use-audit-logs'

export const Route = createFileRoute('/admin/audit-logs')({
  component: AuditLogsPage,
})

function getActionIcon(action: string) {
  if (action.includes('server') || action.includes('spawn')) return Server
  if (action.includes('user')) return User
  if (action.includes('setting') || action.includes('config')) return Settings
  if (action.includes('credit') || action.includes('nuke')) return CreditCard
  if (action.includes('environment') || action.includes('plan')) return Box
  return Activity
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

function getActionColor(action: string): string {
  if (action.includes('delete') || action.includes('disable')) return 'text-red-400 bg-red-400/10'
  if (action.includes('create') || action.includes('enable') || action.includes('spawn'))
    return 'text-emerald-400 bg-emerald-400/10'
  if (action.includes('update') || action.includes('edit')) return 'text-amber-400 bg-amber-400/10'
  if (action.includes('login') || action.includes('auth')) return 'text-blue-400 bg-blue-400/10'
  return 'text-muted-foreground bg-muted/30'
}

function formatActionName(action: string): string {
  return action.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())
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
        {createElement(getDetailIcon(label), { className: 'w-3.5 h-3.5 text-muted-foreground/70' })}
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

function CopyableId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(id)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      onClick={handleCopy}
      className="inline-flex items-center gap-1 text-xs font-mono text-muted-foreground hover:text-primary transition-colors"
    >
      {id.slice(0, 8)}...
      {copied ? (
        <CheckCircle2 className="w-3 h-3 text-emerald-400" />
      ) : (
        <Copy className="w-3 h-3" />
      )}
    </button>
  )
}

function AuditLogsPage() {
  const navigate = useNavigate()
  const canViewAudit = useAuthStore((state) => state.hasPermission(PERMISSIONS.AUDIT_READ))
  const density = useThemeStore((state) => state.density)

  useEffect(() => {
    if (!canViewAudit) {
      navigate({ to: '/' })
    }
  }, [canViewAudit, navigate])

  const {
    state: tableState,
    setPage,
    setLimit,
    setSearch,
    setFilter,
  } = useDataTable({ defaultLimit: 25, defaultSortBy: 'created_at' })

  const [sorting, setSorting] = useState<SortingState>([{ id: 'created_at', desc: true }])
  const [rowSelection, setRowSelection] = useState<Record<string, boolean>>({})
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = useState<Record<string, boolean>>({})
  const [selectedLog, setSelectedLog] = useState<ActivityLog | null>(null)
  const [exportLoading, setExportLoading] = useState(false)

  // Sync React Table column filters with API filter state
  const prevColumnFiltersRef = useRef<ColumnFiltersState>([])
  useEffect(() => {
    const currentIds = new Set(columnFilters.map((f) => f.id))

    // Add/update filters
    columnFilters.forEach((filter) => {
      if (filter.value !== undefined && filter.value !== null) {
        setFilter(filter.id, String(filter.value))
      }
    })

    // Remove filters that no longer exist
    prevColumnFiltersRef.current.forEach((filter) => {
      if (!currentIds.has(filter.id)) {
        setFilter(filter.id, null)
      }
    })

    prevColumnFiltersRef.current = columnFilters
  }, [columnFilters, setFilter])

  const { data, isLoading, isError, error } = useAuditLogs({
    action: tableState.filters.action as string,
    target_type: tableState.filters.target_type as string,
    page: tableState.page,
    limit: tableState.limit,
  })

  const logs = data?.logs || []
  const pagination = data?.pagination

  // Stats
  const totalEvents = pagination?.total || 0
  const securityEvents = logs.filter(
    (l) =>
      l.action.includes('login') || l.action.includes('auth') || l.action.includes('permission')
  ).length
  const warningEvents = logs.filter(
    (l) => l.action.includes('delete') || l.action.includes('disable') || l.action.includes('stop')
  ).length
  const todayEvents = logs.filter((l) => {
    const date = new Date(l.created_at)
    const now = new Date()
    return date.toDateString() === now.toDateString()
  }).length

  const handleExport = async () => {
    try {
      setExportLoading(true)
      const params = new URLSearchParams()
      params.set('format', 'csv')
      params.set('limit', '10000')
      if (tableState.filters.action) params.set('action', String(tableState.filters.action))
      if (tableState.filters.target_type)
        params.set('target_type', String(tableState.filters.target_type))

      const response = await fetch(`/api/admin/activity/export?${params.toString()}`, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem('nukelab-token') || ''}`,
        },
      })

      if (!response.ok) throw new Error('Export failed')

      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `audit_logs_${new Date().toISOString().split('T')[0]}.csv`
      a.click()
      window.URL.revokeObjectURL(url)
    } catch {
      useToastStore.getState().addToast({
        type: 'error',
        title: 'Export failed',
        message: 'Failed to export audit logs',
        duration: 8000,
      })
    } finally {
      setExportLoading(false)
    }
  }

  const columns: ColumnDef<ActivityLog>[] = [
    {
      accessorKey: 'action',
      header: 'Action',
      cell: ({ row }) => {
        const action = row.getValue('action') as string
        const Icon = getActionIcon(action)
        return (
          <div className="flex items-center gap-2">
            <div className={`p-1.5 rounded-md ${getActionColor(action)}`}>
              <Icon className="w-3.5 h-3.5" />
            </div>
            <span className="font-medium text-sm">{action}</span>
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
      accessorKey: 'actor_id',
      header: 'Actor',
      cell: ({ row }) => {
        const actorId = row.getValue('actor_id') as string | null
        const details = row.original.details as Record<string, unknown>
        const username = details?.actor_username as string | undefined
        return (
          <div className="text-sm">
            {actorId ? (
              <div className="flex items-center gap-1.5">
                <span className="font-medium">{username || 'User'}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  {actorId.slice(0, 6)}...
                </span>
              </div>
            ) : (
              <span className="text-muted-foreground">System</span>
            )}
          </div>
        )
      },
    },
    {
      accessorKey: 'ip_address',
      header: 'IP Address',
      cell: ({ row }) => (
        <span className="text-sm font-mono text-muted-foreground">
          {(row.getValue('ip_address') as string) || '-'}
        </span>
      ),
    },
    {
      accessorKey: 'created_at',
      header: 'Time',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">
            {formatDate(row.getValue('created_at') as string)}
          </span>
        </div>
      ),
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <button
          onClick={() => setSelectedLog(row.original)}
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
        { label: 'Login', value: 'login' },
        { label: 'Spawn', value: 'spawn' },
        { label: 'Stop', value: 'stop' },
        { label: 'Start', value: 'start' },
      ],
    },
    {
      key: 'target_type',
      label: 'Target Type',
      options: [
        { label: 'Users', value: 'users' },
        { label: 'Servers', value: 'servers' },
        { label: 'Environments', value: 'environments' },
        { label: 'Plans', value: 'plans' },
        { label: 'Settings', value: 'settings' },
      ],
    },
  ]

  const mobileCardRenderer = (log: ActivityLog) => (
    <div className="p-3 space-y-1.5">
      {/* Top row: action + view */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`p-1 rounded ${getActionColor(log.action)} shrink-0`}>
            {(() => {
              const Icon = getActionIcon(log.action)
              return <Icon className="w-3 h-3" />
            })()}
          </div>
          <span className="font-medium text-sm truncate">{log.action}</span>
        </div>
        <button
          onClick={() => setSelectedLog(log)}
          className="p-1 rounded-md hover:bg-primary/10 text-primary transition-colors inline-flex shrink-0"
        >
          <Eye className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Bottom row: metadata inline */}
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground flex-wrap">
        <span className="text-foreground font-medium">{log.target_type}</span>
        <span className="text-border">·</span>
        <span className="truncate">
          {String(log.details?.actor_username || '') || (log.actor_id ? 'User' : 'System')}
        </span>
        <span className="text-border">·</span>
        <span className="tabular-nums">{formatDate(log.created_at)}</span>
      </div>
    </div>
  )

  if (!canViewAudit) return null

  return (
    <>
      <ResourcePageLayout
        title="Audit Logs"
        subtitle="Platform activity monitoring"
        icon={FileText}
        backTo="/admin"
        stats={[
          {
            title: 'Total Events',
            value: totalEvents,
            icon: FileText,
            iconColor: 'text-blue-400',
            bgColor: 'bg-blue-500/10',
          },
          {
            title: 'Security',
            value: securityEvents,
            icon: Shield,
            iconColor: 'text-emerald-400',
            bgColor: 'bg-emerald-500/10',
          },
          {
            title: 'Warnings',
            value: warningEvents,
            icon: AlertTriangle,
            iconColor: 'text-amber-400',
            bgColor: 'bg-amber-500/10',
          },
          {
            title: 'Today',
            value: todayEvents,
            icon: Activity,
            iconColor: 'text-violet-400',
            bgColor: 'bg-violet-500/10',
          },
        ]}
        actions={[
          {
            action: 'export',
            onClick: handleExport,
            loading: exportLoading,
          },
        ]}
      >
        <DataTable
          columns={columns}
          data={logs}
          totalCount={pagination?.total || 0}
          pageCount={pagination?.total_pages || 1}
          page={tableState.page}
          limit={tableState.limit}
          sorting={sorting}
          rowSelection={rowSelection}
          columnFilters={columnFilters}
          columnVisibility={columnVisibility}
          globalFilter={tableState.search}
          isLoading={isLoading}
          isError={isError}
          errorMessage={error?.message}
          onPageChange={setPage}
          onLimitChange={setLimit}
          onSortingChange={(newSorting) => {
            setSorting(newSorting)
          }}
          onRowSelectionChange={setRowSelection}
          onColumnFiltersChange={setColumnFilters}
          onColumnVisibilityChange={setColumnVisibility}
          onGlobalFilterChange={setSearch}
          getRowId={(row) => row.id}
          filters={filters}
          searchable
          searchPlaceholder="Search audit logs..."
          density={density}
          mobileCardRenderer={mobileCardRenderer}
          enableRowSelection={false}
          defaultMobileView={false}
        />
      </ResourcePageLayout>

      {/* Detail Drawer */}
      <Dialog open={!!selectedLog} onOpenChange={(open) => !open && setSelectedLog(null)}>
        <DialogContent className="sm:max-w-lg pt-6">
          <DialogClose onClick={() => setSelectedLog(null)} />

          {selectedLog && (
            <div className="space-y-5">
              {/* Header */}
              <div className="flex items-start gap-3">
                <div className={`p-2.5 rounded-xl ${getActionColor(selectedLog.action)} shrink-0`}>
                  {(() => {
                    const Icon = getActionIcon(selectedLog.action)
                    return <Icon className="w-5 h-5" />
                  })()}
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="font-semibold text-base leading-tight">
                    {formatActionName(selectedLog.action)}
                  </h3>
                  <div className="flex items-center gap-2 mt-1.5 text-xs text-muted-foreground">
                    <Clock className="w-3 h-3" />
                    <span>{formatDate(selectedLog.created_at)}</span>
                    {selectedLog.request_id && (
                      <>
                        <span className="text-border">|</span>
                        <span className="font-mono">{selectedLog.request_id.slice(0, 8)}</span>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* Info Grid */}
              <div className="grid grid-cols-2 gap-2.5">
                <InfoCard
                  icon={Hash}
                  label="Target"
                  value={selectedLog.target_type}
                  subValue={
                    selectedLog.target_id ? <CopyableId id={selectedLog.target_id} /> : undefined
                  }
                />
                <InfoCard
                  icon={User}
                  label="Actor"
                  value={
                    String(selectedLog.details.actor_username || '') ||
                    (selectedLog.actor_id ? 'User' : 'System')
                  }
                  subValue={
                    selectedLog.actor_id ? <CopyableId id={selectedLog.actor_id} /> : undefined
                  }
                />
                {selectedLog.ip_address && (
                  <InfoCard icon={Globe} label="IP Address" value={selectedLog.ip_address} />
                )}
                {selectedLog.user_agent && (
                  <InfoCard
                    icon={Terminal}
                    label="User Agent"
                    value={
                      <Tooltip content={selectedLog.user_agent} position="bottom">
                        <span className="text-xs truncate block cursor-help">
                          {selectedLog.user_agent.split(' ')[0]}
                        </span>
                      </Tooltip>
                    }
                  />
                )}
              </div>

              {/* Request Block */}
              {!!selectedLog.details.method && (
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
                          (selectedLog.details.method as string) === 'GET' &&
                            'bg-blue-400/10 text-blue-400',
                          (selectedLog.details.method as string) === 'POST' &&
                            'bg-emerald-400/10 text-emerald-400',
                          (selectedLog.details.method as string) === 'PUT' &&
                            'bg-amber-400/10 text-amber-400',
                          (selectedLog.details.method as string) === 'DELETE' &&
                            'bg-red-400/10 text-red-400',
                          (selectedLog.details.method as string) === 'PATCH' &&
                            'bg-violet-400/10 text-violet-400'
                        )}
                      >
                        {String(selectedLog.details.method)}
                      </span>
                      <span className="text-xs font-mono text-foreground truncate">
                        {String(selectedLog.details.path)}
                      </span>
                      {!!selectedLog.details.status_code &&
                        (() => {
                          const {
                            icon: StatusIcon,
                            color,
                            label,
                          } = getStatusBadge(Number(selectedLog.details.status_code))
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
                      const extraDetails = Object.entries(selectedLog.details).filter(
                        ([k]) => !['method', 'path', 'status_code'].includes(k)
                      )
                      return extraDetails.length > 0 ? (
                        <div className="px-3.5 py-2.5">
                          {extraDetails.map(([key, value]) => (
                            <DetailRow
                              key={key}
                              label={key}
                              value={String(value)}
                              mono={typeof value === 'string' && value.length < 50}
                            />
                          ))}
                        </div>
                      ) : null
                    })()}
                  </div>
                </div>
              )}

              {/* Before / After Diff */}
              {(Object.keys(selectedLog.before_state).length > 0 ||
                Object.keys(selectedLog.after_state).length > 0) && (
                <div className="space-y-2">
                  <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    <Activity className="w-3.5 h-3.5" />
                    State Changes
                  </div>
                  <AuditLogDiff
                    beforeState={selectedLog.before_state}
                    afterState={selectedLog.after_state}
                  />
                </div>
              )}

              {/* Raw Details (fallback) */}
              {Object.keys(selectedLog.details).length > 0 && !selectedLog.details.method && (
                <div className="space-y-2">
                  <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    <Info className="w-3.5 h-3.5" />
                    Details
                  </div>
                  <div className="rounded-xl border border-border/50 bg-muted/30 overflow-hidden px-3.5">
                    {Object.entries(selectedLog.details).map(([key, value]) => (
                      <DetailRow
                        key={key}
                        label={key}
                        value={typeof value === 'object' ? JSON.stringify(value) : String(value)}
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
