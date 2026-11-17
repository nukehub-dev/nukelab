// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
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
import type { RecreationPreview, RecreationSource } from '../../types/server-provenance'
import { Button } from '../ui/button'
import {
  Dialog,
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
import { formatBytes, formatPlanResource, parseMemoryString } from '../../lib/utils'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  sourceLaunchId?: string
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
  const requestVersion = useRef(0)
  const mounted = useRef(true)
  const submission = useRef(false)
  const dialogRef = useRef<HTMLDivElement>(null)
  const currentAccount = () => mounted.current && useAuthStore.getState().user?.id === ownerId
  const plans = catalog.plans.data ?? []
  const volumes = catalog.volumes.data ?? []
  const plan = plans.find((item) => item.id === planId)
  const busy = validating || recreate.isPending

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
      if (currentAccount() && version === requestVersion.current) updateInput(text)
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
    <Dialog open onOpenChange={onOpenChange} size="lg">
      <DialogContent
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="recreate-dialog-title"
        tabIndex={-1}
      >
        <DialogHeader>
          <DialogTitle id="recreate-dialog-title">
            {sourceLaunchId ? 'Recreate environment' : 'Import environment'}
          </DialogTitle>
          <DialogDescription>
            Create a new server from an approved captured environment. Data volumes are selected
            separately; existing files are never copied by the environment file.
          </DialogDescription>
        </DialogHeader>
        <form className="mt-4 space-y-5" onSubmit={submit} noValidate>
          {!sourceLaunchId && (
            <div className="space-y-2">
              <Label htmlFor="environment-file">Environment JSON file</Label>
              <Input
                id="environment-file"
                type="file"
                accept="application/json,.json"
                disabled={busy}
                onChange={(event) => {
                  void loadFile(event.target.files?.[0])
                }}
              />
              <Label htmlFor="environment-json">Or paste exported JSON</Label>
              <Textarea
                id="environment-json"
                data-testid="environment-import-json"
                value={raw}
                onChange={(event) => updateInput(event.target.value)}
                disabled={recreate.isPending}
                autoResize={false}
                className="h-40 font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">
                Maximum 64 KiB. Imported files cannot grant access to unapproved environments or
                other users’ data.
              </p>
              <Button
                type="button"
                variant="outline"
                disabled={busy || !raw.trim()}
                onClick={() => {
                  try {
                    void check({ manifest: parseManifestInput(raw) })
                  } catch (error) {
                    setFailure(error)
                  }
                }}
              >
                Validate environment
              </Button>
            </div>
          )}
          {validating && <p role="status">Checking approved environment…</p>}
          {failure != null && (
            <div
              role="alert"
              className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 space-y-2"
            >
              <p className="text-sm">{provenanceErrorMessage(failure)}</p>
              {failure instanceof ApiError &&
                failure.code === 'request_already_exists' &&
                failure.queueId && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      onOpenChange(false)
                      void navigate({
                        to: '/servers',
                        search: { tab: 'queue', request: failure.queueId },
                      })
                    }}
                  >
                    View existing request
                  </Button>
                )}
              {sourceLaunchId && !preview && !busy && (
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
          {preview && (
            <>
              <section className="rounded-lg bg-surface/50 p-3 space-y-2">
                <h3 className="font-medium">{preview.environment_label}</h3>
                <p className="text-sm">
                  {preview.manifest.portability === 'registry_verified'
                    ? 'Registry-verified artifacts'
                    : 'Local-only environment: captured images must exist on this installation.'}
                </p>
                <p className="text-xs text-muted-foreground">
                  Environment variable values are excluded from the file. Approved configuration and
                  current permissions remain authoritative.
                </p>
                <ul className="list-disc pl-4 text-xs text-muted-foreground space-y-1">
                  {preview.manifest.limitations.map((limitation) => (
                    <li key={limitation}>{limitation}</li>
                  ))}
                </ul>
              </section>
              <div className="space-y-2">
                <Label htmlFor="recreate-name">New server name</Label>
                <Input
                  id="recreate-name"
                  data-testid="recreate-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  disabled={recreate.isPending}
                  autoComplete="off"
                />
              </div>
              <div className="space-y-2">
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
                      {item.name} · {item.cpu_limit} CPU · {formatPlanResource(item.memory_limit)}{' '}
                      RAM · {formatPlanResource(item.disk_limit)} disk
                    </SelectItem>
                  ))}
                </Select>
                {catalog.plans.isError && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      void catalog.plans.refetch()
                    }}
                  >
                    Retry plan choices
                  </Button>
                )}
              </div>
              <section className="space-y-3">
                <h3 className="font-medium">Choose data volumes</h3>
                <p className="text-sm text-muted-foreground">
                  No volume from the source server is selected automatically. Choose a fresh volume
                  or one you own for each mount.
                </p>
                {catalog.volumes.isError && (
                  <p role="status" className="text-sm">
                    Existing volumes could not be loaded. Fresh volumes remain available.{' '}
                    <button
                      type="button"
                      className="text-primary underline"
                      onClick={() => {
                        void catalog.volumes.refetch()
                      }}
                    >
                      Retry
                    </button>
                  </p>
                )}
                {preview.volume_requirements.map((requirement, index) => (
                  <div
                    key={`${requirement.mount_path}:${index}`}
                    className="rounded-lg border border-border p-3 space-y-2"
                  >
                    <Label>
                      {requirement.purpose} · {requirement.mount_path} ·{' '}
                      {requirement.mode === 'read_only' ? 'Read only' : 'Read/write'}
                    </Label>
                    <Select
                      value={choices[index]?.selection ?? ''}
                      onChange={(selection) =>
                        setChoices((current) =>
                          current.map((choice, i) =>
                            i === index ? { ...choice, selection } : choice
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
                    {choices[index]?.selection === 'fresh' && (
                      <div className="space-y-1">
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
                              current.map((choice, i) =>
                                i === index ? { ...choice, sizeGiB: event.target.value } : choice
                              )
                            )
                          }
                        />
                      </div>
                    )}
                  </div>
                ))}
              </section>
            </>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              data-testid="recreate-submit"
              disabled={!preview || busy}
              loading={recreate.isPending}
            >
              Create new server
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
