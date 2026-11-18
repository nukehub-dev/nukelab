// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import {
  AlertTriangle,
  CheckCircle2,
  FileJson,
  HardDrive,
  Loader2,
  Plus,
  RotateCcw,
  Server,
  ShieldAlert,
  ShieldCheck,
  Upload,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { ApiError } from '../../lib/api'
import {
  MANIFEST_MAX_BYTES,
  blankVolumeChoices,
  buildExplicitBindings,
  parseManifestInput,
  provenanceErrorMessage,
  type VolumeChoice,
} from '../../lib/server-provenance'
import { isQueuedServer } from '../../lib/server-queue'
import {
  useRecreateServer,
  useRecreationCatalog,
  useValidateRecreation,
} from '../../hooks/use-server-provenance'
import { useAuthStore } from '../../stores/auth-store'
import { useToastStore } from '../../stores/toast-store'
import type {
  EnvironmentManifest,
  RecreationPreview,
  RecreationSource,
} from '../../types/server-provenance'
import { Button } from '../ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select, SelectItem } from '../ui/select'
import { Textarea } from '../ui/textarea'
import { cn, formatBytes, formatPlanResource, parseMemoryString } from '../../lib/utils'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  sourceLaunchId?: string
}

function StepHeader({
  id,
  step,
  title,
  description,
  icon: Icon,
  complete = false,
}: {
  id: string
  step: number
  title: string
  description: string
  icon: LucideIcon
  complete?: boolean
}) {
  return (
    <div className="flex items-start gap-3">
      <span
        className={cn(
          'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold',
          complete
            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
            : 'border-border/60 bg-muted/50 text-muted-foreground'
        )}
      >
        {complete ? <CheckCircle2 className="h-3.5 w-3.5" /> : step}
      </span>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
          <h3 id={id} className="text-sm font-semibold">
            {title}
          </h3>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}

function PortabilityBadge({ manifest }: { manifest: EnvironmentManifest }) {
  const verified = manifest.portability === 'registry_verified'
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider',
        verified
          ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
          : 'border-amber-500/20 bg-amber-500/10 text-amber-400'
      )}
    >
      {verified ? <ShieldCheck className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}
      {verified ? 'Registry verified' : 'Local-only artifacts'}
    </span>
  )
}

export function RecreateServerDialog({ open, onOpenChange, sourceLaunchId }: Props) {
  // Remounting discards previous-account fields and in-flight form state.
  const ownerId = useAuthStore((state) => state.user?.id)
  return open && ownerId ? (
    <RecreationForm
      key={`${ownerId}:${sourceLaunchId ?? 'import'}`}
      onOpenChange={onOpenChange}
      sourceLaunchId={sourceLaunchId}
      ownerId={ownerId}
    />
  ) : null
}

function RecreationForm({
  onOpenChange,
  sourceLaunchId,
  ownerId,
}: Omit<Props, 'open'> & { ownerId: string }) {
  const navigate = useNavigate()
  const catalog = useRecreationCatalog(true)
  const validate = useValidateRecreation()
  const recreate = useRecreateServer()
  const [raw, setRaw] = useState('')
  const [preview, setPreview] = useState<RecreationPreview | null>(null)
  const [source, setSource] = useState<RecreationSource | null>(null)
  const [choices, setChoices] = useState<VolumeChoice[]>([])
  const [name, setName] = useState('')
  const [planId, setPlanId] = useState('')
  const [failure, setFailure] = useState<unknown>(null)
  const [validating, setValidating] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [fileName, setFileName] = useState<string | null>(null)
  const requestVersion = useRef(0)
  const mounted = useRef(true)
  const submission = useRef(false)
  const dialogRef = useRef<HTMLDivElement>(null)
  const currentAccount = () => mounted.current && useAuthStore.getState().user?.id === ownerId
  const plans = catalog.plans.data ?? []
  const volumes = catalog.volumes.data ?? []
  const plan = plans.find((item) => item.id === planId)
  const busy = validating || recreate.isPending
  const byteCount = new TextEncoder().encode(raw).byteLength
  const existingRequestId =
    failure instanceof ApiError && failure.code === 'request_already_exists'
      ? (failure.queueId ?? null)
      : null
  const canRetryValidation = !!sourceLaunchId && !preview && !busy

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    return () => {
      if (previous?.isConnected) previous.focus()
    }
  }, [])

  const check = async (candidate: RecreationSource) => {
    if (validating || recreate.isPending) return
    const version = ++requestVersion.current
    setValidating(true)
    setFailure(null)
    try {
      const result = await validate.mutateAsync(candidate)
      if (!currentAccount() || version !== requestVersion.current) return
      setSource(candidate)
      setPreview(result)
      setChoices(blankVolumeChoices(result.volume_requirements))
    } catch (error) {
      if (currentAccount() && version === requestVersion.current) setFailure(error)
    } finally {
      if (currentAccount() && version === requestVersion.current) setValidating(false)
    }
  }

  const initialized = useRef(false)
  useEffect(() => {
    if (sourceLaunchId && !initialized.current) {
      initialized.current = true
      void check({ source_launch_id: sourceLaunchId })
    }
    // A source is validated once when this keyed form opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceLaunchId])

  const updateInput = (value: string) => {
    requestVersion.current++
    setRaw(value)
    setValidating(false)
    setPreview(null)
    setSource(null)
    setChoices([])
    setFailure(null)
    setFileName(null)
  }

  const loadFile = async (file: File | undefined) => {
    if (!file) return
    if (file.size > MANIFEST_MAX_BYTES) {
      setFailure(new Error('Environment files must be 64 KiB or smaller.'))
      return
    }
    const version = ++requestVersion.current
    try {
      const text = await file.text()
      if (currentAccount() && version === requestVersion.current) {
        updateInput(text)
        setFileName(file.name)
      }
    } catch {
      if (currentAccount()) setFailure(new Error('This environment file could not be read.'))
    }
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (submission.current || busy || !preview || !source || !currentAccount()) return
    setFailure(null)
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(name)) {
      setFailure(
        new Error(
          'Use a new name with letters, numbers, underscores or hyphens (up to 64 characters).'
        )
      )
      return
    }
    if (!plan) {
      setFailure(new Error('Choose a currently available plan.'))
      return
    }
    try {
      const volume_mounts = buildExplicitBindings(preview.volume_requirements, choices, volumes)
      const total = volume_mounts.reduce(
        (sum, mount) =>
          sum +
          (mount.max_size_bytes ??
            volumes.find((item) => item.id === mount.volume_id)?.max_size_bytes ??
            volumes.find((item) => item.id === mount.volume_id)?.size_bytes ??
            0),
        0
      )
      if (total > parseMemoryString(plan.disk_limit))
        throw new Error('The selected volume capacities exceed this plan’s disk limit.')
      submission.current = true
      const result = await recreate.mutateAsync({ ...source, name, plan_id: planId, volume_mounts })
      if (!currentAccount()) return
      onOpenChange(false)
      useToastStore.getState().addToast({
        type: isQueuedServer(result) ? 'info' : 'success',
        title: isQueuedServer(result) ? 'Request queued' : 'Environment recreated',
        message: isQueuedServer(result) ? result.message : `${result.name} is ready.`,
        duration: 8000,
      })
      if (isQueuedServer(result))
        void navigate({ to: '/servers', search: { tab: 'queue', request: result.queue_id } })
      else void navigate({ to: '/servers/$serverId', params: { serverId: result.id } })
    } catch (error) {
      if (currentAccount()) setFailure(error)
    } finally {
      submission.current = false
    }
  }

  return (
    <Dialog open onOpenChange={onOpenChange} size="xl">
      <DialogContent
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="recreate-dialog-title"
        tabIndex={-1}
        className="flex min-h-full flex-col space-y-5"
      >
        <DialogHeader>
          <div className="flex items-start gap-3">
            <div className="shrink-0 rounded-xl bg-primary/10 p-2.5 text-primary ring-1 ring-primary/15">
              {sourceLaunchId ? (
                <RotateCcw className="h-5 w-5" />
              ) : (
                <FileJson className="h-5 w-5" />
              )}
            </div>
            <div className="min-w-0 space-y-1.5">
              <DialogTitle id="recreate-dialog-title">
                {sourceLaunchId ? 'Recreate environment' : 'Import environment'}
              </DialogTitle>
              <DialogDescription>
                Create a new server from an approved captured environment. Data volumes are selected
                separately; existing files are never copied by the environment file.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <form className="flex flex-1 flex-col space-y-5" onSubmit={submit} noValidate>
          {!sourceLaunchId && (
            <section
              aria-labelledby="recreate-step-import"
              className="space-y-4 rounded-2xl border border-border/50 bg-surface/40 p-4"
            >
              <StepHeader
                id="recreate-step-import"
                step={1}
                title="Import"
                description="Upload an exported file or paste its JSON to check it against an approved revision."
                icon={FileJson}
              />
              <div
                className={cn(
                  'rounded-xl border border-dashed p-4 transition-colors',
                  dragging
                    ? 'border-primary/50 bg-primary/5'
                    : 'border-border/70 bg-background/30 hover:border-primary/40 hover:bg-primary/[0.03]'
                )}
                onDragOver={(event) => {
                  event.preventDefault()
                  if (!busy) setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault()
                  setDragging(false)
                  if (!busy) void loadFile(event.dataTransfer.files?.[0])
                }}
              >
                <input
                  id="environment-file"
                  aria-label="Environment JSON file"
                  type="file"
                  accept="application/json,.json"
                  disabled={busy}
                  className="sr-only"
                  onChange={(event) => {
                    void loadFile(event.target.files?.[0])
                    event.target.value = ''
                  }}
                />
                <label
                  htmlFor="environment-file"
                  className={cn(
                    'group flex cursor-pointer flex-col items-center gap-3 text-center sm:flex-row sm:text-left',
                    busy && 'pointer-events-none opacity-60'
                  )}
                >
                  <span className="shrink-0 rounded-xl bg-primary/10 p-2.5 text-primary transition-transform group-hover:scale-105">
                    <Upload className="h-4 w-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">Drop an environment file here</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      JSON exported from a verified launch · up to 64 KiB
                    </span>
                  </span>
                  <span className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border/60 bg-background/60 px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors group-hover:text-foreground">
                    <FileJson className="h-3.5 w-3.5" />
                    Browse
                  </span>
                </label>
              </div>
              {fileName && (
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <FileJson className="h-3.5 w-3.5 shrink-0 text-primary" />
                  Loaded <span className="font-mono">{fileName}</span>
                </p>
              )}

              <div className="flex items-center gap-3">
                <span className="h-px flex-1 bg-border/60" />
                <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  or paste
                </span>
                <span className="h-px flex-1 bg-border/60" />
              </div>

              <div className="space-y-1.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Label htmlFor="environment-json">Or paste exported JSON</Label>
                  <span
                    className={cn(
                      'text-[11px] tabular-nums text-muted-foreground',
                      byteCount > MANIFEST_MAX_BYTES && 'text-destructive'
                    )}
                  >
                    {byteCount.toLocaleString()} / {MANIFEST_MAX_BYTES.toLocaleString()} bytes
                  </span>
                </div>
                <Textarea
                  id="environment-json"
                  data-testid="environment-import-json"
                  value={raw}
                  onChange={(event) => updateInput(event.target.value)}
                  disabled={recreate.isPending}
                  autoResize={false}
                  className="h-28 min-h-28 resize-none font-mono text-xs leading-relaxed"
                />
                <p className="text-[11px] text-muted-foreground">
                  Maximum 64 KiB. Imported files cannot grant access to unapproved environments or
                  other users’ data.
                </p>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[11px] text-muted-foreground">
                  Validation checks the approved revision before any volume is chosen.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy || !raw.trim()}
                  onClick={() => {
                    try {
                      void check({ manifest: parseManifestInput(raw) })
                    } catch (error) {
                      setFailure(error)
                    }
                  }}
                >
                  <ShieldCheck className="h-3.5 w-3.5" />
                  Validate environment
                </Button>
              </div>
            </section>
          )}

          {failure != null && (
            <div
              role="alert"
              className="rounded-xl border border-destructive/30 bg-destructive/10 p-4"
            >
              <div className="flex items-start gap-3">
                <div className="shrink-0 rounded-lg bg-destructive/15 p-2 text-destructive">
                  <AlertTriangle className="h-4 w-4" />
                </div>
                <div className="min-w-0 space-y-2.5">
                  <p className="text-sm">{provenanceErrorMessage(failure)}</p>
                  {(existingRequestId || canRetryValidation) && (
                    <div className="flex flex-wrap gap-2">
                      {existingRequestId && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            onOpenChange(false)
                            void navigate({
                              to: '/servers',
                              search: { tab: 'queue', request: existingRequestId },
                            })
                          }}
                        >
                          View existing request
                        </Button>
                      )}
                      {canRetryValidation && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            void check({ source_launch_id: sourceLaunchId })
                          }}
                        >
                          Retry validation
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          <div className={cn('grid gap-5', preview && 'lg:grid-cols-2 lg:items-start')}>
            <section
              aria-labelledby="recreate-step-review"
              className="space-y-4 rounded-2xl border border-border/50 bg-surface/40 p-4"
            >
              <StepHeader
                id="recreate-step-review"
                step={2}
                title="Review"
                description="Confirm the approved identity and the data mounts this environment expects."
                icon={ShieldCheck}
                complete={!!preview}
              />

              {validating ? (
                <div
                  role="status"
                  className="flex items-center gap-3 rounded-xl border border-border/60 bg-surface/50 p-4"
                >
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
                  <div>
                    <p className="text-sm font-medium">Checking approved environment…</p>
                    <p className="text-xs text-muted-foreground">
                      Verifying the captured revision, identities, and data mounts.
                    </p>
                  </div>
                </div>
              ) : preview ? (
                <div className="space-y-3 rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-3.5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-[10px] font-medium uppercase tracking-wider text-emerald-400/90">
                        Validated environment
                      </p>
                      <h4 className="mt-0.5 text-sm font-semibold break-words">
                        {preview.environment_label}
                      </h4>
                    </div>
                    <PortabilityBadge manifest={preview.manifest} />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Environment variable values are excluded from the file. Approved configuration
                    and current permissions remain authoritative.
                  </p>
                  <div className="space-y-1.5">
                    <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      Key limitations
                    </p>
                    <ul className="space-y-1.5">
                      {preview.manifest.limitations.map((limitation) => (
                        <li key={limitation} className="flex gap-2 text-xs text-muted-foreground">
                          <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50" />
                          <span>{limitation}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="flex items-start gap-2 rounded-lg bg-emerald-500/10 px-2.5 py-2 text-xs text-emerald-400">
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span>Validated for this account. Final approval still applies.</span>
                  </div>
                </div>
              ) : (
                <div
                  className={cn(
                    'flex items-center gap-3 rounded-xl border border-dashed p-4',
                    failure != null
                      ? 'border-destructive/30 bg-destructive/5'
                      : 'border-border/60 bg-background/30'
                  )}
                >
                  <div
                    className={cn(
                      'shrink-0 rounded-lg p-2',
                      failure != null
                        ? 'bg-destructive/10 text-destructive'
                        : 'bg-muted text-muted-foreground'
                    )}
                  >
                    {failure != null ? (
                      <ShieldAlert className="h-4 w-4" />
                    ) : (
                      <ShieldCheck className="h-4 w-4" />
                    )}
                  </div>
                  <div>
                    <p className="text-sm font-medium">
                      {failure != null ? 'Validation not complete' : 'Awaiting validation'}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {failure != null
                        ? 'Review the message above, then validate the environment again.'
                        : 'Validate the environment to review its approved identity and data mounts.'}
                    </p>
                  </div>
                </div>
              )}
            </section>

            {preview && (
              <section
                aria-labelledby="recreate-step-configure"
                className="space-y-4 rounded-2xl border border-border/50 bg-surface/40 p-4"
              >
                <StepHeader
                  id="recreate-step-configure"
                  step={3}
                  title="Configure"
                  description="Name the server, choose a current plan, and bind every data mount explicitly."
                  icon={Server}
                />

                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="recreate-name">New server name</Label>
                    <Input
                      id="recreate-name"
                      data-testid="recreate-name"
                      value={name}
                      onChange={(event) => setName(event.target.value)}
                      disabled={recreate.isPending}
                      autoComplete="off"
                      placeholder="e.g. analysis-replica"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Current plan</Label>
                    <Select
                      value={planId}
                      onChange={setPlanId}
                      disabled={recreate.isPending || catalog.plans.isPending}
                      data-testid="recreate-plan"
                      placeholder="Choose a current plan"
                    >
                      {plans.map((item) => (
                        <SelectItem
                          key={item.id}
                          value={item.id}
                          data-testid={`recreate-plan-${item.id}`}
                        >
                          {item.name} · {item.cpu_limit} CPU ·{' '}
                          {formatPlanResource(item.memory_limit)} RAM ·{' '}
                          {formatPlanResource(item.disk_limit)} disk
                        </SelectItem>
                      ))}
                    </Select>
                    <p className="text-[11px] text-muted-foreground">
                      {plan
                        ? `${plan.cpu_limit} CPU · ${formatPlanResource(plan.memory_limit)} RAM · ${formatPlanResource(plan.disk_limit)} disk`
                        : 'The source plan is not reused automatically; current limits and pricing apply.'}
                    </p>
                    {catalog.plans.isError && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          void catalog.plans.refetch()
                        }}
                      >
                        Retry plan choices
                      </Button>
                    )}
                  </div>
                </div>

                <div className="space-y-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                        Data volumes
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        No source volume is selected automatically.
                      </p>
                    </div>
                    <span className="inline-flex items-center gap-1 rounded-full border border-border/60 bg-muted/50 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                      <HardDrive className="h-3 w-3" />
                      {preview.volume_requirements.length} mount
                      {preview.volume_requirements.length === 1 ? '' : 's'}
                    </span>
                  </div>

                  {catalog.volumes.isError && (
                    <div
                      role="status"
                      className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 p-2.5 text-xs text-amber-400"
                    >
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      <span>
                        Existing volumes could not be loaded. Fresh volumes remain available.{' '}
                        <button
                          type="button"
                          className="underline underline-offset-2"
                          onClick={() => {
                            void catalog.volumes.refetch()
                          }}
                        >
                          Retry
                        </button>
                      </span>
                    </div>
                  )}

                  {preview.volume_requirements.map((requirement, index) => {
                    const selection = choices[index]?.selection ?? ''
                    const chosenVolume =
                      selection && selection !== 'fresh'
                        ? volumes.find((volume) => volume.id === selection)
                        : undefined
                    return (
                      <div
                        key={`${requirement.mount_path}:${index}`}
                        className="space-y-3 rounded-xl border border-border/50 bg-background/30 p-3"
                      >
                        <div className="flex items-start gap-2.5">
                          <div className="shrink-0 rounded-lg bg-chart-3/10 p-2 text-chart-3">
                            <HardDrive className="h-3.5 w-3.5" />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <p className="text-sm font-medium capitalize">
                                {requirement.purpose}
                              </p>
                              <span
                                className={cn(
                                  'rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider',
                                  requirement.mode === 'read_only'
                                    ? 'bg-amber-500/10 text-amber-400'
                                    : 'bg-emerald-500/10 text-emerald-400'
                                )}
                              >
                                {requirement.mode === 'read_only' ? 'Read only' : 'Read/write'}
                              </span>
                            </div>
                            <p className="font-mono text-xs break-all text-muted-foreground">
                              {requirement.mount_path}
                            </p>
                          </div>
                        </div>

                        <div className="space-y-1.5">
                          <Label>Volume for this mount</Label>
                          <Select
                            value={selection}
                            onChange={(value) =>
                              setChoices((current) =>
                                current.map((choice, choiceIndex) =>
                                  choiceIndex === index ? { ...choice, selection: value } : choice
                                )
                              )
                            }
                            disabled={recreate.isPending}
                            data-testid={`recreate-volume-${index}`}
                            placeholder="Choose a volume deliberately"
                          >
                            <SelectItem value="fresh">Create a fresh private volume</SelectItem>
                            {volumes.map((volume) => (
                              <SelectItem key={volume.id} value={volume.id}>
                                {volume.display_name} ·{' '}
                                {formatBytes(volume.max_size_bytes ?? volume.size_bytes)}
                              </SelectItem>
                            ))}
                          </Select>
                        </div>

                        {chosenVolume && (
                          <div className="flex items-center gap-2 rounded-lg border border-border/50 bg-surface/40 px-2.5 py-2 text-xs text-muted-foreground">
                            <HardDrive className="h-3.5 w-3.5 shrink-0" />
                            <span className="min-w-0 truncate">{chosenVolume.display_name}</span>
                            <span className="ml-auto shrink-0 font-mono">
                              {formatBytes(chosenVolume.max_size_bytes ?? chosenVolume.size_bytes)}
                            </span>
                            <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wider">
                              {chosenVolume.visibility}
                            </span>
                          </div>
                        )}

                        {selection === 'fresh' && (
                          <div className="space-y-1.5 rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-2.5">
                            <Label htmlFor={`fresh-volume-size-${index}`}>
                              Fresh volume size (GiB)
                            </Label>
                            <Input
                              id={`fresh-volume-size-${index}`}
                              data-testid={`recreate-volume-size-${index}`}
                              type="number"
                              min="0.001"
                              step="0.25"
                              value={choices[index].sizeGiB}
                              disabled={recreate.isPending}
                              onChange={(event) =>
                                setChoices((current) =>
                                  current.map((choice, choiceIndex) =>
                                    choiceIndex === index
                                      ? { ...choice, sizeGiB: event.target.value }
                                      : choice
                                  )
                                )
                              }
                            />
                            <p className="text-[11px] text-muted-foreground">
                              Creates a new empty private volume for this mount.
                            </p>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </section>
            )}
          </div>

          <DialogFooter className="mt-auto pt-4">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              data-testid="recreate-submit"
              disabled={!preview || busy}
              loading={recreate.isPending}
            >
              {!recreate.isPending && <Plus className="h-4 w-4" />}
              Create new server
            </Button>
          </DialogFooter>
        </form>
        <DialogClose onClick={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}
