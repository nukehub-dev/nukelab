// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import {
  AlertTriangle,
  Ban,
  Box,
  ChevronDown,
  ChevronUp,
  Clock,
  Folder,
  Fingerprint,
  KeyRound,
  Package,
  Plug,
  ShieldAlert,
  ShieldCheck,
  Wrench,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  revisionLimitationLabel,
  revisionManifestDigest,
  revisionPlatform,
  revisionPortabilityLabel,
  revisionVolumeModeLabel,
  shortRevisionId,
} from '../../lib/environment-revisions'
import { cn, formatDate } from '../../lib/utils'
import type {
  EnvironmentRevisionConfiguration,
  EnvironmentRevisionImage,
  EnvironmentRevisionSummary,
} from '../../types/environment-revisions'
import { Button } from '../ui/button'
import { Card, CardContent } from '../ui/card'
import { CopyButton } from '../ui/copy-button'
import { Tooltip } from '../ui/tooltip'

function PortabilityPill({ revision }: { revision: EnvironmentRevisionSummary }) {
  const verified = revision.portability === 'registry_verified'
  const Icon = verified ? ShieldCheck : ShieldAlert
  return (
    <span
      data-testid="revision-portability"
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium',
        verified
          ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
          : 'border-amber-500/20 bg-amber-500/10 text-amber-400'
      )}
    >
      <Icon className="h-3 w-3 shrink-0" />
      {revisionPortabilityLabel(revision.portability)}
    </span>
  )
}

function RevokedPill() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-red-500/20 bg-red-500/10 px-2 py-0.5 text-[11px] font-medium text-red-400">
      <Ban className="h-3 w-3 shrink-0" />
      Revoked
    </span>
  )
}

function ImageSummary({ label, image }: { label: string; image: EnvironmentRevisionImage }) {
  const Icon = label === 'Runtime' ? Box : Wrench
  const digest = revisionManifestDigest(image)
  return (
    <div className="min-w-0 rounded-lg border border-border/50 bg-background/40 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="text-xs font-semibold">{label}</span>
        </div>
        <span
          className={cn(
            'inline-flex items-center gap-1 text-[11px]',
            image.registry_verified ? 'text-emerald-400' : 'text-amber-400'
          )}
        >
          {image.registry_verified ? (
            <ShieldCheck className="h-3 w-3 shrink-0" />
          ) : (
            <ShieldAlert className="h-3 w-3 shrink-0" />
          )}
          {image.registry_verified ? 'Registry verified' : 'Not registry verified'}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        <span className="rounded-full bg-muted/50 px-2 py-0.5 font-mono">
          {revisionPlatform(image)}
        </span>
      </div>
      {digest ? (
        <div className="mt-2 flex min-w-0 items-center gap-1.5">
          <span className="shrink-0 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Manifest
          </span>
          <Tooltip content={digest} wrapperClassName="min-w-0">
            <code className="block truncate font-mono text-[11px] text-foreground/90">
              {digest}
            </code>
          </Tooltip>
          <CopyButton value={digest} label={`Copy ${label.toLowerCase()} manifest digest`} />
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-muted-foreground">
          No verified manifest digest captured.
        </p>
      )}
    </div>
  )
}

function BoundedChipList({
  items,
  emptyLabel,
  max = 8,
}: {
  items: string[]
  emptyLabel: string
  max?: number
}) {
  const [expanded, setExpanded] = useState(false)
  if (items.length === 0) {
    return <span className="text-xs text-muted-foreground">{emptyLabel}</span>
  }
  const shown = expanded ? items : items.slice(0, max)
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {shown.map((item) => (
        <code
          key={item}
          className="max-w-full truncate rounded-md border border-border/50 bg-muted/50 px-1.5 py-0.5 text-[11px] text-foreground/90"
        >
          {item}
        </code>
      ))}
      {!expanded && items.length > max && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-muted/60 hover:text-foreground"
        >
          +{items.length - max} more
        </button>
      )}
    </div>
  )
}

function ConfigurationSection({
  icon: Icon,
  label,
  children,
}: {
  icon: LucideIcon
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="min-w-0 space-y-1.5">
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        <Icon className="h-3 w-3 shrink-0" />
        {label}
      </div>
      {children}
    </div>
  )
}

function ConfigurationSummary({
  configuration,
}: {
  configuration: EnvironmentRevisionConfiguration
}) {
  return (
    <div className="grid gap-3 border-t border-border/50 pt-3 sm:grid-cols-2">
      <ConfigurationSection icon={Box} label="Image">
        {configuration.image ? (
          <code className="block truncate font-mono text-[11px] text-foreground/90">
            {configuration.image}
          </code>
        ) : (
          <span className="text-xs text-muted-foreground">Not recorded</span>
        )}
      </ConfigurationSection>
      <ConfigurationSection icon={Wrench} label="Tool image">
        {configuration.tool_image ? (
          <code className="block truncate font-mono text-[11px] text-foreground/90">
            {configuration.tool_image}
          </code>
        ) : (
          <span className="text-xs text-muted-foreground">No toolchain</span>
        )}
      </ConfigurationSection>
      <ConfigurationSection icon={Package} label="Packages">
        <BoundedChipList items={configuration.packages} emptyLabel="No packages declared" />
      </ConfigurationSection>
      <ConfigurationSection icon={Plug} label="Ports">
        <BoundedChipList items={configuration.ports} emptyLabel="No ports declared" max={12} />
      </ConfigurationSection>
      <ConfigurationSection icon={Folder} label="Tool mounts">
        <BoundedChipList items={configuration.tool_mounts} emptyLabel="No tool mounts declared" />
      </ConfigurationSection>
      <ConfigurationSection icon={KeyRound} label="Environment variables (names only)">
        <BoundedChipList
          items={configuration.environment_variable_names}
          emptyLabel="No environment variables declared"
        />
      </ConfigurationSection>
      <div className="sm:col-span-2">
        <ConfigurationSection icon={Folder} label="Container volumes">
          {configuration.volumes.length === 0 ? (
            <span className="text-xs text-muted-foreground">No container volumes declared</span>
          ) : (
            <div className="flex flex-wrap items-center gap-1.5">
              {configuration.volumes.map((volume) => (
                <span
                  key={`${volume.mount_path}:${volume.mode}`}
                  className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-border/50 bg-muted/50 px-1.5 py-0.5 text-[11px]"
                >
                  <code className="truncate text-foreground/90">{volume.mount_path}</code>
                  <span className="shrink-0 text-muted-foreground">
                    {revisionVolumeModeLabel(volume.mode)}
                  </span>
                </span>
              ))}
            </div>
          )}
        </ConfigurationSection>
      </div>
    </div>
  )
}

function Limitations({ limitations }: { limitations: string[] }) {
  const [expanded, setExpanded] = useState(false)
  if (limitations.length === 0) return null
  const shown = expanded ? limitations : limitations.slice(0, 4)
  return (
    <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-amber-400">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
        Limitations
      </div>
      <ul className="mt-1.5 space-y-1 pl-5 text-[11px] text-amber-200/90">
        {shown.map((limitation) => (
          <li key={limitation} className="list-disc">
            {revisionLimitationLabel(limitation)}
          </li>
        ))}
      </ul>
      {limitations.length > 4 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-1.5 text-[11px] text-amber-300/90 hover:text-amber-200"
        >
          Show all {limitations.length} limitations
        </button>
      )}
    </div>
  )
}

export interface EnvironmentRevisionCardProps {
  revision: EnvironmentRevisionSummary
  canManage: boolean
  highlighted?: boolean
  onRevoke?: (revision: EnvironmentRevisionSummary) => void
}

export function EnvironmentRevisionCard({
  revision,
  canManage,
  highlighted = false,
  onRevoke,
}: EnvironmentRevisionCardProps) {
  const [configurationOpen, setConfigurationOpen] = useState(false)
  const configuration = revision.configuration
  const configurationSummary = [
    configuration.packages.length ? `${configuration.packages.length} packages` : null,
    configuration.ports.length ? `${configuration.ports.length} ports` : null,
    configuration.volumes.length ? `${configuration.volumes.length} volumes` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  return (
    <Card
      variant="bubble"
      className={cn(
        'border-border/50',
        highlighted && 'ring-2 ring-primary/40',
        revision.revoked && 'opacity-80'
      )}
    >
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="inline-flex items-center gap-0.5">
                <Tooltip content={revision.id}>
                  <code className="rounded-md bg-muted/50 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                    rev {shortRevisionId(revision.id)}
                  </code>
                </Tooltip>
                <CopyButton value={revision.id} label="Copy revision ID" />
              </span>
              <PortabilityPill revision={revision} />
              {revision.revoked && <RevokedPill />}
            </div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3 shrink-0" />
                {revision.created_at ? formatDate(revision.created_at) : 'Capture time unavailable'}
              </span>
              <span className="inline-flex min-w-0 items-center gap-0.5">
                <Tooltip content={revision.fingerprint} wrapperClassName="min-w-0">
                  <span className="inline-flex min-w-0 items-center gap-1">
                    <Fingerprint className="h-3 w-3 shrink-0" />
                    <code className="truncate font-mono text-[10px]">
                      {shortRevisionId(revision.fingerprint)}
                    </code>
                  </span>
                </Tooltip>
                <CopyButton value={revision.fingerprint} label="Copy revision fingerprint" />
              </span>
            </div>
          </div>
          {canManage && !revision.revoked && onRevoke && (
            <Button type="button" size="sm" variant="outline" onClick={() => onRevoke(revision)}>
              <Ban className="h-3.5 w-3.5" />
              Revoke
            </Button>
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <ImageSummary label="Runtime" image={revision.runtime} />
          {revision.toolchain && <ImageSummary label="Toolchain" image={revision.toolchain} />}
        </div>

        <div className="border-t border-border/50 pt-3">
          <button
            type="button"
            onClick={() => setConfigurationOpen((open) => !open)}
            aria-expanded={configurationOpen}
            className="flex w-full items-center justify-between gap-2 rounded-lg px-1 py-1 text-left text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <Box className="h-3.5 w-3.5 shrink-0" />
              <span className="font-medium">Configuration</span>
              {configurationSummary && (
                <span className="truncate text-[11px] text-muted-foreground">
                  {configurationSummary}
                </span>
              )}
            </span>
            <span className="inline-flex shrink-0 items-center gap-1">
              {configurationOpen ? 'Hide' : 'Show'}
              {configurationOpen ? (
                <ChevronUp className="h-3.5 w-3.5" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5" />
              )}
            </span>
          </button>
          <div className={cn('mt-2', !configurationOpen && 'hidden')}>
            <ConfigurationSummary configuration={revision.configuration} />
          </div>
        </div>
        <Limitations limitations={revision.limitations} />
      </CardContent>
    </Card>
  )
}
