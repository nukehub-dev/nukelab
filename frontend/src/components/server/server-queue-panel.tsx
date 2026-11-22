// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useServers } from '../../hooks/use-servers'
import { Link } from '@tanstack/react-router'
import { motion } from 'framer-motion'
import {
  AlertTriangle,
  Ban,
  Box,
  CalendarClock,
  CheckCircle2,
  Clock,
  Cpu,
  ExternalLink,
  HardDrive,
  History,
  Inbox,
  Info,
  Layers,
  ListOrdered,
  Loader2,
  MemoryStick,
  Play,
  RefreshCw,
  Timer,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import {
  useCancelServerQueue,
  useServerQueue,
  useServerQueueEntry,
} from '../../hooks/use-server-queue'
import { ApiError } from '../../lib/api'
import { canCancelQueuedRequest, isQueueActive } from '../../lib/server-queue'
import { cn, formatBytes, formatDate } from '../../lib/utils'
import { springs } from '../../lib/animations'
import { PERMISSIONS, useAuthStore } from '../../stores/auth-store'
import { useToastStore } from '../../stores/toast-store'
import type { Environment, Plan, Server } from '../../types/api'
import type { QueueStatus, ServerQueueEntry } from '../../types/server-queue'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { useConfirmDialog } from '../ui/confirm-dialog'
import { Skeleton } from '../feedback/skeleton'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '../ui/dialog'

interface QueuePanelProps {
  requestId?: string
  plans: Plan[]
  environments: Environment[]
  onSelect: (id?: string) => void
}

const statusConfig: Record<
  QueueStatus,
  { label: string; icon: LucideIcon; pill: string; tile: string }
> = {
  pending: {
    label: 'Waiting',
    icon: Clock,
    pill: 'border-blue-500/20 bg-blue-500/10 text-blue-400',
    tile: 'bg-blue-500/10 text-blue-400',
  },
  scheduled: {
    label: 'Scheduled',
    icon: CalendarClock,
    pill: 'border-sky-500/20 bg-sky-500/10 text-sky-400',
    tile: 'bg-sky-500/10 text-sky-400',
  },
  starting: {
    label: 'Starting',
    icon: Loader2,
    pill: 'border-amber-500/20 bg-amber-500/10 text-amber-400',
    tile: 'bg-amber-500/10 text-amber-400',
  },
  started: {
    label: 'Started',
    icon: CheckCircle2,
    pill: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400',
    tile: 'bg-emerald-500/10 text-emerald-400',
  },
  failed: {
    label: 'Failed',
    icon: AlertTriangle,
    pill: 'border-red-500/20 bg-red-500/10 text-red-400',
    tile: 'bg-red-500/10 text-red-400',
  },
  cancelled: {
    label: 'Cancelled',
    icon: Ban,
    pill: 'border-border/50 bg-muted/50 text-muted-foreground',
    tile: 'bg-muted/50 text-muted-foreground',
  },
}

type QueueFilterKey = 'active' | 'started' | 'history' | 'all'

interface QueueFilterDefinition {
  key: QueueFilterKey
  label: string
  countLabel: string
  statuses?: readonly QueueStatus[]
  emptyTitle: string
  emptyDescription: string
  icon: LucideIcon
}

const queueFilters: readonly QueueFilterDefinition[] = [
  {
    key: 'active',
    label: 'Active',
    countLabel: 'Active requests',
    statuses: ['pending', 'scheduled', 'starting'],
    emptyTitle: 'No active requests',
    emptyDescription:
      'Requests appear here when capacity is unavailable. Deploy a server to join the queue.',
    icon: Inbox,
  },
  {
    key: 'started',
    label: 'Started',
    countLabel: 'Started requests',
    statuses: ['started'],
    emptyTitle: 'No started requests',
    emptyDescription: 'Requests that launch successfully appear here.',
    icon: CheckCircle2,
  },
  {
    key: 'history',
    label: 'History',
    countLabel: 'History requests',
    statuses: ['cancelled', 'failed'],
    emptyTitle: 'No request history',
    emptyDescription: 'Cancelled or failed requests appear here.',
    icon: History,
  },
  {
    key: 'all',
    label: 'All',
    countLabel: 'All requests',
    emptyTitle: 'No waiting requests',
    emptyDescription: 'Requests appear here when capacity is unavailable.',
    icon: Clock,
  },
]

function QueueStatusPill({ status, className }: { status: QueueStatus; className?: string }) {
  const config = statusConfig[status]
  const Icon = config.icon
  return (
    <span
      role="status"
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium',
        config.pill,
        className
      )}
    >
      <Icon className={cn('h-3 w-3', status === 'starting' && 'animate-spin')} />
      {config.label}
    </span>
  )
}

function ResourceChip({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-surface/50 px-2 py-1 text-[11px] text-muted-foreground">
      <Icon className="h-3 w-3 shrink-0" />
      {children}
    </span>
  )
}

function QueueResourceChips({
  resources,
  compact = false,
}: {
  resources: ServerQueueEntry['request']['resources']
  compact?: boolean
}) {
  return (
    <div className={cn('flex flex-wrap gap-1.5', compact && 'gap-1')}>
      <ResourceChip icon={Cpu}>{resources.cpu} vCPU</ResourceChip>
      <ResourceChip icon={MemoryStick}>
        {formatBytes(resources.memory_mib * 1024 * 1024)} RAM
      </ResourceChip>
      <ResourceChip icon={HardDrive}>
        {formatBytes(resources.disk_mib * 1024 * 1024)} disk
      </ResourceChip>
      <ResourceChip icon={Zap}>{resources.gpu_count} GPU</ResourceChip>
    </div>
  )
}

function ViewServerLink({
  server,
  username,
  className,
}: {
  server: Server
  username?: string
  className?: string
}) {
  const linkUsername = server.username || username
  if (!linkUsername) return null
  return (
    <Link
      to="/user/$username/$serverName"
      params={{ username: linkUsername, serverName: server.name }}
      className={cn(
        'inline-flex h-8 items-center gap-1.5 rounded-md border border-input bg-background px-3 text-xs font-medium text-primary transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
        className
      )}
    >
      <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
      View server
    </Link>
  )
}

export function QueueRecoveryNotice({
  reasonCode,
  className,
}: {
  reasonCode: string | null | undefined
  className?: string
}) {
  if (reasonCode !== 'recovery_required') return null
  return (
    <div
      role="status"
      data-testid="queue-recovery-notice"
      className={cn(
        'flex items-start gap-2.5 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2.5',
        className
      )}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-sm font-medium text-amber-400">Operator verification required</p>
        <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
          The launch outcome could not be verified automatically. Contact support before
          resubmitting; resubmit only after support confirms this request cannot be recovered. No
          admin retry is available for this request.
        </p>
      </div>
    </div>
  )
}

export function QueueRequestCard({
  entry,
  index,
  planName,
  environmentName,
  launched,
  username,
  canManage,
  cancelPending,
  onSelect,
  onCancel,
}: {
  entry: ServerQueueEntry
  index: number
  planName: string
  environmentName: string
  launched?: Server
  username?: string
  canManage: boolean
  cancelPending: boolean
  onSelect: () => void
  onCancel: () => void
}) {
  const active = isQueueActive(entry)
  const config = statusConfig[entry.status]
  const StatusIcon = config.icon
  const showPriority = entry.position !== null && entry.position > 0

  return (
    <motion.article
      data-testid={`queue-request-${entry.id}`}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.04, 0.2), ...springs.gentle }}
    >
      <Card
        variant="bubble"
        className={cn(
          'relative overflow-hidden',
          active ? 'border-primary/25' : 'border-border/40'
        )}
      >
        {active && (
          <>
            <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-primary/60" />
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary/10 via-transparent to-transparent"
            />
          </>
        )}
        <CardContent className={cn('relative', active ? 'p-5' : 'p-4')}>
          <div className="flex items-start gap-3">
            <div
              className={cn(
                'flex shrink-0 items-center justify-center rounded-xl',
                config.tile,
                active ? 'h-10 w-10' : 'h-8 w-8',
                entry.status === 'cancelled' && 'opacity-80'
              )}
            >
              <StatusIcon
                className={cn(
                  active ? 'h-4 w-4' : 'h-3.5 w-3.5',
                  entry.status === 'starting' && 'animate-spin'
                )}
              />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3
                  className={cn(
                    'break-all font-semibold',
                    active ? 'text-base' : 'text-sm text-foreground/90'
                  )}
                >
                  {entry.request.name}
                </h3>
                <QueueStatusPill status={entry.status} />
              </div>
              <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
                <Layers className="h-3 w-3 shrink-0" />
                <span>{planName}</span>
                <span aria-hidden="true">·</span>
                <span>{environmentName}</span>
              </p>
            </div>
          </div>

          <div className="mt-3">
            <QueueResourceChips resources={entry.request.resources} compact={!active} />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Requested {entry.requested_at ? formatDate(entry.requested_at) : 'time unavailable'}
            </span>
            {entry.expires_at && (
              <span className="inline-flex items-center gap-1">
                <Timer className="h-3 w-3" />
                Expires {formatDate(entry.expires_at)}
              </span>
            )}
            {showPriority && (
              <span className="inline-flex items-center gap-1 font-medium text-foreground">
                <ListOrdered className="h-3 w-3" />
                Priority position {entry.position}
              </span>
            )}
            {entry.status === 'started' && entry.started_at && (
              <span className="inline-flex items-center gap-1">
                <Play className="h-3 w-3" />
                Started {formatDate(entry.started_at)}
              </span>
            )}
          </div>

          {entry.reason_code === 'recovery_required' ? (
            <QueueRecoveryNotice reasonCode={entry.reason_code} className="mt-3" />
          ) : (
            entry.message && (
              <p
                className={cn(
                  'mt-3 rounded-lg border px-3 py-2 text-xs',
                  active
                    ? 'border-primary/15 bg-primary/5 text-foreground/80'
                    : 'border-border/50 bg-surface/50 text-muted-foreground'
                )}
              >
                {entry.message}
              </p>
            )
          )}

          <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
            <Button variant="outline" size="sm" onClick={onSelect}>
              View request
            </Button>
            {entry.status === 'started' && launched && (
              <ViewServerLink server={launched} username={username} />
            )}
            {canManage && canCancelQueuedRequest(entry) && (
              <Button
                variant="ghost"
                size="sm"
                disabled={cancelPending}
                onClick={onCancel}
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
              >
                Cancel request
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.article>
  )
}

function DetailField({
  icon: Icon,
  label,
  value,
}: {
  icon: LucideIcon
  label: string
  value: ReactNode
}) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-border/50 bg-surface/50 p-3">
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
        <div className="mt-0.5 break-words text-sm font-medium">{value}</div>
      </div>
    </div>
  )
}

function QueueTimeline({ entry }: { entry: ServerQueueEntry }) {
  const queueValue =
    entry.status === 'pending'
      ? 'Waiting for capacity'
      : entry.status === 'scheduled'
        ? 'Scheduled for launch'
        : entry.status === 'starting'
          ? 'Launch in progress'
          : entry.status === 'started'
            ? 'Launch complete'
            : entry.status === 'failed'
              ? 'Launch failed'
              : 'Request closed'

  const queueTone =
    entry.status === 'started'
      ? 'bg-emerald-500/10 text-emerald-400'
      : entry.status === 'failed'
        ? 'bg-red-500/10 text-red-400'
        : entry.status === 'cancelled'
          ? 'bg-muted/50 text-muted-foreground'
          : 'bg-primary/10 text-primary'

  const launchValue =
    entry.status === 'started'
      ? entry.started_at
        ? formatDate(entry.started_at)
        : 'Time unavailable'
      : entry.status === 'starting'
        ? entry.reason_code === 'recovery_required'
          ? 'Needs review'
          : 'In progress'
        : entry.status === 'failed'
          ? 'Did not complete'
          : entry.status === 'cancelled'
            ? 'Not launched'
            : 'Not started'

  const launchTone =
    entry.status === 'started'
      ? 'bg-emerald-500/10 text-emerald-400'
      : entry.status === 'starting'
        ? 'bg-amber-500/10 text-amber-400'
        : entry.status === 'failed'
          ? 'bg-red-500/10 text-red-400'
          : 'bg-muted/50 text-muted-foreground'

  const steps = [
    {
      label: 'Requested',
      value: entry.requested_at ? formatDate(entry.requested_at) : 'Time unavailable',
      icon: Clock,
      tone: 'bg-primary/10 text-primary',
    },
    { label: 'Queue', value: queueValue, icon: Timer, tone: queueTone },
    { label: 'Launch', value: launchValue, icon: Play, tone: launchTone },
  ]

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
      {steps.map(({ label, value, icon: Icon, tone }) => (
        <div
          key={label}
          className="flex items-start gap-2.5 rounded-lg border border-border/50 bg-surface/50 p-3"
        >
          <div className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-lg', tone)}>
            <Icon className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              {label}
            </p>
            <p className="mt-0.5 break-words text-xs font-medium">{value}</p>
          </div>
        </div>
      ))}
    </div>
  )
}

export function QueueRequestDetail({
  entry,
  planName,
  environmentName,
  launched,
  username,
  canManage,
  cancelPending,
  onCancel,
  onClose,
}: {
  entry: ServerQueueEntry
  planName: string
  environmentName: string
  launched?: Server
  username?: string
  canManage: boolean
  cancelPending: boolean
  onCancel: () => void
  onClose: () => void
}) {
  const active = isQueueActive(entry)
  const config = statusConfig[entry.status]
  const StatusIcon = config.icon
  const showPriority = entry.position !== null && entry.position > 0

  return (
    <div className="mt-5 space-y-3">
      <div
        data-testid={`queue-request-${entry.id}`}
        className={cn(
          'relative overflow-hidden rounded-xl border p-4',
          active ? 'border-primary/25 bg-primary/5' : 'border-border/50 bg-surface/50'
        )}
      >
        {active && (
          <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-primary/60" />
        )}
        <div className="flex items-start gap-3">
          <div
            className={cn(
              'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl',
              config.tile
            )}
          >
            <StatusIcon className={cn('h-4 w-4', entry.status === 'starting' && 'animate-spin')} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="break-all text-base font-semibold">{entry.request.name}</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Saved launch configuration and current queue state.
            </p>
          </div>
          <QueueStatusPill status={entry.status} />
        </div>
        <div className="mt-4">
          <QueueTimeline entry={entry} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <DetailField icon={Layers} label="Plan" value={planName} />
        <DetailField icon={Box} label="Environment" value={environmentName} />
        <DetailField
          icon={Clock}
          label="Requested"
          value={entry.requested_at ? formatDate(entry.requested_at) : 'Time unavailable'}
        />
        <DetailField
          icon={Timer}
          label="Expires"
          value={entry.expires_at ? formatDate(entry.expires_at) : 'No expiry recorded'}
        />
        <DetailField
          icon={ListOrdered}
          label="Priority"
          value={showPriority ? `Priority position ${entry.position}` : 'Not currently queued'}
        />
        <DetailField
          icon={Play}
          label="Launch time"
          value={
            entry.started_at
              ? formatDate(entry.started_at)
              : entry.status === 'started'
                ? 'Time unavailable'
                : 'Not started'
          }
        />
        <div className="rounded-lg border border-border/50 bg-surface/50 p-3 sm:col-span-2">
          <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            <Cpu className="h-3.5 w-3.5" />
            Resources
          </p>
          <div className="mt-2">
            <QueueResourceChips resources={entry.request.resources} />
          </div>
        </div>
      </div>

      {entry.reason_code === 'recovery_required' ? (
        <QueueRecoveryNotice reasonCode={entry.reason_code} />
      ) : (
        <div className="flex items-start gap-2.5 rounded-xl border border-primary/15 bg-primary/5 p-3">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <div className="min-w-0">
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Request message
            </p>
            <p className="mt-0.5 text-sm text-foreground/90">
              {entry.message || 'No message provided.'}
            </p>
          </div>
        </div>
      )}

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Close details
        </Button>
        {entry.status === 'started' && launched && (
          <ViewServerLink server={launched} username={username} className="h-9 px-4 text-sm" />
        )}
        {canManage && canCancelQueuedRequest(entry) && (
          <Button
            variant="outline"
            disabled={cancelPending}
            onClick={onCancel}
            className="border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive"
          >
            Cancel request
          </Button>
        )}
      </DialogFooter>
    </div>
  )
}

function QueueEmptyState({
  filter,
  onShowAll,
}: {
  filter: QueueFilterDefinition
  onShowAll: () => void
}) {
  const Icon = filter.icon
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={springs.gentle}>
      <Card variant="bubble" className="border-border/50">
        <CardContent className="flex flex-col items-center px-6 py-10 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-muted/50 text-muted-foreground">
            <Icon className="h-6 w-6" />
          </div>
          <h3 className="mt-3 text-sm font-semibold">{filter.emptyTitle}</h3>
          <p className="mt-1 max-w-md text-xs text-muted-foreground">{filter.emptyDescription}</p>
          {filter.key !== 'all' && (
            <Button variant="outline" size="sm" onClick={onShowAll} className="mt-4">
              View all requests
            </Button>
          )}
        </CardContent>
      </Card>
    </motion.div>
  )
}

function QueueLoadingState() {
  return (
    <div role="status" className="space-y-3">
      <span className="sr-only">Loading requests…</span>
      {[0, 1].map((index) => (
        <div key={index} className="bubble space-y-4 p-5">
          <div className="flex items-center gap-3">
            <Skeleton className="h-10 w-10 rounded-xl" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-44" />
              <Skeleton className="h-3 w-32" />
            </div>
            <Skeleton className="h-5 w-20 rounded-full" />
          </div>
          <Skeleton className="h-3 w-full" />
          <div className="flex gap-2">
            <Skeleton className="h-6 w-20" />
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-6 w-20" />
          </div>
        </div>
      ))}
    </div>
  )
}

function QueueDetailSkeleton() {
  return (
    <div role="status" className="mt-5 space-y-3">
      <span className="sr-only">Loading request…</span>
      <div className="space-y-3 rounded-xl border border-border/50 bg-surface/50 p-4">
        <div className="flex items-center gap-3">
          <Skeleton className="h-10 w-10 rounded-xl" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-44" />
            <Skeleton className="h-3 w-32" />
          </div>
          <Skeleton className="h-5 w-20 rounded-full" />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Skeleton className="h-16 rounded-lg" />
          <Skeleton className="h-16 rounded-lg" />
          <Skeleton className="h-16 rounded-lg" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Skeleton className="h-14 rounded-lg" />
        <Skeleton className="h-14 rounded-lg" />
        <Skeleton className="h-14 rounded-lg" />
        <Skeleton className="h-14 rounded-lg" />
      </div>
    </div>
  )
}

function QueueErrorState({ error, retry }: { error: Error | null; retry: () => void }) {
  const message =
    error instanceof ApiError && error.status === 403
      ? 'You do not have permission to view these requests.'
      : error instanceof ApiError && error.status === 404
        ? 'This request is unavailable or no longer exists.'
        : 'Requests could not be refreshed. Displayed information may be out of date.'
  return (
    <div
      role="alert"
      className="bubble flex flex-col gap-3 border border-destructive/20 p-4 sm:flex-row sm:items-start"
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
        <AlertTriangle className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm font-medium">Could not refresh requests</p>
        <p className="text-xs text-muted-foreground">{message}</p>
      </div>
      <Button variant="outline" size="sm" onClick={retry}>
        Retry
      </Button>
    </div>
  )
}

export function ServerQueuePanel({ requestId, plans, environments, onSelect }: QueuePanelProps) {
  const [page, setPage] = useState(1)
  const [filterKey, setFilterKey] = useState<QueueFilterKey>('active')
  const filter = queueFilters.find((item) => item.key === filterKey) ?? queueFilters[0]
  const headingId = useId()
  const descriptionId = useId()
  const detailRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!requestId) return
    const previous = document.activeElement
    const frame = requestAnimationFrame(() => detailRef.current?.focus())
    return () => {
      cancelAnimationFrame(frame)
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [requestId])
  const queue = useServerQueue(
    page,
    true,
    filter.statuses,
    filter.key === 'active' || filter.key === 'all'
  )
  const { data: servers = [] } = useServers()
  const detail = useServerQueueEntry(requestId, true)
  const cancel = useCancelServerQueue()
  const { confirm, dialog } = useConfirmDialog()
  const canManage = useAuthStore((state) => state.hasPermission(PERMISSIONS.SERVERS_WRITE_OWN))
  const username = useAuthStore((state) => state.user?.username)
  const ownerId = useAuthStore((state) => state.user?.id)
  const pageCount = queue.data ? Math.max(1, Math.ceil(queue.data.total / queue.data.page_size)) : 1

  useEffect(() => {
    if (!queue.data || page <= pageCount) return
    // The server owns the page count; polling or cancellation can shrink it.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPage(pageCount)
  }, [page, pageCount, queue.data])

  const cancelRequest = async (entry: ServerQueueEntry) => {
    if (!canCancelQueuedRequest(entry) || !canManage) return
    if (
      !(await confirm({
        title: 'Cancel waiting request?',
        description: `Cancel ${entry.request.name}? Its selected configuration will not be launched.`,
        confirmLabel: 'Cancel request',
        cancelLabel: 'Keep waiting',
        variant: 'warning',
      }))
    )
      return
    if (useAuthStore.getState().user?.id !== ownerId) return
    cancel.mutate(entry, {
      onSuccess: () => {
        if (useAuthStore.getState().user?.id !== ownerId) return
        useToastStore
          .getState()
          .addToast({ type: 'info', title: 'Request cancelled', message: entry.request.name })
      },
      onError: (error) =>
        useToastStore.getState().addToast({
          type: 'error',
          title:
            error instanceof ApiError && error.status === 409
              ? 'Launch already in progress'
              : 'Could not cancel request',
          message:
            error instanceof ApiError && error.status === 409
              ? 'Refresh the request to see its current status.'
              : 'The request is unchanged. Refresh and try again.',
        }),
    })
  }

  const planName = (entry: ServerQueueEntry) =>
    plans.find((plan) => plan.id === entry.request.plan_id)?.name ?? 'Selected plan'
  const environmentName = (entry: ServerQueueEntry) =>
    environments.find((environment) => environment.id === entry.request.environment_id)?.name ??
    'Selected environment'
  const launchedServer = (entry: ServerQueueEntry) =>
    servers.find((server) => server.id === entry.server_id)

  return (
    <section aria-label="Waiting server requests" className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Clock className="h-4 w-4" />
            </span>
            Waiting requests
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Track saved launch requests and their current queue state.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          aria-label="Refresh waiting requests"
          disabled={queue.isFetching}
          onClick={() => void queue.refetch()}
        >
          <RefreshCw className={cn('h-4 w-4', queue.isFetching && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      <div className="flex flex-col gap-3">
        <div
          role="group"
          aria-label="Request status filter"
          className="flex w-fit items-center gap-0.5 rounded-lg border border-input/50 bg-input/80 p-0.5"
        >
          {queueFilters.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-pressed={filter.key === item.key}
              onClick={() => {
                setFilterKey(item.key)
                setPage(1)
              }}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs font-medium transition-all',
                filter.key === item.key
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {item.label}
            </button>
          ))}
        </div>

        {queue.data && (
          <div className="flex flex-col gap-2 rounded-xl border border-border/50 bg-surface/50 px-4 py-3 text-xs sm:flex-row sm:items-center sm:justify-between">
            <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-medium text-foreground">{filter.label}</span>
              <span className="rounded-full bg-primary/10 px-2 py-0.5 font-medium text-primary">
                {queue.data.total} {queue.data.total === 1 ? 'request' : 'requests'}
              </span>
              {pageCount > 1 && (
                <span className="text-muted-foreground">
                  Page {queue.data.page} of {pageCount}
                </span>
              )}
            </span>
            <p className="inline-flex items-start gap-1.5 text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              Waiting is not billed. Priority position does not guarantee a start time.
            </p>
          </div>
        )}
      </div>

      {queue.isError && <QueueErrorState error={queue.error} retry={() => void queue.refetch()} />}
      {queue.isPending && <QueueLoadingState />}
      {queue.data?.items.length === 0 && (
        <QueueEmptyState
          filter={filter}
          onShowAll={() => {
            setFilterKey('all')
            setPage(1)
          }}
        />
      )}
      {queue.data && queue.data.items.length > 0 && (
        <div className="space-y-3">
          {queue.data.items.map((entry, index) => (
            <QueueRequestCard
              key={entry.id}
              entry={entry}
              index={index}
              planName={planName(entry)}
              environmentName={environmentName(entry)}
              launched={launchedServer(entry)}
              username={username}
              canManage={canManage}
              cancelPending={cancel.isPending}
              onSelect={() => onSelect(entry.id)}
              onCancel={() => void cancelRequest(entry)}
            />
          ))}
        </div>
      )}

      {queue.data && queue.data.total > 0 && pageCount > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>
            Page {queue.data.page} of {pageCount}
          </span>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={page <= 1 || queue.isFetching}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={page >= pageCount || queue.isFetching}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      <Dialog
        open={!!requestId}
        onOpenChange={(open) => {
          if (!open) onSelect()
        }}
        size="lg"
      >
        <DialogContent
          ref={detailRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={headingId}
          aria-describedby={descriptionId}
          tabIndex={-1}
          className="flex min-h-full flex-col"
          onKeyDown={(event) => {
            if (event.key !== 'Tab') return
            const controls = detailRef.current?.querySelectorAll<HTMLElement>(
              'button:not(:disabled), a[href], [tabindex="0"]'
            )
            const first = controls?.[0]
            const last = controls?.[controls.length - 1]
            if (!first || !last) {
              event.preventDefault()
              return
            }
            if (
              event.shiftKey &&
              (document.activeElement === first || document.activeElement === detailRef.current)
            ) {
              event.preventDefault()
              last.focus()
            } else if (
              !event.shiftKey &&
              (document.activeElement === last || document.activeElement === detailRef.current)
            ) {
              event.preventDefault()
              first.focus()
            }
          }}
        >
          <DialogHeader>
            <DialogTitle id={headingId} className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-primary" aria-hidden="true" />
              Server request
            </DialogTitle>
            <DialogDescription id={descriptionId}>
              Saved configuration and current launch status.
            </DialogDescription>
          </DialogHeader>
          {detail.isPending && <QueueDetailSkeleton />}
          {detail.isError && (
            <div className="mt-5">
              <QueueErrorState error={detail.error} retry={() => void detail.refetch()} />
            </div>
          )}
          {detail.data && (
            <QueueRequestDetail
              entry={detail.data}
              planName={planName(detail.data)}
              environmentName={environmentName(detail.data)}
              launched={launchedServer(detail.data)}
              username={username}
              canManage={canManage}
              cancelPending={cancel.isPending}
              onCancel={() => void cancelRequest(detail.data)}
              onClose={() => onSelect()}
            />
          )}
          <p className="mt-auto flex items-start gap-2 border-t border-border/40 pt-4 text-[11px] leading-relaxed text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {detail.data?.can_cancel
              ? 'Waiting is not billed. You can cancel while the request is pending; once launch starts, it can no longer be cancelled.'
              : detail.data?.status === 'starting'
                ? 'Waiting is not billed. Launch is starting; this request can no longer be cancelled.'
                : detail.data?.status === 'failed'
                  ? 'Waiting is not billed. This request failed; submit a new request to try again.'
                  : detail.data?.status === 'cancelled'
                    ? 'Waiting is not billed. This request was cancelled.'
                    : 'Waiting is not billed.'}
          </p>
          <DialogClose onClick={() => onSelect()} />
        </DialogContent>
      </Dialog>
      {dialog}
    </section>
  )
}
