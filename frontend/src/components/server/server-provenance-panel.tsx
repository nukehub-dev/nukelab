// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useRef, useState } from 'react'
import { Copy, Download, RotateCcw } from 'lucide-react'
import {
  fetchEnvironmentManifest,
  useProvenanceCapabilities,
  useServerProvenance,
} from '../../hooks/use-server-provenance'
import { provenanceErrorMessage, recreationReason } from '../../lib/server-provenance'
import { formatDate } from '../../lib/utils'
import { PERMISSIONS, useAuthStore } from '../../stores/auth-store'
import type { Server } from '../../types/api'
import type { ImageIdentity } from '../../types/server-provenance'
import { Button } from '../ui/button'
import { Tooltip } from '../ui/tooltip'
import { RecreateServerDialog } from './recreate-server-dialog'

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
  if (!image) return <p className="text-sm text-muted-foreground">{label}: not recorded</p>
  return (
    <div className="rounded-lg border border-border p-3 space-y-2 min-w-0">
      <h4 className="font-medium text-sm">{label}</h4>
      <p className="text-xs break-all">
        Approved request: {requested ?? image.requested_reference}
      </p>
      <div className="flex items-center gap-2">
        <Tooltip content={image.local_id} wrapperClassName="min-w-0 flex-1">
          <code className="block truncate text-xs flex-1">{image.local_id}</code>
        </Tooltip>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          aria-label={`Copy ${label.toLowerCase()} image identity`}
          onClick={() => {
            void (
              navigator.clipboard?.writeText(image.local_id) ??
              Promise.reject(new Error('Copy unavailable'))
            ).then(
              () => setCopyError(false),
              () => setCopyError(true)
            )
          }}
        >
          <Copy className="h-3 w-3" />
          Copy
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        {image.os}/{image.architecture} ·{' '}
        {image.registry_verified ? 'Registry verified' : 'Local identity, registry not verified'}
      </p>
      {copyError && (
        <p role="status" className="text-xs">
          Copy unavailable. Select the identity text to copy it.
        </p>
      )}
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
      <section className="bubble p-5 space-y-2">
        <h3 className="font-semibold">Environment details</h3>
        <p className="text-sm text-muted-foreground">
          Environment history and source recreation are available to this server’s owner.
        </p>
      </section>
    )
  const data = provenance.data
  return (
    <section className="bubble p-5 space-y-4" aria-label="Environment details">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h3 className="font-semibold">Environment details</h3>
          <p className="text-sm text-muted-foreground">
            Last verified launch · current server status: {server.status}
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={provenance.isFetching}
          onClick={() => {
            void refetch()
          }}
        >
          Refresh environment details
        </Button>
      </div>
      {provenance.isPending && <p role="status">Loading environment history…</p>}
      {provenance.isError && (
        <div role="alert">
          <p>{provenanceErrorMessage(provenance.error)}</p>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void refetch()
            }}
          >
            Retry environment details
          </Button>
        </div>
      )}
      {data?.state === 'unrecorded' && (
        <div className="rounded-lg border border-border p-3">
          <h4 className="font-medium">Environment history not recorded</h4>
          <p className="text-sm text-muted-foreground">
            This server predates verified launch capture. Its original environment and toolchain
            cannot be reconstructed from today’s template.
          </p>
        </div>
      )}
      {data?.state === 'recorded' && data.manifest && (
        <>
          <div className="grid sm:grid-cols-2 gap-3 text-sm">
            <p>Verified generation: {data.generation}</p>
            <p>Captured: {data.captured_at ? formatDate(data.captured_at) : 'Time unavailable'}</p>
            <p className="break-all">Revision: {data.manifest.revision_id}</p>
            <p>
              {data.manifest.portability === 'registry_verified'
                ? 'Registry-verified environment'
                : 'Local-only environment'}
            </p>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
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
          <p className="text-xs break-all text-muted-foreground">
            Revision fingerprint: {data.manifest.revision_fingerprint}
          </p>
          <div className="space-y-2">
            <p className="text-sm font-medium">Limits of this capture</p>
            <ul className="list-disc pl-5 text-sm text-muted-foreground space-y-1">
              {data.manifest.limitations.map((limitation) => (
                <li key={limitation}>{limitation}</li>
              ))}
            </ul>
            <p className="text-xs text-muted-foreground">
              Export contains environment identities and variable names, not credentials or mutable
              volume contents.
            </p>
          </div>
          {failure != null && (
            <p role="alert" className="text-sm text-destructive">
              {provenanceErrorMessage(failure)}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
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
          {canWrite && !data.can_recreate && (
            <p className="text-sm text-muted-foreground">
              {recreationReason(data.recreation_reason_code)}
            </p>
          )}
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
