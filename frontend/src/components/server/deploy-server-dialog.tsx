// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useEffect, useMemo, useRef } from 'react'
import { Link } from '@tanstack/react-router'
import { ApiError } from '../../lib/api'
import { HardDrive, Plus, X, AlertTriangle, ArrowRight, Info } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '../ui/dialog'
import { Input } from '../ui/input'
import { Button } from '../ui/button'
import { Select, SelectItem } from '../ui/select'
import { Label } from '../ui/label'
import { cn, formatBytes, formatPlanResource, parseMemoryString } from '../../lib/utils'
import {
  describeDeployCost,
  describeDeployVolume,
  resolveDeployDefaults,
  resolveDeployMountPath,
} from '../../lib/deploy-defaults'
import { PERMISSIONS, useAuthStore } from '../../stores/auth-store'
import type { Environment, Plan } from '../../types/api'
import type { Volume } from '../../hooks/use-volumes'

interface VolumeMountForm {
  volume_id: string
  mount_path: string
  mode: 'read_write' | 'read_only'
  max_size_gb: number
}

export interface DeployServerData {
  name: string
  plan_id: string
  environment_id: string
  volume_mounts?: Array<{
    volume_id: string
    mount_path: string
    mode: 'read_write' | 'read_only'
    max_size_bytes?: number
  }>
}

interface DeployServerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  plans: Plan[]
  environments: Environment[]
  volumes: Volume[]
  defaultUsername?: string
  defaultPlanId?: string
  defaultEnvironmentId?: string
  isPending: boolean
  error?: Error | null
  onViewQueued?: (queueId: string) => void
  onDeploy: (data: DeployServerData) => void
}

export function DeployServerDialog({
  open,
  onOpenChange,
  plans,
  environments,
  volumes,
  defaultUsername = 'user',
  defaultPlanId,
  defaultEnvironmentId,
  isPending,
  error,
  onDeploy,
  onViewQueued,
}: DeployServerDialogProps) {
  const [deployForm, setDeployForm] = useState({
    name: '',
    plan_id: '',
    environment_id: '',
  })
  const [volumeMounts, setVolumeMounts] = useState<VolumeMountForm[]>([
    { volume_id: '', mount_path: '', mode: 'read_write', max_size_gb: 10 },
  ])
  const [selectionTouched, setSelectionTouched] = useState({
    plan: false,
    environment: false,
  })
  const [visibleError, setVisibleError] = useState<string | null>(null)
  const canAccessAdmin = useAuthStore((state) => state.hasPermission(PERMISSIONS.ADMIN_ACCESS))

  // The dialog already receives the actor-scoped catalog it renders, so guide
  // from those records rather than re-filtering admin choices.
  const deployDefaults = useMemo(
    () =>
      resolveDeployDefaults({
        plans,
        environments,
        savedPlanId: defaultPlanId,
        savedEnvironmentId: defaultEnvironmentId,
      }),
    [plans, environments, defaultPlanId, defaultEnvironmentId]
  )

  const wasOpen = useRef(false)
  useEffect(() => {
    const opening = open && !wasOpen.current
    wasOpen.current = open
    if (opening) {
      const planId = deployDefaults.planId
      const envId = deployDefaults.environmentId
      queueMicrotask(() => {
        setDeployForm({ name: '', plan_id: planId, environment_id: envId })
        setSelectionTouched({ plan: false, environment: false })
        setVolumeMounts([{ volume_id: '', mount_path: '', mode: 'read_write', max_size_gb: 10 }])
        setVisibleError(null)
      })
    }
  }, [open, deployDefaults])

  // A deep link can open the dialog before the catalog queries settle. Fill a
  // safe default once it arrives, but only while the field is untouched and
  // empty so a user's explicit selection is never overwritten.
  useEffect(() => {
    if (!open) return
    if (!selectionTouched.plan && !deployForm.plan_id && deployDefaults.planId) {
      const planId = deployDefaults.planId
      queueMicrotask(() => {
        setDeployForm((current) => (current.plan_id ? current : { ...current, plan_id: planId }))
      })
    }
    if (
      !selectionTouched.environment &&
      !deployForm.environment_id &&
      deployDefaults.environmentId
    ) {
      const environmentId = deployDefaults.environmentId
      queueMicrotask(() => {
        setDeployForm((current) =>
          current.environment_id ? current : { ...current, environment_id: environmentId }
        )
      })
    }
  }, [open, selectionTouched, deployForm.plan_id, deployForm.environment_id, deployDefaults])

  useEffect(() => {
    if (error) {
      queueMicrotask(() => setVisibleError(error.message))
    }
  }, [error])

  const selectedPlan = plans.find((p) => p.id === deployForm.plan_id)
  const selectedEnvironment = environments.find((e) => e.id === deployForm.environment_id)
  const planDiskBytes = selectedPlan ? parseMemoryString(selectedPlan.disk_limit) : 0
  const missingPlans = plans.length === 0
  const missingEnvironments = environments.length === 0
  const prerequisitesMissing = missingPlans || missingEnvironments
  const planSelectionStale = Boolean(deployForm.plan_id) && !selectedPlan
  const environmentSelectionStale = Boolean(deployForm.environment_id) && !selectedEnvironment

  const staleSavedPlan = deployDefaults.savedPlanStale && !selectionTouched.plan
  const staleSavedEnvironment =
    deployDefaults.savedEnvironmentStale && !selectionTouched.environment
  const staleSavedFields = [
    staleSavedPlan ? 'plan' : null,
    staleSavedEnvironment ? 'environment' : null,
  ].filter((field): field is string => field !== null)
  const staleSavedMessage =
    staleSavedFields.length > 0
      ? `Your saved default ${staleSavedFields.join(' and ')} ${
          staleSavedFields.length === 1 ? 'is' : 'are'
        } no longer available. ${
          deployDefaults.plan || deployDefaults.environment
            ? 'The current recommended setup is preselected; review it before launching.'
            : 'Choose a current option before launching.'
        }`
      : null

  const totalAllocatedBytes = useMemo(() => {
    return volumeMounts.reduce((sum, mount) => {
      if (!mount.volume_id) {
        // New volume: use specified size
        return sum + mount.max_size_gb * 1024 * 1024 * 1024
      }
      // Existing volume: use its max_size_bytes or size_bytes
      const vol = volumes.find((v) => v.id === mount.volume_id)
      return sum + (vol?.max_size_bytes || vol?.size_bytes || 0)
    }, 0)
  }, [volumeMounts, volumes])

  const isOverCapacity = planDiskBytes > 0 && totalAllocatedBytes > planDiskBytes
  const capacityPercent =
    planDiskBytes > 0 ? Math.min(100, (totalAllocatedBytes / planDiskBytes) * 100) : 0
  const missingVolumeSelection = volumeMounts.some(
    (mount) => mount.volume_id && !volumes.some((volume) => volume.id === mount.volume_id)
  )

  const isValid = Boolean(
    deployForm.name.trim() &&
    selectedPlan &&
    selectedEnvironment &&
    !isOverCapacity &&
    !missingVolumeSelection
  )

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (isPending) return
    setVisibleError(null)

    if (!deployForm.name.trim()) {
      setVisibleError('Server name is required')
      return
    }
    if (!selectedPlan) {
      setVisibleError(
        planSelectionStale
          ? 'The selected plan is no longer available. Choose a plan from the current list.'
          : 'Please select a plan'
      )
      return
    }
    if (!selectedEnvironment) {
      setVisibleError(
        environmentSelectionStale
          ? 'The selected environment is no longer available. Choose an environment from the current list.'
          : 'Please select an environment'
      )
      return
    }
    if (missingVolumeSelection) {
      setVisibleError(
        'A selected volume is no longer available. Choose a current volume before launching.'
      )
      return
    }

    const mounts = volumeMounts.map((m, idx) => ({
      volume_id: m.volume_id,
      mount_path: resolveDeployMountPath(m.mount_path, idx, defaultUsername),
      mode: m.mode,
      max_size_bytes: !m.volume_id ? m.max_size_gb * 1024 * 1024 * 1024 : undefined,
    }))

    onDeploy({
      name: deployForm.name.trim(),
      plan_id: selectedPlan.id,
      environment_id: selectedEnvironment.id,
      volume_mounts: mounts.length > 0 ? mounts : undefined,
    })
  }

  const addVolumeMount = () => {
    setVolumeMounts((prev) => [
      ...prev,
      { volume_id: '', mount_path: '/data', mode: 'read_write', max_size_gb: 10 },
    ])
  }

  const removeVolumeMount = (index: number) => {
    setVolumeMounts((prev) => prev.filter((_, i) => i !== index))
  }

  const updateVolumeMount = (
    index: number,
    field: keyof VolumeMountForm,
    value: string | number
  ) => {
    setVolumeMounts((prev) => prev.map((m, i) => (i === index ? { ...m, [field]: value } : m)))
  }

  const handleCancel = () => {
    onOpenChange(false)
    setVolumeMounts([{ volume_id: '', mount_path: '', mode: 'read_write', max_size_gb: 10 }])
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Deploy New Server</DialogTitle>
          <DialogDescription>
            Review the starting resources, environment and storage, then launch your workspace.
          </DialogDescription>
        </DialogHeader>
        <form
          id="deploy-form"
          data-testid="deploy-form"
          onSubmit={handleSubmit}
          className="space-y-4 mt-4"
          noValidate
        >
          {prerequisitesMissing && (
            <div
              role="alert"
              data-testid="deploy-prerequisites"
              className="space-y-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4"
            >
              <div className="flex items-start gap-2">
                <AlertTriangle
                  className="mt-0.5 h-4 w-4 shrink-0 text-amber-400"
                  aria-hidden="true"
                />
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-amber-400">
                    Deployment isn't available yet
                  </p>
                  <ul className="list-disc space-y-0.5 pl-4 text-sm text-muted-foreground">
                    {missingPlans && <li>No active plans are available.</li>}
                    {missingEnvironments && <li>No active environments are available.</li>}
                  </ul>
                </div>
              </div>
              {canAccessAdmin ? (
                <div className="space-y-2 pl-6">
                  <p className="text-sm text-muted-foreground">
                    Publish a public environment and make a plan available to users, then try again.
                  </p>
                  <Link
                    to="/admin/setup"
                    className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                  >
                    Finish setup
                    <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </Link>
                </div>
              ) : (
                <p className="pl-6 text-sm text-muted-foreground">
                  Contact your NukeLab administrator or{' '}
                  <Link to="/support" className="font-medium text-primary hover:underline">
                    support
                  </Link>{' '}
                  to finish setting up deployment.
                </p>
              )}
            </div>
          )}
          {visibleError && (
            <div
              role="alert"
              className="flex items-start gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/20"
            >
              <AlertTriangle className="w-4 h-4 text-destructive flex-shrink-0 mt-0.5" />
              <div className="space-y-2">
                <p className="text-sm text-destructive">{visibleError}</p>
                {error instanceof ApiError &&
                  error.code === 'request_already_exists' &&
                  error.queueId &&
                  onViewQueued && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => onViewQueued(error.queueId!)}
                    >
                      View existing request
                    </Button>
                  )}
              </div>
            </div>
          )}
          {staleSavedMessage && (
            <div
              role="status"
              data-testid="deploy-saved-default-unavailable"
              className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 p-3"
            >
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
              <p className="text-xs text-muted-foreground">{staleSavedMessage}</p>
            </div>
          )}
          <div className="space-y-2">
            <Label>Server Name *</Label>
            <Input
              type="text"
              data-testid="deploy-server-name"
              value={deployForm.name}
              onChange={(e) => {
                setDeployForm({ ...deployForm, name: e.target.value })
                if (visibleError) setVisibleError(null)
              }}
              placeholder="my-simulation-server"
            />
          </div>
          <div className="space-y-2" role="group" aria-labelledby="deploy-server-plan-label">
            <Label id="deploy-server-plan-label">Plan *</Label>
            <Select
              value={deployForm.plan_id}
              data-testid="deploy-server-plan"
              onChange={(value) => {
                setDeployForm({ ...deployForm, plan_id: value })
                setSelectionTouched((current) => ({ ...current, plan: true }))
                if (visibleError) setVisibleError(null)
              }}
              placeholder="Select a plan..."
            >
              {plans.map((plan) => (
                <SelectItem
                  key={plan.id}
                  value={plan.id}
                  data-testid={`deploy-server-plan-${plan.id}`}
                >
                  {plan.name} ({plan.cpu_limit} CPU / {plan.memory_limit} /{' '}
                  {formatPlanResource(plan.disk_limit)} disk
                  {plan.gpu_limit > 0 ? ` · ${plan.gpu_limit} GPU` : ''})
                </SelectItem>
              ))}
            </Select>
            {planSelectionStale && !missingPlans && (
              <p role="status" className="pl-1 text-xs text-destructive">
                The selected plan is no longer available. Choose a current plan.
              </p>
            )}
          </div>
          <div className="space-y-2" role="group" aria-labelledby="deploy-server-environment-label">
            <Label id="deploy-server-environment-label">Environment *</Label>
            <Select
              value={deployForm.environment_id}
              data-testid="deploy-server-environment"
              onChange={(value) => {
                setDeployForm({ ...deployForm, environment_id: value })
                setSelectionTouched((current) => ({ ...current, environment: true }))
                if (visibleError) setVisibleError(null)
              }}
              placeholder="Select an environment..."
            >
              {environments.map((env) => (
                <SelectItem
                  key={env.id}
                  value={env.id}
                  data-testid={`deploy-server-environment-${env.id}`}
                >
                  {env.name} ({env.slug})
                </SelectItem>
              ))}
            </Select>
            {environmentSelectionStale && !missingEnvironments && (
              <p role="status" className="pl-1 text-xs text-destructive">
                The selected environment is no longer available. Choose a current environment.
              </p>
            )}
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label className="flex items-center gap-1.5">
                <HardDrive className="w-4 h-4" />
                Volume Mounts
              </Label>
              <button
                type="button"
                onClick={addVolumeMount}
                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <Plus className="w-3.5 h-3.5" />
                Add Volume
              </button>
            </div>

            {/* Capacity indicator */}
            {selectedPlan && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">
                    Plan capacity: {formatPlanResource(selectedPlan.disk_limit)}
                  </span>
                  <span
                    className={
                      isOverCapacity ? 'text-destructive font-medium' : 'text-muted-foreground'
                    }
                  >
                    {formatBytes(totalAllocatedBytes)} /{' '}
                    {formatPlanResource(selectedPlan.disk_limit)}
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${
                      isOverCapacity
                        ? 'bg-destructive'
                        : capacityPercent > 80
                          ? 'bg-amber-500'
                          : 'bg-emerald-500'
                    }`}
                    style={{ width: `${capacityPercent}%` }}
                  />
                </div>
                {isOverCapacity && (
                  <p className="text-xs text-destructive">
                    Total volume capacity exceeds plan disk limit. Reduce sizes or choose a larger
                    plan.
                  </p>
                )}
              </div>
            )}

            {volumeMounts.map((mount, index) => {
              const selectedVol = volumes.find((v) => v.id === mount.volume_id)
              const isNewVolume = !mount.volume_id
              return (
                <div
                  key={index}
                  className="space-y-2 p-3 rounded-lg bg-surface/50 border border-border/50"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">
                      {index === 0 ? 'Primary Mount' : `Additional Mount ${index}`}
                    </span>
                    {volumeMounts.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeVolumeMount(index)}
                        aria-label={`Remove volume mount ${index + 1}`}
                        className="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>

                  <Select
                    value={mount.volume_id}
                    data-testid={`deploy-volume-${index}`}
                    onChange={(value) => updateVolumeMount(index, 'volume_id', value)}
                    placeholder="Create new volume (default)"
                  >
                    <SelectItem value="" data-testid={`deploy-volume-${index}-new`}>
                      Create new volume
                    </SelectItem>
                    {volumes.map((vol) => (
                      <SelectItem
                        key={vol.id}
                        value={vol.id}
                        data-testid={`deploy-volume-${index}-${vol.id}`}
                      >
                        {vol.display_name}{' '}
                        {vol.max_size_bytes
                          ? `(${formatBytes(vol.max_size_bytes)} limit${vol.size_bytes > 0 ? `, ${formatBytes(vol.size_bytes)} used` : ''})`
                          : vol.size_bytes > 0
                            ? `(${formatBytes(vol.size_bytes)} used)`
                            : '(unused)'}
                      </SelectItem>
                    ))}
                  </Select>

                  {/* Size input for new volumes */}
                  {isNewVolume && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground whitespace-nowrap">Size:</span>
                      <Input
                        type="number"
                        min={1}
                        max={500}
                        value={mount.max_size_gb}
                        onChange={(e) => {
                          const val = parseInt(e.target.value, 10)
                          updateVolumeMount(
                            index,
                            'max_size_gb',
                            String(isNaN(val) ? 1 : Math.max(1, Math.min(500, val)))
                          )
                        }}
                        className="w-20 text-sm"
                      />
                      <span className="text-xs text-muted-foreground">GB</span>
                    </div>
                  )}

                  {/* Show existing volume size info */}
                  {selectedVol && (
                    <div className="text-xs text-muted-foreground">
                      {selectedVol.max_size_bytes
                        ? `Capacity: ${formatBytes(selectedVol.max_size_bytes)}${selectedVol.size_bytes > 0 ? ` • Used: ${formatBytes(selectedVol.size_bytes)}` : ''}`
                        : selectedVol.size_bytes > 0
                          ? `Used: ${formatBytes(selectedVol.size_bytes)}`
                          : 'Empty volume'}
                    </div>
                  )}

                  <div className="flex gap-2">
                    <Input
                      type="text"
                      value={mount.mount_path}
                      onChange={(e) => updateVolumeMount(index, 'mount_path', e.target.value)}
                      placeholder={index === 0 ? `/home/${defaultUsername}` : '/data'}
                      className="flex-1 text-sm"
                    />
                    <div className="flex gap-1">
                      <Button
                        type="button"
                        variant={mount.mode === 'read_write' ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => updateVolumeMount(index, 'mode', 'read_write')}
                        className="text-xs px-2"
                      >
                        RW
                      </Button>
                      <Button
                        type="button"
                        variant={mount.mode === 'read_only' ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => updateVolumeMount(index, 'mode', 'read_only')}
                        className="text-xs px-2"
                      >
                        RO
                      </Button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          <section
            aria-labelledby="deploy-review-heading"
            data-testid="deploy-review"
            className="rounded-xl border border-border/60 bg-surface/40 p-4"
          >
            <div className="flex items-start gap-2">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              <div className="min-w-0">
                <h3 id="deploy-review-heading" className="text-sm font-semibold">
                  Review before launch
                </h3>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Final eligibility and capacity are confirmed when you submit.
                </p>
              </div>
            </div>

            <dl className="mt-3 grid grid-cols-2 gap-2">
              <div className="rounded-lg border border-border/50 bg-background/40 p-2.5">
                <dt className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  CPU
                </dt>
                <dd className="mt-0.5 break-words text-sm font-medium">
                  {selectedPlan ? `${selectedPlan.cpu_limit} vCPU` : 'Choose a plan'}
                </dd>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-2.5">
                <dt className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Memory
                </dt>
                <dd className="mt-0.5 break-words text-sm font-medium">
                  {selectedPlan ? formatPlanResource(selectedPlan.memory_limit) : 'Choose a plan'}
                </dd>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-2.5">
                <dt className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Disk
                </dt>
                <dd className="mt-0.5 break-words text-sm font-medium">
                  {selectedPlan ? formatPlanResource(selectedPlan.disk_limit) : 'Choose a plan'}
                </dd>
              </div>
              <div className="rounded-lg border border-border/50 bg-background/40 p-2.5">
                <dt className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  Cost
                </dt>
                <dd className="mt-0.5 break-words text-sm font-medium">
                  {describeDeployCost(selectedPlan ?? null)}
                </dd>
              </div>
              {selectedPlan && selectedPlan.gpu_limit > 0 && (
                <div className="rounded-lg border border-border/50 bg-background/40 p-2.5">
                  <dt className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    GPU
                  </dt>
                  <dd className="mt-0.5 break-words text-sm font-medium">
                    {selectedPlan.gpu_limit}
                  </dd>
                </div>
              )}
            </dl>

            <div className="mt-3 rounded-lg border border-border/50 bg-background/40 p-3">
              <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                <HardDrive className="h-3.5 w-3.5" aria-hidden="true" />
                Private storage
              </p>
              <ul className="mt-1.5 space-y-1">
                {volumeMounts.map((mount, index) => {
                  const review = describeDeployVolume(mount, volumes, defaultUsername, index)
                  return (
                    <li key={index} className="flex flex-wrap items-baseline gap-x-1.5 text-xs">
                      <span
                        className={cn(
                          'font-medium',
                          review.missing ? 'text-destructive' : 'text-foreground'
                        )}
                      >
                        {review.action}
                      </span>
                      <span className="text-muted-foreground">{review.detail}</span>
                    </li>
                  )
                })}
              </ul>
            </div>

            <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              If capacity is unavailable, your request waits in the existing queue. You can track it
              from Waiting requests.
            </p>
          </section>
        </form>
        <DialogFooter>
          <Button variant="outline" type="button" onClick={handleCancel}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="deploy-form"
            data-testid="deploy-server-submit"
            loading={isPending}
            disabled={!isValid || prerequisitesMissing}
          >
            {isPending ? 'Deploying...' : 'Deploy'}
          </Button>
        </DialogFooter>
        <DialogClose onClick={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}
