// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { cn } from '../../lib/utils'
import { motion } from 'framer-motion'
import { useState } from 'react'

interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  className?: string
}

export function Skeleton({ className, ...props }: SkeletonProps) {
  return <div className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />
}

interface SkeletonCardProps {
  className?: string
  rows?: number
}

export function SkeletonCard({ className, rows = 3 }: SkeletonCardProps) {
  const [widths] = useState(() =>
    Array.from({ length: rows }, () => `${85 + Math.floor(Math.random() * 15)}%`)
  )

  return (
    <motion.div
      className={cn('bubble p-5 space-y-4', className)}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <div className="flex items-center justify-between">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-8 rounded-lg" />
      </div>
      <Skeleton className="h-8 w-16" />
      {rows > 0 && (
        <div className="space-y-2">
          {widths.map((width, i) => (
            <Skeleton key={i} className="h-3" style={{ width }} />
          ))}
        </div>
      )}
    </motion.div>
  )
}

interface SkeletonTableProps {
  rows?: number
  columns?: number
  className?: string
}

export function SkeletonTable({ rows = 5, columns = 4, className }: SkeletonTableProps) {
  return (
    <div className={cn('w-full space-y-3', className)}>
      {/* Header */}
      <div className="flex gap-4">
        {Array.from({ length: columns }).map((_, i) => (
          <Skeleton key={`header-${i}`} className="h-4 flex-1" />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <motion.div
          key={`row-${rowIndex}`}
          className="flex gap-4 items-center"
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: rowIndex * 0.03, duration: 0.3 }}
        >
          {Array.from({ length: columns }).map((_, colIndex) => (
            <Skeleton
              key={`cell-${rowIndex}-${colIndex}`}
              className="h-10 flex-1 rounded-lg"
              style={{ opacity: 0.5 + (rowIndex % 2) * 0.2 }}
            />
          ))}
        </motion.div>
      ))}
    </div>
  )
}

interface SkeletonStatCardProps {
  className?: string
}

export function SkeletonStatCard({ className }: SkeletonStatCardProps) {
  return (
    <motion.div
      className={cn('bubble p-5', className)}
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: 'spring', stiffness: 120, damping: 14 }}
    >
      <div className="flex items-start justify-between">
        <div className="space-y-3 flex-1">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-3 w-24" />
        </div>
        <Skeleton className="h-10 w-10 rounded-xl" />
      </div>
    </motion.div>
  )
}
