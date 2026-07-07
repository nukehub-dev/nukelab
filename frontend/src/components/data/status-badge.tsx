// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { cn } from '../../lib/utils'
import { motion } from 'framer-motion'
import { CheckCircle2, Square, Loader2, AlertCircle, AlertTriangle, Info } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

type StatusType =
  | 'running'
  | 'stopped'
  | 'pending'
  | 'error'
  | 'warning'
  | 'info'
  | 'healthy'
  | 'unhealthy'
  | 'unknown'

interface StatusBadgeProps {
  status: StatusType
  label?: string
  pulse?: boolean
  size?: 'sm' | 'md'
  className?: string
}

const statusConfig: Record<
  StatusType,
  {
    icon: LucideIcon
    bgColor: string
    textColor: string
    borderColor: string
    defaultLabel: string
  }
> = {
  running: {
    icon: CheckCircle2,
    bgColor: 'bg-emerald-500/10',
    textColor: 'text-emerald-400',
    borderColor: 'border-emerald-500/20',
    defaultLabel: 'Running',
  },
  stopped: {
    icon: Square,
    bgColor: 'bg-gray-500/10',
    textColor: 'text-gray-400',
    borderColor: 'border-gray-500/20',
    defaultLabel: 'Stopped',
  },
  pending: {
    icon: Loader2,
    bgColor: 'bg-blue-500/10',
    textColor: 'text-blue-400',
    borderColor: 'border-blue-500/20',
    defaultLabel: 'Pending',
  },
  error: {
    icon: AlertCircle,
    bgColor: 'bg-red-500/10',
    textColor: 'text-red-400',
    borderColor: 'border-red-500/20',
    defaultLabel: 'Error',
  },
  warning: {
    icon: AlertTriangle,
    bgColor: 'bg-amber-500/10',
    textColor: 'text-amber-400',
    borderColor: 'border-amber-500/20',
    defaultLabel: 'Warning',
  },
  info: {
    icon: Info,
    bgColor: 'bg-sky-500/10',
    textColor: 'text-sky-400',
    borderColor: 'border-sky-500/20',
    defaultLabel: 'Info',
  },
  healthy: {
    icon: CheckCircle2,
    bgColor: 'bg-emerald-500/10',
    textColor: 'text-emerald-400',
    borderColor: 'border-emerald-500/20',
    defaultLabel: 'Healthy',
  },
  unhealthy: {
    icon: AlertCircle,
    bgColor: 'bg-red-500/10',
    textColor: 'text-red-400',
    borderColor: 'border-red-500/20',
    defaultLabel: 'Unhealthy',
  },
  unknown: {
    icon: Info,
    bgColor: 'bg-gray-500/10',
    textColor: 'text-gray-400',
    borderColor: 'border-gray-500/20',
    defaultLabel: 'Unknown',
  },
}

export function StatusBadge({
  status,
  label,
  pulse = false,
  size = 'md',
  className,
}: StatusBadgeProps) {
  const config = statusConfig[status]
  const { icon: Icon, bgColor, textColor, borderColor, defaultLabel } = config
  const shouldPulse = pulse || status === 'running' || status === 'pending'

  const sizeClasses = {
    sm: 'h-5 px-2 text-[11px] gap-1',
    md: 'h-6 px-2.5 text-xs gap-1.5',
  }

  return (
    <motion.span
      className={cn(
        'inline-flex items-center justify-center rounded-full font-medium border',
        sizeClasses[size],
        bgColor,
        textColor,
        borderColor,
        className
      )}
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: 'spring', stiffness: 400, damping: 25 }}
    >
      {shouldPulse ? (
        <span className="relative flex h-2 w-2">
          <span
            className={cn(
              'animate-ping absolute inline-flex h-full w-full rounded-full opacity-75',
              status === 'running' && 'bg-emerald-400',
              status === 'pending' && 'bg-blue-400'
            )}
          />
          <span
            className={cn(
              'relative inline-flex rounded-full h-2 w-2',
              status === 'running' && 'bg-emerald-400',
              status === 'pending' && 'bg-blue-400'
            )}
          />
        </span>
      ) : (
        <Icon className="w-3.5 h-3.5" />
      )}
      <span>{label || defaultLabel}</span>
    </motion.span>
  )
}
