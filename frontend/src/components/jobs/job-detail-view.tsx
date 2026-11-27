// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { type ElementType, type ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import {
  AlertTriangle,
  Ban,
  Boxes,
  Clock,
  Copy as CopyIcon,
  Cpu,
  HardDrive,
  Info,
  Layers,
  MemoryStick,
  Play,
  RefreshCw,
  ScrollText,
  ShieldAlert,
  Terminal,
  Timer,
  XCircle,
  Zap,
} from 'lucide-react'
import { ApiError } from '../../lib/api'
import {
  canCancelJob,
  jobErrorMessage,
  jobOutcomeLabel,
  jobProofLabel,
  jobReasonCopy,
  jobStateDescription,
  jobStateLabel,
} from '../../lib/batch-job'
import { cn, formatBytes, formatDate, formatDuration } from '../../lib/utils'
import { useCancelJob, useJobCapabilities, useJobDetail } from '../../hooks/use-jobs'
import { usePageGuard } from '../../hooks/use-page-guard'
import { useAuthStore, PERMISSIONS } from '../../stores/auth-store'
import { useToastStore } from '../../stores/toast-store'
import { ResourcePageLayout } from '../layout/resource-page-layout'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { CopyButton } from '../ui/copy-button'
import { useConfirmDialog } from '../ui/confirm-dialog'
import { Skeleton } from '../feedback/skeleton'
import { JobLogsPanel } from './job-logs-panel'
import { JobStatusPill } from './job-status-pill'
import type { JobDetail } from '../../types/batch-job'

function JobDetailSkeleton() {
  return (
    <div role="status" aria-label="Loading job" className="space-y-4">
      <div className="bubble space-y-3 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <Skeleton className="h-6 w-24 rounded-full" />
          <Skeleton className="h-5 w-60" />
        </div>
        <Skeleton className="h-3 w-2/3" />
        <Skeleton className="h-3 w-1/2" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="bubble space-y-3 p-5">
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-4/5" />
        </div>
        <div className="bubble space-y-3 p-5">
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-4/5" />
        </div>
      </div>
      <div className="bubble space-y-3 p-5">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-5/6" />
      </div>
    </div>
  )
}

function UnavailableJob({ permissionDenied = false }: { permissionDenied?: boolean }) {
  return (
    <Card variant="bubble">
      <CardContent className="flex flex-col items-start gap-3 p-6">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted/50 text-muted-foreground">
          <Terminal className="h-5 w-5" aria-hidden="true" />
        </div>
        <div>
          <h2 className="text-base font-semibold">Job unavailable</h2>
          <p role="status" className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {permissionDenied
              ? 'You no longer have permission to view this job.'
              : 'This job does not exist or is not available to this account.'}
          </p>
        </div>
        <Link
          to="/jobs"
          className="text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          Back to jobs
        </Link>
      </CardContent>
    </Card>
  )
}

function DetailField({
  label,
  children,
  mono = false,
  className,
}: {
  label: string
  children: ReactNode
  mono?: boolean
  className?: string
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <dt className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd className={cn('mt-0.5 break-words text-sm', mono && 'font-mono text-xs')}>{children}</dd>
    </div>
  )
}

function DetailSection({
  title,
  icon: Icon,
  children,
  className,
}: {
  title: string
  icon: ElementType
  children: ReactNode
  className?: string
}) {
  return (
    <section aria-label={title} className={cn('bubble p-5', className)}>
      <h2 className="flex items-center gap-2 text-base font-semibold">
        <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
        {title}
      </h2>
      <div className="mt-4">{children}</div>
    </section>
  )
}

function CopyableValue({ value, label }: { value: string; label: string }) {
  return (
    <span className="inline-flex max-w-full items-center gap-1">
      <span className="break-all font-mono text-xs">{value}</span>
      <CopyButton value={value} label={label} />
    </span>
  )
}

function OutcomeCard({
  job,
  canCancel,
  cancelPending,
  onCancel,
}: {
  job: JobDetail
  canCancel: boolean
  cancelPending: boolean
  onCancel: () => void
}) {
  const reason = job.reason_message || jobReasonCopy(job.reason_code)
  const result = job.result
  return (
    <Card variant="bubble" className="overflow-hidden">
      <CardContent className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <JobStatusPill state={job.state} />
            <h2 className="text-lg font-semibold">
              {result ? jobOutcomeLabel(result.outcome_code) : jobStateLabel(job.state)}
            </h2>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {canCancel && (
              <Button
                variant="outline"
                size="sm"
                loading={cancelPending}
                disabled={cancelPending}
                onClick={onCancel}
                className="border-destructive/30 text-destructive hover:bg-destructive/10 hover:text-destructive"
              >
                <Ban className="h-3.5 w-3.5" aria-hidden="true" />
                Cancel job
              </Button>
            )}
          </div>
        </div>

        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          {jobStateDescription(job.state)}
        </p>

        {reason && (
          <p className="mt-3 rounded-lg border border-primary/15 bg-primary/5 px-3 py-2 text-xs text-foreground/80">
            {reason}
            {job.reason_code && (
              <span className="ml-2 font-mono text-[10px] text-muted-foreground">
                {job.reason_code}
              </span>
            )}
          </p>
        )}

        {job.state === 'cancelling' && (
          <p
            role="status"
            className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-muted-foreground"
          >
            <Clock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" aria-hidden="true" />
            Stop requested. The runtime must confirm termination before resources are released.
            Refreshing, closing this page, or cancelling again does not force a second stop.
          </p>
        )}

        {job.state === 'recovery_required' && (
          <div
            role="status"
            className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2.5"
          >
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
            <div className="min-w-0">
              <p className="text-sm font-medium text-amber-400">Operator verification required</p>
              <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                The recorded runtime evidence is incomplete, so the outcome cannot be finalized and
                resources stay reserved. An authorized operator must reconcile this job before it
                can be retried. Do not submit a duplicate job.
              </p>
            </div>
          </div>
        )}

        {result && (
          <div className="mt-4 grid grid-cols-2 gap-3 rounded-lg border border-border/50 bg-surface/50 p-3 sm:grid-cols-4">
            <DetailField label="Exit code">
              {result.exit_code === null ? (
                <span className="text-amber-400">Not available</span>
              ) : (
                <span className={result.exit_code === 0 ? 'text-emerald-400' : 'text-red-400'}>
                  {result.exit_code}
                </span>
              )}
            </DetailField>
            <DetailField label="Duration">
              {result.duration_seconds === null
                ? 'Not recorded'
                : formatDuration(result.duration_seconds)}
            </DetailField>
            <DetailField label="Proof">{jobProofLabel(result.proof)}</DetailField>
            <DetailField label="Finished">
              {result.finished_at ? formatDate(result.finished_at) : 'Not recorded'}
            </DetailField>
          </div>
        )}

        {!result && job.state === 'failed' && (
          <p className="mt-3 flex items-start gap-2 text-xs text-muted-foreground">
            <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" aria-hidden="true" />
            No terminal result was persisted for this failure. The runtime outcome may be
            incomplete.
          </p>
        )}

        {result && result.exit_code === null && (
          <p className="mt-3 flex items-start gap-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            The daemon could not prove an exit code. The recorded outcome comes from the available
            runtime evidence.
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function EnvironmentSection({ job }: { job: JobDetail }) {
  return (
    <DetailSection title="Environment snapshot" icon={Boxes}>
      <dl className="space-y-3">
        <DetailField label="Approved revision">
          <span className="font-medium">
            {job.environment.display_label || job.environment.name}
          </span>
        </DetailField>
        <DetailField label="Image reference" mono>
          {job.environment.image_reference ? (
            <CopyableValue value={job.environment.image_reference} label="Copy image reference" />
          ) : (
            'Not recorded'
          )}
        </DetailField>
        <DetailField label="Fingerprint" mono>
          {job.environment.fingerprint ? (
            <CopyableValue value={job.environment.fingerprint} label="Copy fingerprint" />
          ) : (
            'Not recorded'
          )}
        </DetailField>
        <DetailField label="Revision ID" mono>
          <CopyableValue value={job.environment.revision_id} label="Copy revision ID" />
        </DetailField>
      </dl>
    </DetailSection>
  )
}

function PlanSection({ job }: { job: JobDetail }) {
  return (
    <DetailSection title="Plan snapshot" icon={Cpu}>
      <p className="text-sm font-medium">{job.plan.name}</p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-surface/60 px-2 py-1 text-[11px] text-muted-foreground">
          <Cpu className="h-3 w-3" aria-hidden="true" />
          {job.plan.cpu} vCPU
        </span>
        <span className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-surface/60 px-2 py-1 text-[11px] text-muted-foreground">
          <MemoryStick className="h-3 w-3" aria-hidden="true" />
          {formatBytes(job.plan.memory_mib * 1024 * 1024)} RAM
        </span>
        <span className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-surface/60 px-2 py-1 text-[11px] text-muted-foreground">
          <HardDrive className="h-3 w-3" aria-hidden="true" />
          {formatBytes(job.plan.disk_mib * 1024 * 1024)} disk
        </span>
        <span className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-surface/60 px-2 py-1 text-[11px] text-muted-foreground">
          <Zap className="h-3 w-3" aria-hidden="true" />
          {job.plan.gpu_count} GPU
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <DetailField label="Rate">{job.plan.cost_per_hour} NUKE/hr</DetailField>
        <DetailField label="Billing">
          {job.billing.mode === 'zero_cost'
            ? 'Zero cost'
            : `${job.billing.charged.toLocaleString(undefined, { maximumFractionDigits: 2 })} NUKE charged`}
        </DetailField>
        <DetailField label="Maximum runtime">
          {formatDuration(job.limits.max_runtime_seconds)}
        </DetailField>
        <DetailField label="Plan ID" mono>
          <CopyableValue value={job.plan.id} label="Copy plan ID" />
        </DetailField>
      </dl>
    </DetailSection>
  )
}

function VolumeSection({ job }: { job: JobDetail }) {
  return (
    <DetailSection title="Output volume" icon={HardDrive}>
      {job.volume ? (
        <div className="space-y-3">
          <p className="text-sm font-medium">{job.volume.display_name}</p>
          <p className="text-xs text-muted-foreground">
            Files written under <code className="font-mono">/work</code> remain on this private
            volume after the runtime is removed.
          </p>
          {job.volume.available ? (
            <Link
              to="/volumes"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-primary underline-offset-4 hover:underline"
            >
              Open output volume
              <span className="sr-only"> {job.volume.display_name} on the Volumes page</span>
            </Link>
          ) : (
            <p role="status" className="text-xs text-amber-400">
              The output volume is no longer available to this account. Existing files may have been
              removed or access may have changed.
            </p>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No output volume is recorded for this job.</p>
      )}
    </DetailSection>
  )
}

function CommandSection({ job }: { job: JobDetail }) {
  return (
    <DetailSection title="Command" icon={Terminal}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Arguments are stored literally. No shell parsing or expansion occurred.
        </p>
        {job.argv.length > 0 && (
          <CopyButton value={job.argv.join('\n')} label="Copy job arguments" />
        )}
      </div>
      {job.argv.length > 0 ? (
        <ol className="mt-3 space-y-1.5" aria-label="Job command arguments">
          {job.argv.map((argument, index) => (
            <li
              key={`${index}-${argument}`}
              className="flex gap-2 rounded-md border border-border/50 bg-surface/50 px-2.5 py-1.5"
            >
              <span className="w-6 shrink-0 text-right font-mono text-[10px] text-muted-foreground">
                {index + 1}
              </span>
              <code className="min-w-0 break-all font-mono text-xs">{argument}</code>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">No command was recorded.</p>
      )}
      <p className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Layers className="h-3.5 w-3.5" aria-hidden="true" />
        Working directory: <code className="font-mono">/work</code>
      </p>
    </DetailSection>
  )
}

function TimelineSection({ job }: { job: JobDetail }) {
  return (
    <DetailSection title="Timeline" icon={Clock}>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <DetailField label="Created">{formatDate(job.created_at)}</DetailField>
        <DetailField label="Updated">
          {job.updated_at ? formatDate(job.updated_at) : 'Not recorded'}
        </DetailField>
        <DetailField label="Queue expires">
          {job.queue_expires_at ? formatDate(job.queue_expires_at) : 'No queue deadline'}
        </DetailField>
        <DetailField label="Started">
          {job.started_at ? formatDate(job.started_at) : 'Not started'}
        </DetailField>
        <DetailField label="Runtime deadline">
          {job.deadline_at ? formatDate(job.deadline_at) : 'No deadline recorded'}
        </DetailField>
        <DetailField label="Finished">
          {job.finished_at ? formatDate(job.finished_at) : 'Not finished'}
        </DetailField>
      </dl>
    </DetailSection>
  )
}

export function JobDetailView({ jobId }: { jobId: string }) {
  const allowed = usePageGuard({ permission: PERMISSIONS.JOBS_READ_OWN })
  const ownerId = useAuthStore((state) => state.user?.id)
  const canWrite = useAuthStore((state) => state.hasPermission(PERMISSIONS.JOBS_WRITE_OWN))
  const capabilities = useJobCapabilities()
  const detailEnabled = capabilities.data?.enabled === true
  const job = useJobDetail(jobId, detailEnabled)
  const cancelJob = useCancelJob()
  const { confirm, dialog } = useConfirmDialog()

  if (!allowed) return null

  const requestCancel = async (current: JobDetail) => {
    if (!canWrite || !canCancelJob(current)) return
    const queued = current.state === 'queued'
    const confirmed = await confirm({
      title: queued ? 'Cancel queued job?' : 'Stop running job?',
      description: queued
        ? `${current.name} will not be admitted or run. The work volume and plan reservation are not held while queued.`
        : `A stop will be requested for ${current.name}. The runtime must confirm termination before resources are released; the final state may be cancelled or a preserved natural result.`,
      confirmLabel: 'Cancel job',
      cancelLabel: 'Keep job',
      variant: 'warning',
    })
    if (!confirmed) return
    if (useAuthStore.getState().user?.id !== ownerId) return
    cancelJob.mutate(current, {
      onSuccess: (updated) => {
        if (useAuthStore.getState().user?.id !== ownerId) return
        useToastStore.getState().addToast({
          type: 'info',
          title: updated.state === 'cancelling' ? 'Stop requested' : 'Job cancelled',
          message:
            updated.state === 'cancelling'
              ? 'Waiting for the runtime to confirm termination.'
              : updated.name,
        })
      },
      onError: (error) => {
        if (useAuthStore.getState().user?.id !== ownerId) return
        const notCancellable =
          error instanceof ApiError &&
          (error.status === 409 || error.code === 'job_not_cancellable')
        useToastStore.getState().addToast({
          type: 'error',
          title: notCancellable ? 'Job can no longer be cancelled' : 'Could not cancel job',
          message: notCancellable
            ? 'Refresh the job to see its current authoritative state.'
            : 'The job is unchanged. Refresh and try again.',
        })
        if (notCancellable) void job.refetch()
      },
    })
  }

  const title = job.data?.name ?? 'Job'
  const subtitle = job.data
    ? `${job.data.environment.name} · /work · ${jobStateLabel(job.data.state)}`
    : 'Single-run batch job'

  return (
    <ResourcePageLayout title={title} subtitle={subtitle} icon={Terminal} backTo="/jobs">
      {capabilities.isPending && <JobDetailSkeleton />}

      {capabilities.isError && (
        <div role="alert" className="bubble p-5">
          <p className="text-sm font-medium">Job availability could not be checked.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {capabilities.error.message || 'Try refreshing the page.'}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => void capabilities.refetch()}
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            Retry
          </Button>
        </div>
      )}

      {capabilities.data && !capabilities.data.enabled && (
        <Card variant="bubble">
          <CardContent className="flex flex-col items-start gap-3 p-6">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted/50 text-muted-foreground">
              <Terminal className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <h2 className="text-base font-semibold">Batch jobs are not available</h2>
              <p role="status" className="mt-1 max-w-2xl text-sm text-muted-foreground">
                {jobErrorMessage(
                  capabilities.data.reason_code,
                  'This job cannot be displayed while job features are unavailable.'
                )}
              </p>
            </div>
            <Link
              to="/jobs"
              className="text-sm font-medium text-primary underline-offset-4 hover:underline"
            >
              Back to jobs
            </Link>
          </CardContent>
        </Card>
      )}

      {detailEnabled && job.isPending && <JobDetailSkeleton />}

      {detailEnabled && job.isError && (
        <div className="space-y-3">
          {job.error instanceof ApiError &&
          (job.error.status === 404 || job.error.status === 403) ? (
            <UnavailableJob permissionDenied={job.error.status === 403} />
          ) : (
            <div role="alert" className="bubble p-5">
              <div className="flex items-start gap-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                <div>
                  <p className="text-sm font-medium">Job details could not be loaded</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    The job is unchanged. Retry to refresh its authoritative state.
                  </p>
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => void job.refetch()}
              >
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                Retry
              </Button>
            </div>
          )}
        </div>
      )}

      {detailEnabled && job.data && (
        <div className="space-y-4">
          <OutcomeCard
            job={job.data}
            canCancel={canWrite && canCancelJob(job.data)}
            cancelPending={cancelJob.isPending}
            onCancel={() => void requestCancel(job.data!)}
          />

          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Timer className="h-3.5 w-3.5" aria-hidden="true" />
              Created {formatDate(job.data.created_at)}
            </span>
            {job.data.started_at && (
              <span className="inline-flex items-center gap-1">
                <Play className="h-3.5 w-3.5" aria-hidden="true" />
                Started {formatDate(job.data.started_at)}
              </span>
            )}
            <Button
              variant="ghost"
              size="sm"
              aria-label="Refresh job"
              disabled={job.isFetching}
              onClick={() => void job.refetch()}
            >
              <RefreshCw
                className={cn('h-3.5 w-3.5', job.isFetching && 'animate-spin')}
                aria-hidden="true"
              />
              Refresh
            </Button>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <EnvironmentSection job={job.data} />
            <PlanSection job={job.data} />
            <VolumeSection job={job.data} />
            <TimelineSection job={job.data} />
          </div>

          <CommandSection job={job.data} />

          <section aria-label="Billing and result" className="bubble p-5">
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <Cpu className="h-4 w-4 text-primary" aria-hidden="true" />
              Result and billing
            </h2>
            {job.data.result ? (
              <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <DetailField label="Outcome">
                  {jobOutcomeLabel(job.data.result.outcome_code)}
                </DetailField>
                <DetailField label="Exit code">
                  {job.data.result.exit_code === null ? (
                    <span className="text-amber-400">Unknown (not proven by the daemon)</span>
                  ) : (
                    job.data.result.exit_code
                  )}
                </DetailField>
                <DetailField label="Result started">
                  {job.data.result.started_at
                    ? formatDate(job.data.result.started_at)
                    : 'Not recorded'}
                </DetailField>
                <DetailField label="Result finished">
                  {job.data.result.finished_at
                    ? formatDate(job.data.result.finished_at)
                    : 'Not recorded'}
                </DetailField>
                <DetailField label="Billing">
                  {job.data.billing.mode === 'zero_cost'
                    ? 'Zero cost; no charge recorded'
                    : `${job.data.billing.charged.toLocaleString(undefined, { maximumFractionDigits: 2 })} NUKE charged`}
                </DetailField>
                <DetailField label="Execution proof">
                  {jobProofLabel(job.data.result.proof)}
                </DetailField>
              </dl>
            ) : (
              <p className="mt-3 flex items-start gap-2 text-sm text-muted-foreground">
                <ScrollText className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                No execution result has been recorded. Active jobs update automatically; terminal
                jobs without a result may need operator review.
              </p>
            )}
          </section>

          <JobLogsPanel jobId={job.data.id} summary={job.data.logs} />

          <p className="flex items-start gap-2 text-[11px] leading-relaxed text-muted-foreground">
            <CopyIcon className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
            Copy controls always use the full identifier or value returned by the server. Times are
            shown in your selected timezone.
          </p>
        </div>
      )}

      {detailEnabled && !job.data && !job.isPending && !job.isError && <UnavailableJob />}

      {dialog}
    </ResourcePageLayout>
  )
}
