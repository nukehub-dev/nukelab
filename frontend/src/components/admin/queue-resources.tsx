// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { Cpu, HardDrive, MemoryStick, Zap, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { sanitizeQueueResources } from '../../lib/admin-queue'
import { cn, formatBytes } from '../../lib/utils'
import type { AdminQueueResources } from '../../types/admin-queue'

function QueueResourceChip({
  icon: Icon,
  compact,
  children,
}: {
  icon: LucideIcon
  compact: boolean
  children: ReactNode
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border border-border/50 bg-surface/50 px-2 py-1 text-[11px] text-muted-foreground',
        compact && 'px-1.5 py-0.5 text-[10px]'
      )}
    >
      <Icon className="h-3 w-3 shrink-0" />
      {children}
    </span>
  )
}

export interface QueueResourceChipsProps {
  resources: AdminQueueResources | null | undefined
  compact?: boolean
  className?: string
}

/** Compact, read-only request sizing shared by the queue table and cards. */
export function QueueResourceChips({
  resources,
  compact = false,
  className,
}: QueueResourceChipsProps) {
  const safe = sanitizeQueueResources(resources)
  return (
    <div
      className={cn('flex flex-wrap gap-1.5', compact && 'gap-1', className)}
      data-testid="queue-resource-chips"
    >
      <QueueResourceChip icon={Cpu} compact={compact}>
        {safe.cpu} vCPU
      </QueueResourceChip>
      <QueueResourceChip icon={MemoryStick} compact={compact}>
        {formatBytes(safe.memory_mib * 1024 * 1024)} RAM
      </QueueResourceChip>
      <QueueResourceChip icon={HardDrive} compact={compact}>
        {formatBytes(safe.disk_mib * 1024 * 1024)} disk
      </QueueResourceChip>
      <QueueResourceChip icon={Zap} compact={compact}>
        {safe.gpu_count} GPU
      </QueueResourceChip>
    </div>
  )
}
