// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { AlertTriangle, Cpu, HardDrive, Info, MemoryStick, Play, Terminal, Zap } from 'lucide-react'
import { ApiError } from '../../lib/api'
import {
  createJobIdempotencyKey,
  formatJobCredits,
  isJobFormField,
  jobErrorMessage,
  jobErrorField,
  jobMaximumCost,
  jobRequestSignature,
  parseJobArgs,
  validateJobArgv,
} from '../../lib/batch-job'
import { formatBytes, formatDuration, parseMemoryString } from '../../lib/utils'
import { usePlans } from '../../hooks/use-plans'
import { useEligibleJobRevisions, useCreateJob } from '../../hooks/use-jobs'
import { useVolumes } from '../../hooks/use-volumes'
import { PERMISSIONS, useAuthStore } from '../../stores/auth-store'
import { useToastStore } from '../../stores/toast-store'
import type {
  CreateJobRequest,
  EligibleJobRevision,
  JobCapabilities,
  JobFormField,
} from '../../types/batch-job'
import type { Plan } from '../../types/api'
import type { Volume } from '../../hooks/use-volumes'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select, SelectItem } from '../ui/select'
import { Textarea } from '../ui/textarea'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog'

interface JobFormState {
  name: string
  revisionId: string
  planId: string
  volumeId: string
  executable: string
  argsText: string
  runtimeSeconds: string
}

function emptyForm(capabilities: JobCapabilities): JobFormState {
  return {
    name: '',
    revisionId: '',
    planId: '',
    volumeId: '',
    executable: '',
    argsText: '',
    runtimeSeconds: String(capabilities.limits.default_runtime_seconds),
  }
}

function FieldMessage({ id, message }: { id: string; message?: string }) {
  if (!message) return null
  return (
    <p id={id} role="alert" className="text-xs text-destructive">
      {message}
    </p>
  )
}

function eligiblePlans(plans: Plan[], capabilities: JobCapabilities) {
  return plans.filter(
    (plan) =>
      plan.is_active &&
      plan.gpu_limit === 0 &&
      (capabilities.billing_mode !== 'zero_cost' || plan.cost_per_hour === 0)
  )
}

function eligibleVolumes(volumes: Volume[], ownerId: string | undefined) {
  return volumes.filter(
    (volume) =>
      volume.visibility === 'private' && volume.owner_id === ownerId && volume.status === 'active'
  )
}

function revisionLabel(revision: EligibleJobRevision) {
  return revision.display_label || `${revision.environment_name} (${revision.revision_id})`
}

export function NewJobDialog({
  open,
  onOpenChange,
  capabilities,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  capabilities: JobCapabilities
}) {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const ownerId = user?.id
  const canWrite = useAuthStore((state) => state.hasPermission(PERMISSIONS.JOBS_WRITE_OWN))
  const titleId = useId()
  const descriptionId = useId()
  const contentRef = useRef<HTMLDivElement>(null)

  const revisions = useEligibleJobRevisions(capabilities.enabled && capabilities.can_submit)
  const plansQuery = usePlans({ is_active: true, limit: 100 })
  const volumesQuery = useVolumes()
  const createJob = useCreateJob()

  const plans = eligiblePlans(plansQuery.data?.data ?? [], capabilities)
  const volumes = eligibleVolumes(volumesQuery.data ?? [], ownerId)
  const revisionsAvailable = (revisions.data?.items ?? []).filter(
    (revision) => revision.supports_jobs && !revision.reason_code
  )
  const savedPlanId =
    typeof user?.preferences?.default_plan === 'string' ? user.preferences.default_plan : ''
  const savedEnvironmentId =
    typeof user?.preferences?.default_environment === 'string'
      ? user.preferences.default_environment
      : ''
  const savedRevisions = revisionsAvailable.filter(
    (revision) => revision.environment_id === savedEnvironmentId
  )
  const defaultRevisionId =
    savedRevisions.length === 1
      ? savedRevisions[0].revision_id
      : revisionsAvailable.length === 1
        ? revisionsAvailable[0].revision_id
        : ''
  const defaultPlanId = plans.some((plan) => plan.id === savedPlanId)
    ? savedPlanId
    : plans.length === 1
      ? plans[0].id
      : ''
  const [form, setForm] = useState<JobFormState>(() => emptyForm(capabilities))
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<JobFormField, string>>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const keyRef = useRef<{ key: string | null; signature: string | null }>({
    key: null,
    signature: null,
  })
  const effectiveRevisionId = form.revisionId || defaultRevisionId
  const effectivePlanId = form.planId || defaultPlanId
  const selectedPlan = plans.find((plan) => plan.id === effectivePlanId)
  const selectedVolume = volumes.find((volume) => volume.id === form.volumeId)
  const selectedRevision = revisionsAvailable.find(
    (revision) => revision.revision_id === effectiveRevisionId
  )
  const runtimeSeconds = Number(form.runtimeSeconds)
  const maximumCost =
    selectedPlan && Number.isFinite(runtimeSeconds)
      ? jobMaximumCost(selectedPlan.cost_per_hour, runtimeSeconds, capabilities.billing_mode)
      : 0
  const submissionDisabled = !capabilities.can_submit || !canWrite

  useEffect(() => {
    if (!open) return
    const previous = document.activeElement
    const frame = requestAnimationFrame(() => contentRef.current?.focus())
    return () => {
      cancelAnimationFrame(frame)
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus()
    }
  }, [open])

  const update = <K extends keyof JobFormState>(key: K, value: JobFormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }))
    const field =
      key === 'revisionId'
        ? 'revision_id'
        : key === 'planId'
          ? 'plan_id'
          : key === 'volumeId'
            ? 'volume_id'
            : key === 'runtimeSeconds'
              ? 'max_runtime_seconds'
              : key === 'executable' || key === 'argsText'
                ? 'argv'
                : key === 'name'
                  ? 'name'
                  : null
    if (!field) return
    setFieldErrors((current) => {
      if (!current[field]) return current
      const next = { ...current }
      delete next[field]
      return next
    })
  }

  const validate = (): CreateJobRequest | null => {
    const errors: Partial<Record<JobFormField, string>> = {}
    const name = form.name.trim()
    if (!name) errors.name = 'Enter a name for this job.'
    if (!selectedRevision) errors.revision_id = 'Select an approved environment revision.'
    if (!selectedPlan) {
      errors.plan_id =
        capabilities.billing_mode === 'zero_cost'
          ? 'Select an available zero-cost plan.'
          : 'Select an available plan.'
    }
    if (!selectedVolume) errors.volume_id = 'Select an owned private volume.'
    if (!form.executable.trim()) {
      errors.argv = 'Enter the executable to run.'
    } else if (form.executable.includes('\n') || form.executable.includes('\r')) {
      errors.argv = 'The executable must be one argument.'
    }

    const argv = [form.executable, ...parseJobArgs(form.argsText)]
    if (!errors.argv) {
      const argvError = validateJobArgv(argv, capabilities.limits)
      if (argvError) errors.argv = argvError
    }

    if (!Number.isInteger(runtimeSeconds) || runtimeSeconds <= 0) {
      errors.max_runtime_seconds = 'Enter a whole number of seconds.'
    } else if (runtimeSeconds > capabilities.limits.max_runtime_seconds) {
      errors.max_runtime_seconds = `Use at most ${formatDuration(
        capabilities.limits.max_runtime_seconds
      )}.`
    }

    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return null
    return {
      name,
      revision_id: effectiveRevisionId,
      plan_id: effectivePlanId,
      volume_id: form.volumeId,
      argv,
      max_runtime_seconds: runtimeSeconds,
    }
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submissionDisabled || createJob.isPending) return
    setFormError(null)
    const request = validate()
    if (!request) return

    const signature = jobRequestSignature(request)
    let idempotencyKey = keyRef.current.key
    if (!idempotencyKey || keyRef.current.signature !== signature) {
      idempotencyKey = createJobIdempotencyKey()
      keyRef.current = { key: idempotencyKey, signature }
    }

    createJob.mutate(
      { request, idempotencyKey },
      {
        onSuccess: (job) => {
          if (useAuthStore.getState().user?.id !== ownerId) return
          useToastStore.getState().addToast({
            type: job.replayed ? 'info' : 'success',
            title: job.replayed ? 'Existing job opened' : 'Job submitted',
            message: job.name,
          })
          onOpenChange(false)
          void navigate({ to: '/jobs/$jobId', params: { jobId: job.id } })
        },
        onError: (error) => {
          if (useAuthStore.getState().user?.id !== ownerId) return
          const apiError = error instanceof ApiError ? error : null
          const code = apiError?.code
          const reportedField = apiError?.field
          const field = isJobFormField(reportedField) ? reportedField : jobErrorField(code)
          const message = code
            ? jobErrorMessage(code, error.message)
            : error.message || 'The job could not be submitted. Try again.'
          if (field) {
            setFieldErrors((current) => ({ ...current, [field]: message }))
          } else {
            setFormError(message)
          }
          if (code === 'idempotency_conflict') {
            // This request identity can no longer be reused; the draft stays editable.
            keyRef.current = { key: null, signature: null }
          }
        },
      }
    )
  }

  const nameErrorId = 'job-name-error'
  const argvErrorId = 'job-argv-error'
  const runtimeErrorId = 'job-runtime-error'

  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="lg">
      <DialogContent
        ref={contentRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        className="flex min-h-full flex-col"
        onKeyDown={(event) => {
          if (event.key !== 'Tab') return
          const controls = contentRef.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]'
          )
          const first = controls?.[0]
          const last = controls?.[controls.length - 1]
          if (!first || !last) {
            event.preventDefault()
            return
          }
          if (
            event.shiftKey &&
            (document.activeElement === first || document.activeElement === contentRef.current)
          ) {
            event.preventDefault()
            last.focus()
          } else if (
            !event.shiftKey &&
            (document.activeElement === last || document.activeElement === contentRef.current)
          ) {
            event.preventDefault()
            first.focus()
          }
        }}
      >
        <DialogHeader>
          <DialogTitle id={titleId} className="flex items-center gap-2">
            <Terminal className="h-4 w-4 text-primary" aria-hidden="true" />
            New job
          </DialogTitle>
          <DialogDescription id={descriptionId}>
            Run one noninteractive command in an approved environment using an owned private volume.
            The backend rechecks every choice before queueing.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="mt-5 flex flex-1 flex-col gap-5" noValidate>
          {submissionDisabled && (
            <div
              role="status"
              className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-muted-foreground"
            >
              <AlertTriangle
                className="mt-0.5 h-4 w-4 shrink-0 text-amber-400"
                aria-hidden="true"
              />
              <span>
                {capabilities.reason_code
                  ? jobErrorMessage(capabilities.reason_code, 'Job submission is unavailable.')
                  : !canWrite
                    ? 'You do not have permission to submit jobs.'
                    : 'Job submission is currently disabled.'}{' '}
                Authorized history remains available.
              </span>
            </div>
          )}

          {formError && (
            <div
              role="alert"
              className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive"
            >
              {formError}
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="job-name">Job name</Label>
            <Input
              id="job-name"
              data-testid="job-name"
              value={form.name}
              maxLength={120}
              autoComplete="off"
              placeholder="Checksum run"
              aria-invalid={!!fieldErrors.name}
              aria-describedby={fieldErrors.name ? nameErrorId : undefined}
              onChange={(event) => update('name', event.target.value)}
            />
            <FieldMessage id={nameErrorId} message={fieldErrors.name} />
          </div>

          <div className="space-y-1.5">
            <Label>Environment revision</Label>
            <Select
              value={effectiveRevisionId}
              onChange={(value) => update('revisionId', value)}
              placeholder={
                revisions.isPending ? 'Loading approved environments…' : 'Select a revision'
              }
              disabled={revisions.isPending || revisions.isError || revisionsAvailable.length === 0}
              data-testid="job-revision"
            >
              {revisionsAvailable.map((revision) => (
                <SelectItem
                  key={revision.revision_id}
                  value={revision.revision_id}
                  data-testid={`job-revision-${revision.revision_id}`}
                >
                  {revisionLabel(revision)}
                </SelectItem>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              Only approved revisions that support single-run jobs are listed. The selected image is
              fixed at submission.
            </p>
            {revisions.isError ? (
              <p role="status" className="text-xs text-destructive">
                Approved environments could not be loaded.{' '}
                <button
                  type="button"
                  className="underline underline-offset-2"
                  onClick={() => void revisions.refetch()}
                >
                  Retry
                </button>
              </p>
            ) : revisions.data && revisionsAvailable.length === 0 ? (
              <p role="status" className="text-xs text-amber-400">
                No approved environment revision is available for jobs. Contact an administrator.
              </p>
            ) : null}
            <FieldMessage id="job-revision-error" message={fieldErrors.revision_id} />
          </div>

          <div className="space-y-1.5">
            <Label>Resource plan</Label>
            <Select
              value={effectivePlanId}
              onChange={(value) => update('planId', value)}
              placeholder={plansQuery.isPending ? 'Loading plans…' : 'Select a plan'}
              disabled={plansQuery.isPending || plansQuery.isError || plans.length === 0}
              data-testid="job-plan"
            >
              {plans.map((plan) => (
                <SelectItem key={plan.id} value={plan.id} data-testid={`job-plan-${plan.id}`}>
                  {`${plan.name} · ${plan.cpu_limit} vCPU · ${formatBytes(
                    parseMemoryString(plan.memory_limit)
                  )} RAM`}
                </SelectItem>
              ))}
            </Select>
            {plansQuery.isError ? (
              <p role="status" className="text-xs text-destructive">
                Resource plans could not be loaded.{' '}
                <button
                  type="button"
                  className="underline underline-offset-2"
                  onClick={() => void plansQuery.refetch()}
                >
                  Retry
                </button>
              </p>
            ) : plansQuery.data && plans.length === 0 ? (
              <p role="status" className="text-xs text-amber-400">
                {capabilities.billing_mode === 'zero_cost'
                  ? 'No eligible zero-cost CPU plan is available. Contact an administrator.'
                  : 'No eligible CPU plan is available. Contact an administrator.'}
              </p>
            ) : null}
            <FieldMessage id="job-plan-error" message={fieldErrors.plan_id} />
          </div>

          <div className="space-y-1.5">
            <Label>Private work volume</Label>
            <Select
              value={form.volumeId}
              onChange={(value) => update('volumeId', value)}
              placeholder={volumesQuery.isPending ? 'Loading volumes…' : 'Select a private volume'}
              disabled={volumesQuery.isPending || volumesQuery.isError || volumes.length === 0}
              data-testid="job-volume"
            >
              {volumes.map((volume) => (
                <SelectItem
                  key={volume.id}
                  value={volume.id}
                  data-testid={`job-volume-${volume.id}`}
                >
                  {`${volume.display_name} · ${formatBytes(volume.size_bytes)}`}
                </SelectItem>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">
              The volume is mounted read/write at <code className="font-mono">/work</code> for the
              exclusive duration of the job. Inputs must already be present.
            </p>
            {volumesQuery.isError ? (
              <p role="status" className="text-xs text-destructive">
                Volumes could not be loaded.{' '}
                <button
                  type="button"
                  className="underline underline-offset-2"
                  onClick={() => void volumesQuery.refetch()}
                >
                  Retry
                </button>
              </p>
            ) : volumesQuery.data && volumes.length === 0 ? (
              <p role="status" className="text-xs text-amber-400">
                No owned private volume is available. Create an active private volume first.
              </p>
            ) : null}
            <FieldMessage id="job-volume-error" message={fieldErrors.volume_id} />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="job-executable">Executable</Label>
            <Input
              id="job-executable"
              data-testid="job-executable"
              value={form.executable}
              autoComplete="off"
              spellCheck={false}
              placeholder="python"
              className="font-mono"
              aria-invalid={!!fieldErrors.argv}
              aria-describedby={fieldErrors.argv ? argvErrorId : undefined}
              onChange={(event) => update('executable', event.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              One executable name or path. It is passed to the runtime literally; no shell is
              involved.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="job-args">Arguments</Label>
            <Textarea
              id="job-args"
              data-testid="job-args"
              value={form.argsText}
              autoResize={false}
              spellCheck={false}
              rows={4}
              placeholder={'/work/input.py\n--checksum'}
              className="min-h-24 font-mono text-xs"
              aria-invalid={!!fieldErrors.argv}
              aria-describedby={fieldErrors.argv ? argvErrorId : 'job-args-help'}
              onChange={(event) => update('argsText', event.target.value)}
            />
            <p id="job-args-help" className="text-xs text-muted-foreground">
              One argument per line. Quoting, pipes, globs and variable expansion are not parsed.
            </p>
            <FieldMessage id={argvErrorId} message={fieldErrors.argv} />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="job-runtime">Maximum runtime (seconds)</Label>
            <Input
              id="job-runtime"
              data-testid="job-runtime"
              type="number"
              min={1}
              step={1}
              max={capabilities.limits.max_runtime_seconds}
              value={form.runtimeSeconds}
              aria-invalid={!!fieldErrors.max_runtime_seconds}
              aria-describedby={
                fieldErrors.max_runtime_seconds ? runtimeErrorId : 'job-runtime-help'
              }
              onChange={(event) => update('runtimeSeconds', event.target.value)}
            />
            <p id="job-runtime-help" className="text-xs text-muted-foreground">
              Default {formatDuration(capabilities.limits.default_runtime_seconds)}; maximum{' '}
              {formatDuration(capabilities.limits.max_runtime_seconds)}. The deadline starts when
              the runtime is observed running.
            </p>
            <FieldMessage id={runtimeErrorId} message={fieldErrors.max_runtime_seconds} />
          </div>

          <div className="rounded-xl border border-border/50 bg-surface/50 p-4">
            <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <Info className="h-3.5 w-3.5" aria-hidden="true" />
              Execution summary
            </h3>
            <dl className="mt-3 grid grid-cols-1 gap-3 text-xs sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Working directory</dt>
                <dd className="mt-0.5 font-mono text-foreground">/work</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Output volume</dt>
                <dd className="mt-0.5 break-words text-foreground">
                  {selectedVolume?.display_name ?? 'Select a volume'}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Requested plan</dt>
                <dd className="mt-0.5 break-words text-foreground">
                  {selectedPlan?.name ?? 'Select a plan'}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {capabilities.billing_mode === 'paid' ? 'Maximum hold' : 'Maximum cost'}
                </dt>
                <dd
                  className="mt-0.5 font-medium text-foreground"
                  data-testid={
                    capabilities.billing_mode === 'paid' ? 'job-maximum-hold' : undefined
                  }
                >
                  {capabilities.billing_mode === 'zero_cost'
                    ? 'Zero cost'
                    : selectedPlan
                      ? `${formatJobCredits(maximumCost)} NUKE`
                      : 'Select a plan'}
                </dd>
                {capabilities.billing_mode === 'paid' && selectedPlan && (
                  <p
                    data-testid="job-hold-refund-note"
                    className="mt-1 text-[11px] leading-relaxed text-muted-foreground"
                  >
                    Held until the job finishes. Unused credits are refunded after the terminal
                    result.
                  </p>
                )}
              </div>
            </dl>
            {selectedPlan && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                <span className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-surface/60 px-2 py-1 text-[11px] text-muted-foreground">
                  <Cpu className="h-3 w-3" aria-hidden="true" />
                  {selectedPlan.cpu_limit} vCPU
                </span>
                <span className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-surface/60 px-2 py-1 text-[11px] text-muted-foreground">
                  <MemoryStick className="h-3 w-3" aria-hidden="true" />
                  {selectedPlan.memory_limit} RAM
                </span>
                <span className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-surface/60 px-2 py-1 text-[11px] text-muted-foreground">
                  <HardDrive className="h-3 w-3" aria-hidden="true" />
                  {selectedPlan.disk_limit} disk
                </span>
                <span className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-surface/60 px-2 py-1 text-[11px] text-muted-foreground">
                  <Zap className="h-3 w-3" aria-hidden="true" />
                  {selectedPlan.gpu_limit} GPU
                </span>
              </div>
            )}
            <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">
              The environment is offline. Write outputs under{' '}
              <code className="font-mono">/work</code> so they remain on the selected volume after
              the runtime is removed.
            </p>
          </div>

          <DialogFooter className="mt-auto">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              data-testid="job-submit"
              loading={createJob.isPending}
              disabled={submissionDisabled}
            >
              <Play className="h-4 w-4" aria-hidden="true" />
              Submit job
            </Button>
          </DialogFooter>
        </form>
        <DialogClose onClick={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}
