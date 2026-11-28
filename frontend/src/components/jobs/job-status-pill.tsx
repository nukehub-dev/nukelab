// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock,
  Loader2,
  Play,
  ShieldAlert,
  TimerOff,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { jobStateLabel } from '../../lib/batch-job'
import { cn } from '../../lib/utils'
import type { JobState } from '../../types/batch-job'

const jobStateConfig: Record<JobState, { icon: LucideIcon; pill: string; spin?: boolean }> = {
  queued: {
    icon: Clock,
    pill: 'border-blue-500/20 bg-blue-500/10 text-blue-400',
  },
  starting: {
    icon: Loader2,
    pill: 'border-amber-500/20 bg-amber-500/10 text-amber-400',
    spin: true,
  },
  running: {
    icon: Play,
    pill: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400',
  },
  cancelling: {
    icon: Loader2,
    pill: 'border-amber-500/20 bg-amber-500/10 text-amber-400',
    spin: true,
  },
  recovery_required: {
    icon: ShieldAlert,
    pill: 'border-amber-500/20 bg-amber-500/10 text-amber-400',
  },
  succeeded: {
    icon: CheckCircle2,
    pill: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400',
  },
  failed: {
    icon: XCircle,
    pill: 'border-red-500/20 bg-red-500/10 text-red-400',
  },
  cancelled: {
    icon: Ban,
    pill: 'border-border/50 bg-muted/50 text-muted-foreground',
  },
  timed_out: {
    icon: TimerOff,
    pill: 'border-red-500/20 bg-red-500/10 text-red-400',
  },
  expired: {
    icon: AlertTriangle,
    pill: 'border-border/50 bg-muted/50 text-muted-foreground',
  },
}

export function JobStatusPill({
  state,
  size = 'md',
  className,
}: {
  state: JobState
  size?: 'sm' | 'md'
  className?: string
}) {
  const config = jobStateConfig[state]
  const Icon = config.icon
  return (
    <span
      role="status"
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded-full border font-medium',
        size === 'sm' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs',
        config.pill,
        className
      )}
    >
      <Icon
        className={cn(size === 'sm' ? 'h-3 w-3' : 'h-3.5 w-3.5', config.spin && 'animate-spin')}
        aria-hidden="true"
      />
      {jobStateLabel(state)}
    </span>
  )
}
