// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { Link } from '@tanstack/react-router'
import {
  AlertTriangle,
  ArrowRight,
  Clock,
  History,
  Inbox,
  Plus,
  RefreshCw,
  Terminal,
} from 'lucide-react'
import { ApiError } from '../../lib/api'
import { jobErrorMessage, jobReasonCopy } from '../../lib/batch-job'
import { cn, formatDate } from '../../lib/utils'
import type { JobListFilter, JobSummary } from '../../types/batch-job'
import { Button } from '../ui/button'
import { buttonVariants } from '../ui/button-variants'
import { Card, CardContent } from '../ui/card'
import { EmptyState } from '../feedback/empty-state'
import { Skeleton } from '../feedback/skeleton'
import { JobStatusPill } from './job-status-pill'

export function JobsLoadingState() {
  return (
    <div role="status" className="space-y-3" aria-label="Loading jobs">
      {[0, 1, 2].map((index) => (
        <div key={index} className="bubble space-y-3 p-5">
          <div className="flex items-center gap-3">
            <Skeleton className="h-9 w-9 rounded-xl" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-3 w-32" />
            </div>
            <Skeleton className="h-5 w-20 rounded-full" />
          </div>
          <Skeleton className="h-3 w-2/3" />
        </div>
      ))}
    </div>
  )
}

export function JobsCapabilityLoadingState() {
  return (
    <div role="status" aria-label="Checking job availability" className="space-y-3">
      <div className="bubble space-y-3 p-5">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-3 w-2/3" />
        <Skeleton className="h-3 w-1/2" />
      </div>
    </div>
  )
}

export function JobsDisabledState({ reasonCode }: { reasonCode: string | null }) {
  return (
    <Card variant="bubble">
      <CardContent className="flex flex-col items-start gap-3 p-6">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted/50 text-muted-foreground">
          <Terminal className="h-5 w-5" aria-hidden="true" />
        </div>
        <div>
          <h2 className="text-base font-semibold">Batch jobs are not available</h2>
          <p role="status" className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {jobErrorMessage(
              reasonCode,
              'Job submission is disabled for this deployment or account. No job records are queried while the feature is unavailable.'
            )}
          </p>
        </div>
        <p className="text-xs text-muted-foreground">
          If you expected access, contact an administrator. Existing authorized job history becomes
          available here when the feature is enabled.
        </p>
      </CardContent>
    </Card>
  )
}

export function JobsErrorState({
  error,
  retry,
  compact = false,
}: {
  error: Error | null
  retry: () => void
  compact?: boolean
}) {
  const message =
    error instanceof ApiError && error.status === 404
      ? 'This job list is unavailable or no longer exists.'
      : error instanceof ApiError && error.status === 403
        ? 'You do not have permission to view these jobs.'
        : 'Jobs could not be refreshed. Any content shown below may be out of date.'
  return (
    <div
      role="alert"
      className={cn(
        'bubble flex flex-col gap-3 border border-destructive/20 p-4 sm:flex-row sm:items-start',
        compact && 'p-3'
      )}
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-destructive/10 text-destructive">
        <AlertTriangle className="h-4 w-4" aria-hidden="true" />
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm font-medium">Could not load jobs</p>
        <p className="text-xs text-muted-foreground">{message}</p>
      </div>
      <Button variant="outline" size="sm" onClick={retry}>
        Retry
      </Button>
    </div>
  )
}

export function JobsEmptyState({
  filter,
  canSubmit,
  onNewJob,
  onShowAll,
}: {
  filter: JobListFilter
  canSubmit: boolean
  onNewJob: () => void
  onShowAll: () => void
}) {
  const copy =
    filter === 'active'
      ? {
          icon: Inbox,
          title: 'No active jobs',
          description: 'Queued, starting and running jobs appear here.',
        }
      : filter === 'history'
        ? {
            icon: History,
            title: 'No job history',
            description: 'Completed, failed, cancelled and expired jobs appear here.',
          }
        : {
            icon: Terminal,
            title: 'No jobs yet',
            description:
              'Submit one noninteractive command to run it in an approved environment with your private volume.',
          }
  return (
    <div className="bubble">
      <EmptyState
        icon={copy.icon}
        title={copy.title}
        description={copy.description}
        action={
          canSubmit
            ? {
                label: 'New job',
                onClick: onNewJob,
                icon: Plus,
              }
            : undefined
        }
        secondaryAction={
          filter !== 'all'
            ? {
                label: 'View all jobs',
                onClick: onShowAll,
              }
            : undefined
        }
      />
    </div>
  )
}

function reasonText(item: JobSummary) {
  if (item.state === 'recovery_required') return 'Operator verification required'
  return jobReasonCopy(item.reason_code)
}

function JobRowLink({ item, className }: { item: JobSummary; className?: string }) {
  return (
    <Link
      to="/jobs/$jobId"
      params={{ jobId: item.id }}
      className={cn(
        'inline-flex items-center gap-1.5 font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
        className
      )}
    >
      {item.name}
    </Link>
  )
}

export function JobsTable({ items }: { items: JobSummary[] }) {
  return (
    <div className="hidden overflow-x-auto rounded-xl border border-border/50 bg-card md:block">
      <table className="w-full text-sm">
        <caption className="sr-only">Your batch jobs</caption>
        <thead className="border-b border-border/50 bg-muted/40">
          <tr>
            <th scope="col" className="px-4 py-3 text-left font-medium">
              Name
            </th>
            <th scope="col" className="px-4 py-3 text-left font-medium">
              State
            </th>
            <th scope="col" className="px-4 py-3 text-left font-medium">
              Environment
            </th>
            <th scope="col" className="px-4 py-3 text-left font-medium">
              Created
            </th>
            <th scope="col" className="px-4 py-3 text-left font-medium">
              Started
            </th>
            <th scope="col" className="px-4 py-3 text-right font-medium">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const reason = reasonText(item)
            return (
              <tr
                key={item.id}
                data-testid={`job-row-${item.id}`}
                className="border-b border-border/40 last:border-0"
              >
                <td className="max-w-72 px-4 py-3">
                  <JobRowLink item={item} className="break-all" />
                  {reason && (
                    <p className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">
                      {reason}
                    </p>
                  )}
                </td>
                <td className="px-4 py-3">
                  <JobStatusPill state={item.state} size="sm" />
                </td>
                <td className="max-w-56 px-4 py-3">
                  <span className="line-clamp-1 text-muted-foreground">
                    {item.environment_name || 'Environment unavailable'}
                  </span>
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                  {formatDate(item.created_at)}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                  {item.started_at ? formatDate(item.started_at) : 'Not started'}
                </td>
                <td className="px-4 py-3 text-right">
                  <Link
                    to="/jobs/$jobId"
                    params={{ jobId: item.id }}
                    className="inline-flex items-center gap-1 text-xs font-medium text-primary underline-offset-4 hover:underline"
                  >
                    View
                    <ArrowRight className="h-3 w-3" aria-hidden="true" />
                    <span className="sr-only"> {item.name}</span>
                  </Link>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function JobsCards({ items }: { items: JobSummary[] }) {
  return (
    <ul className="space-y-3 md:hidden">
      {items.map((item) => {
        const reason = reasonText(item)
        return (
          <li key={item.id}>
            <Card variant="bubble" className="overflow-hidden">
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <JobRowLink item={item} className="break-all text-sm" />
                    <p className="mt-1 text-xs text-muted-foreground">
                      {item.environment_name || 'Environment unavailable'}
                    </p>
                  </div>
                  <JobStatusPill state={item.state} size="sm" />
                </div>
                {reason && (
                  <p className="mt-3 rounded-lg border border-border/50 bg-surface/50 px-2.5 py-2 text-xs text-muted-foreground">
                    {reason}
                  </p>
                )}
                <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <dt className="text-muted-foreground">Created</dt>
                    <dd className="mt-0.5 text-foreground">{formatDate(item.created_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Started</dt>
                    <dd className="mt-0.5 text-foreground">
                      {item.started_at ? formatDate(item.started_at) : 'Not started'}
                    </dd>
                  </div>
                </dl>
                <div className="mt-3 flex justify-end">
                  <Link
                    to="/jobs/$jobId"
                    params={{ jobId: item.id }}
                    className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
                  >
                    <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                    Open job
                    <span className="sr-only"> {item.name}</span>
                  </Link>
                </div>
              </CardContent>
            </Card>
          </li>
        )
      })}
    </ul>
  )
}

export function JobsLoadMore({
  hasNextPage,
  loading,
  onLoadMore,
}: {
  hasNextPage: boolean
  loading: boolean
  onLoadMore: () => void
}) {
  if (!hasNextPage) return null
  return (
    <div className="flex justify-center pt-1">
      <Button variant="outline" size="sm" loading={loading} disabled={loading} onClick={onLoadMore}>
        <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
        Load more jobs
      </Button>
    </div>
  )
}
