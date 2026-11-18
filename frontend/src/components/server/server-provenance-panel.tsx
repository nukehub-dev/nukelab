// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  BadgeCheck,
  Box,
  CalendarClock,
  Copy,
  Download,
  Fingerprint,
  GitCommitHorizontal,
  Globe,
  History,
  KeyRound,
  LockKeyhole,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Wrench,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  fetchEnvironmentManifest,
  useProvenanceCapabilities,
  useServerProvenance,
} from '../../hooks/use-server-provenance'
import { provenanceErrorMessage, recreationReason } from '../../lib/server-provenance'
import { cn, formatDate } from '../../lib/utils'
import { PERMISSIONS, useAuthStore } from '../../stores/auth-store'
import type { Server } from '../../types/api'
import type { ImageIdentity } from '../../types/server-provenance'
import { StatusBadge } from '../data/status-badge'
import { Button } from '../ui/button'
import { Tooltip } from '../ui/tooltip'
import { RecreateServerDialog } from './recreate-server-dialog'

type Tone = 'primary' | 'sky' | 'amber' | 'violet'

const toneClasses: Record<Tone, string> = {
  primary: 'bg-primary/10 text-primary',
  sky: 'bg-sky-500/10 text-sky-400',
  amber: 'bg-amber-500/10 text-amber-400',
  violet: 'bg-violet-500/10 text-violet-400',
}

function copyText(value: string) {
  return navigator.clipboard?.writeText(value) ?? Promise.reject(new Error('Copy unavailable'))
}

function MetadataCard({
  icon: Icon,
  tone,
  children,
}: {
  icon: LucideIcon
  tone: Tone
  children: React.ReactNode
}) {
  return (
    <div className="flex min-w-0 items-start gap-3 overflow-hidden rounded-xl border border-border/50 bg-surface/50 p-3">
      <div className={cn('shrink-0 rounded-lg p-2', toneClasses[tone])}>
        <Icon className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

function Identity({
  label,
  image,
  requested,
}: {
  label: string
  image: ImageIdentity | null
  requested?: string
}) {
  const [copyError, setCopyError] = useState(false)
  const Icon = label === 'Runtime' ? Box : Wrench
  const tone = label === 'Runtime' ? toneClasses.primary : toneClasses.violet

  if (!image)
    return (
      <div className="min-w-0 overflow-hidden rounded-xl border border-border/50 bg-surface/50 p-4">
        <div className="flex items-center gap-2.5">
          <div className="rounded-lg bg-muted p-2 text-muted-foreground">
            <Icon className="h-4 w-4" />
          </div>
          <h4 className="text-sm font-semibold">{label}</h4>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">Not recorded</p>
        <p className="mt-1 text-xs text-muted-foreground/80">
          No separate {label.toLowerCase()} image identity was captured for this launch.
        </p>
      </div>
    )

  const approved = requested ?? image.requested_reference
  return (
    <div className="min-w-0 space-y-3 overflow-hidden rounded-xl border border-border/50 bg-surface/50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className={cn('shrink-0 rounded-lg p-2', tone)}>
            <Icon className="h-4 w-4" />
          </div>
          <h4 className="text-sm font-semibold">{label}</h4>
        </div>
        <Tooltip content={approved} wrapperClassName="max-w-full min-w-0">
          <span className="inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-full border border-border/60 bg-muted/50 px-2.5 py-1 text-[11px] text-muted-foreground">
            <BadgeCheck className="h-3 w-3 shrink-0 text-emerald-400" />
            <span className="shrink-0">Approved request</span>
            <span className="min-w-0 truncate font-mono text-foreground/90">{approved}</span>
          </span>
        </Tooltip>
      </div>
      <div className="rounded-lg border border-border/50 bg-background/40 px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="shrink-0 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Local ID
          </span>
          <Tooltip content={image.local_id} wrapperClassName="flex min-w-0 flex-1">
            <code className="block truncate font-mono text-[11px] text-foreground/90">
              {image.local_id}
            </code>
          </Tooltip>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 shrink-0 px-2 text-[11px] text-muted-foreground hover:text-foreground"
            aria-label={`Copy ${label.toLowerCase()} image identity`}
            onClick={() => {
              void copyText(image.local_id).then(
                () => setCopyError(false),
                () => setCopyError(true)
              )
            }}
          >
            <Copy className="h-3 w-3" />
            Copy
          </Button>
        </div>
        {copyError && (
          <p role="status" className="mt-1.5 text-[11px] text-muted-foreground">
            Copy unavailable. Select the identity text to copy it.
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
        <span className="rounded-full bg-muted/50 px-2 py-0.5 font-mono text-muted-foreground">
          {image.os}/{image.architecture}
        </span>
        <span
          className={cn(
            'inline-flex items-center gap-1',
            image.registry_verified ? 'text-emerald-400' : 'text-muted-foreground'
          )}
        >
          {image.registry_verified ? (
            <ShieldCheck className="h-3 w-3 shrink-0" />
          ) : (
            <ShieldAlert className="h-3 w-3 shrink-0 text-amber-400/90" />
          )}
          <span>
            {image.registry_verified
              ? 'Registry verified'
              : 'Local identity, registry not verified'}
          </span>
        </span>
      </div>
    </div>
  )
}

function RevisionFingerprint({ fingerprint }: { fingerprint: string }) {
  const [copyError, setCopyError] = useState(false)
  return (
    <div className="rounded-xl border border-border/50 bg-surface/50 px-3.5 py-3">
      <div className="flex items-center gap-2">
        <Fingerprint className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="shrink-0 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Revision fingerprint
        </span>
        <Tooltip content={fingerprint} wrapperClassName="flex min-w-0 flex-1">
          <code className="block truncate font-mono text-[11px] text-muted-foreground">
            {fingerprint}
          </code>
        </Tooltip>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 shrink-0 px-2 text-[11px] text-muted-foreground hover:text-foreground"
          aria-label="Copy revision fingerprint"
          onClick={() => {
            void copyText(fingerprint).then(
              () => setCopyError(false),
              () => setCopyError(true)
            )
          }}
        >
          <Copy className="h-3 w-3" />
          Copy
        </Button>
      </div>
      {copyError && (
        <p role="status" className="mt-1.5 text-[11px] text-muted-foreground">
          Copy unavailable. Select the fingerprint to copy it.
        </p>
      )}
    </div>
  )
}

function ProvenanceSkeleton() {
  return (
    <div role="status" aria-live="polite" className="space-y-3">
      <span className="sr-only">Loading environment history…</span>
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <div
            key={index}
            className="flex animate-pulse items-start gap-3 rounded-xl border border-border/40 bg-surface/40 p-3"
          >
            <div className="h-8 w-8 shrink-0 rounded-lg bg-muted" />
            <div className="min-w-0 flex-1 space-y-2">
              <div className="h-2.5 w-16 rounded bg-muted" />
              <div className="h-3.5 w-24 rounded bg-muted" />
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {Array.from({ length: 2 }).map((_, index) => (
          <div
            key={index}
            className="animate-pulse space-y-3 rounded-xl border border-border/40 bg-surface/40 p-4"
          >
            <div className="flex items-center gap-2.5">
              <div className="h-8 w-8 rounded-lg bg-muted" />
              <div className="h-4 w-24 rounded bg-muted" />
            </div>
            <div className="h-6 w-48 rounded-full bg-muted" />
            <div className="h-10 rounded-lg bg-muted" />
          </div>
        ))}
      </div>
    </div>
  )
}

export function ServerProvenancePanel({ server }: { server: Server }) {
  const ownerId = useAuthStore((state) => state.user?.id)
  const own = !!ownerId && server.user_id === ownerId
  const canWrite = useAuthStore((state) => state.hasPermission(PERMISSIONS.SERVERS_WRITE_OWN))
  const capabilities = useProvenanceCapabilities()
  const enabled = capabilities.data?.enabled === true
  const provenance = useServerProvenance(server.id, own && enabled)
  const [showRecreate, setShowRecreate] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [failure, setFailure] = useState<unknown>(null)
  const authority = `${ownerId}:${server.id}:${server.container_id}:${server.status}`
  const previous = useRef(authority)
  const mounted = useRef(true)
  const currentServer = useRef(server.id)
  useEffect(() => {
    currentServer.current = server.id
  }, [server.id])
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  const { refetch } = provenance
  useEffect(() => {
    if (previous.current !== authority) {
      previous.current = authority
      if (enabled && own) void refetch()
    }
  }, [authority, enabled, own, refetch])
  useEffect(() => {
    queueMicrotask(() => {
      setShowRecreate(false)
      setFailure(null)
      setExporting(false)
    })
  }, [ownerId, server.id])

  const exportManifest = async () => {
    const launchId = provenance.data?.launch_id
    if (!launchId || !own || exporting) return
    setExporting(true)
    setFailure(null)
    try {
      const manifest = await fetchEnvironmentManifest(server.id, launchId)
      if (
        !mounted.current ||
        currentServer.current !== server.id ||
        useAuthStore.getState().user?.id !== ownerId
      )
        return
      const blob = new Blob([JSON.stringify(manifest, null, 2) + '\n'], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `nukelab-environment-${launchId}.json`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) {
      if (useAuthStore.getState().user?.id === ownerId) setFailure(error)
    } finally {
      if (useAuthStore.getState().user?.id === ownerId) setExporting(false)
    }
  }

  if (!enabled) return null
  if (!own)
    return (
      <section className="bubble p-5" aria-label="Environment details">
        <div className="flex items-start gap-3">
          <div className="shrink-0 rounded-xl bg-muted p-2.5 text-muted-foreground">
            <LockKeyhole className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-semibold">Environment details</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Environment history and source recreation are available to this server’s owner.
            </p>
          </div>
        </div>
      </section>
    )
  const data = provenance.data
  return (
    <section className="bubble space-y-5 p-5" aria-label="Environment details">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <div className="shrink-0 rounded-xl bg-primary/10 p-2.5 text-primary ring-1 ring-primary/15">
            <Fingerprint className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold">Environment details</h3>
              {data?.state === 'recorded' && data.manifest && (
                <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-emerald-400">
                  <ShieldCheck className="h-3 w-3" />
                  Verified record
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              <span>Last verified launch</span>
              <span aria-hidden="true"> · </span>
              <span>current server status:</span>{' '}
              <StatusBadge
                status={server.status}
                label={server.status}
                size="sm"
                className="align-middle"
              />
            </p>
          </div>
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="shrink-0 gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          disabled={provenance.isFetching}
          aria-label="Refresh environment details"
          onClick={() => {
            void refetch()
          }}
        >
          <RefreshCw className={cn('h-3.5 w-3.5', provenance.isFetching && 'animate-spin')} />
          <span className="hidden sm:inline">Refresh</span>
        </Button>
      </div>

      {provenance.isPending && <ProvenanceSkeleton />}

      {provenance.isError && (
        <div
          role="alert"
          className="flex items-start gap-3 rounded-xl border border-destructive/25 bg-destructive/10 p-4"
        >
          <div className="shrink-0 rounded-lg bg-destructive/15 p-2 text-destructive">
            <AlertTriangle className="h-4 w-4" />
          </div>
          <div className="min-w-0 space-y-2">
            <div>
              <p className="text-sm font-medium">Environment details unavailable</p>
              <p className="text-sm text-muted-foreground">
                {provenanceErrorMessage(provenance.error)}
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void refetch()
              }}
            >
              Retry environment details
            </Button>
          </div>
        </div>
      )}

      {data?.state === 'unrecorded' && (
        <div className="flex items-start gap-3 rounded-xl border border-border/60 bg-surface/50 p-4">
          <div className="shrink-0 rounded-xl bg-muted p-2.5 text-muted-foreground">
            <History className="h-5 w-5" />
          </div>
          <div className="min-w-0 space-y-1.5">
            <h4 className="text-sm font-semibold">Environment history not recorded</h4>
            <p className="text-sm text-muted-foreground">
              This server predates verified launch capture. Its original environment and toolchain
              cannot be reconstructed from today’s template.
            </p>
          </div>
        </div>
      )}

      {data?.state === 'recorded' && data.manifest && (
        <>
          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            <MetadataCard icon={BadgeCheck} tone="primary">
              <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Launch record
              </p>
              <p className="mt-0.5 text-sm font-medium tabular-nums">
                Verified generation:{' '}
                <span className="font-semibold text-foreground">{data.generation}</span>
              </p>
            </MetadataCard>
            <MetadataCard icon={CalendarClock} tone="sky">
              <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Captured
              </p>
              <p className="mt-0.5 text-sm font-medium">
                {data.captured_at ? formatDate(data.captured_at) : 'Time unavailable'}
              </p>
            </MetadataCard>
            <MetadataCard icon={GitCommitHorizontal} tone="violet">
              <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Revision
              </p>
              <Tooltip
                content={data.manifest.revision_id}
                wrapperClassName="mt-0.5 flex w-full min-w-0"
              >
                <span className="block truncate font-mono text-xs text-foreground/90">
                  {data.manifest.revision_id}
                </span>
              </Tooltip>
            </MetadataCard>
            <MetadataCard icon={Globe} tone="amber">
              <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                Portability
              </p>
              <span
                className={cn(
                  'mt-1 inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium',
                  data.manifest.portability === 'registry_verified'
                    ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
                    : 'border-amber-500/20 bg-amber-500/10 text-amber-400'
                )}
              >
                {data.manifest.portability === 'registry_verified'
                  ? 'Registry-verified environment'
                  : 'Local-only environment'}
              </span>
            </MetadataCard>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <Identity
              label="Runtime"
              image={data.actual_runtime}
              requested={data.manifest.runtime.requested_reference}
            />
            <Identity
              label="Toolchain"
              image={data.actual_toolchain}
              requested={data.manifest.toolchain?.requested_reference}
            />
          </div>

          <RevisionFingerprint fingerprint={data.manifest.revision_fingerprint} />

          <div className="rounded-xl border border-sky-500/20 bg-sky-500/5 p-4">
            <div className="flex items-start gap-3">
              <div className="shrink-0 rounded-lg bg-sky-500/10 p-2 text-sky-400">
                <ShieldAlert className="h-4 w-4" />
              </div>
              <div className="min-w-0 space-y-2.5">
                <div>
                  <p className="text-sm font-medium">Limits of this capture</p>
                  <p className="text-xs text-muted-foreground">
                    Recorded identities describe this launch only. They are not a portable copy of
                    the runtime or its data.
                  </p>
                </div>
                <ul className="space-y-1.5 text-xs text-muted-foreground">
                  {data.manifest.limitations.map((limitation) => (
                    <li key={limitation} className="flex gap-2">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-sky-400/70" />
                      <span>{limitation}</span>
                    </li>
                  ))}
                </ul>
                <div className="flex items-start gap-2 border-t border-sky-500/15 pt-2.5 text-xs text-muted-foreground">
                  <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-400/80" />
                  <p>
                    Export contains environment identities and variable names, not credentials or
                    mutable volume contents.
                  </p>
                </div>
              </div>
            </div>
          </div>

          {failure != null && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-destructive/25 bg-destructive/10 p-3 text-sm text-destructive"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>{provenanceErrorMessage(failure)}</p>
            </div>
          )}

          <div className="flex flex-col gap-3 border-t border-border/50 pt-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-muted-foreground">
              {!canWrite
                ? 'Export captures this verified record as sanitized JSON.'
                : data.can_recreate
                  ? 'Recreation uses this verified record and a new set of deliberate volume choices.'
                  : recreationReason(data.recreation_reason_code)}
            </p>
            <div className="flex flex-wrap gap-2 sm:justify-end">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  void exportManifest()
                }}
                disabled={exporting}
                loading={exporting}
              >
                <Download className="h-4 w-4" />
                Export environment
              </Button>
              {canWrite && (
                <Button
                  type="button"
                  disabled={!data.can_recreate}
                  onClick={() => setShowRecreate(true)}
                >
                  <RotateCcw className="h-4 w-4" />
                  Recreate environment
                </Button>
              )}
            </div>
          </div>
          {data.launch_id && (
            <RecreateServerDialog
              open={showRecreate}
              onOpenChange={setShowRecreate}
              sourceLaunchId={data.launch_id}
            />
          )}
        </>
      )}
    </section>
  )
}
