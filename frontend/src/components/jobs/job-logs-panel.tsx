// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  FileText,
  RefreshCw,
  ScrollText,
} from 'lucide-react'
import { ApiError } from '../../lib/api'
import { jobLogStateDescription, jobLogStateLabel } from '../../lib/batch-job'
import { cn, formatBytes, formatDate } from '../../lib/utils'
import type { JobLogState, JobLogSummary } from '../../types/batch-job'
import { Button } from '../ui/button'
import { CopyButton } from '../ui/copy-button'
import { Skeleton } from '../feedback/skeleton'
import { useJobLogs } from '../../hooks/use-jobs'

const logTone: Record<JobLogState, string> = {
  pending: 'border-blue-500/20 bg-blue-500/10 text-blue-400',
  available: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400',
  truncated: 'border-amber-500/20 bg-amber-500/10 text-amber-400',
  unavailable: 'border-border/50 bg-muted/50 text-muted-foreground',
  expired: 'border-border/50 bg-muted/50 text-muted-foreground',
}

function LogStatePill({ state }: { state: JobLogState }) {
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[11px] font-medium',
        logTone[state]
      )}
    >
      {jobLogStateLabel(state)}
    </span>
  )
}

export function JobLogsPanel({ jobId, summary }: { jobId: string; summary: JobLogSummary }) {
  const [open, setOpen] = useState(false)
  const canFetch = summary.state === 'available' || summary.state === 'truncated'
  const logs = useJobLogs(jobId, open && canFetch)
  const data = logs.data
  const state = data?.state ?? summary.state
  const text = data?.text ?? null
  const truncated = data?.truncated ?? summary.truncated
  const sizeBytes = data?.size_bytes ?? summary.size_bytes
  const expiresAt = data?.expires_at ?? summary.expires_at

  const errorMessage =
    logs.error instanceof ApiError && logs.error.status === 404
      ? 'Logs are no longer available for this job.'
      : logs.error instanceof ApiError && logs.error.status === 403
        ? 'You no longer have permission to view these logs.'
        : 'Logs could not be loaded. The job itself is unchanged.'

  return (
    <section aria-labelledby="job-logs-heading" className="bubble p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="job-logs-heading" className="flex items-center gap-2 text-base font-semibold">
            <ScrollText className="h-4 w-4 text-primary" aria-hidden="true" />
            Logs
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {jobLogStateDescription(state)}
            {sizeBytes > 0 && ` ${formatBytes(sizeBytes)} retained.`}
            {expiresAt && ` Available until ${formatDate(expiresAt)}.`}
          </p>
        </div>
        <LogStatePill state={state} />
      </div>

      {truncated && state !== 'pending' && (
        <div
          role="status"
          className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-400"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          Only the last {formatBytes(sizeBytes)} of output was retained. Earlier output is not
          available.
        </div>
      )}

      {canFetch && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-expanded={open}
            aria-controls="job-log-output"
            onClick={() => setOpen((current) => !current)}
          >
            {open ? (
              <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {open ? 'Hide logs' : 'Show logs'}
          </Button>
          {open && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label="Refresh job logs"
              disabled={logs.isFetching}
              onClick={() => void logs.refetch()}
            >
              <RefreshCw
                className={cn('h-3.5 w-3.5', logs.isFetching && 'animate-spin')}
                aria-hidden="true"
              />
              Refresh
            </Button>
          )}
          {open && text && <CopyButton value={text} label="Copy job logs" />}
        </div>
      )}

      {open && canFetch && (
        <div id="job-log-output" className="mt-3">
          {logs.isPending && (
            <div role="status" className="space-y-2" aria-label="Loading job logs">
              <Skeleton className="h-3 w-4/5" />
              <Skeleton className="h-3 w-3/5" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          )}
          {logs.isError && (
            <div
              role="alert"
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-muted-foreground"
            >
              <span>{errorMessage}</span>
              <Button variant="outline" size="sm" onClick={() => void logs.refetch()}>
                Retry
              </Button>
            </div>
          )}
          {data && (data.state === 'available' || data.state === 'truncated') && (
            <>
              {text ? (
                <div
                  role="region"
                  aria-label="Job output logs"
                  className="max-h-96 overflow-auto rounded-lg border border-border/50 bg-surface/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                >
                  <pre
                    tabIndex={0}
                    aria-label="Job output text"
                    className="whitespace-pre-wrap break-words p-3 font-mono text-xs leading-relaxed text-foreground/90 focus-visible:outline-none"
                  >
                    {text}
                  </pre>
                </div>
              ) : (
                <p className="rounded-lg border border-border/50 bg-surface/50 p-3 text-xs text-muted-foreground">
                  The runtime captured no output.
                </p>
              )}
            </>
          )}
          {data &&
            (data.state === 'pending' ||
              data.state === 'unavailable' ||
              data.state === 'expired') && (
              <p className="flex items-start gap-2 rounded-lg border border-border/50 bg-surface/50 p-3 text-xs text-muted-foreground">
                <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                {jobLogStateDescription(data.state)}
              </p>
            )}
        </div>
      )}

      {!canFetch && (
        <p className="mt-3 flex items-start gap-2 rounded-lg border border-border/50 bg-surface/50 p-3 text-xs text-muted-foreground">
          <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {summary.state === 'pending'
            ? 'Logs will be collected when the runtime starts. This page refreshes automatically while the job is active.'
            : jobLogStateDescription(summary.state)}
        </p>
      )}
    </section>
  )
}
