// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { cn } from '../../lib/utils'

export interface Segment {
  label: string
  value: number
  color: string
}

export interface SegmentedBarProps {
  segments: Segment[]
  total?: number
  height?: number
  showLegend?: boolean
  className?: string
}

export function SegmentedBar({
  segments,
  total,
  height = 24,
  showLegend = true,
  className,
}: SegmentedBarProps) {
  const computedTotal = total ?? segments.reduce((sum, s) => sum + s.value, 0)

  return (
    <div className={cn('space-y-3', className)}>
      <div className="flex w-full rounded-full overflow-hidden" style={{ height }}>
        {segments.map((segment) => {
          const pct = computedTotal > 0 ? (segment.value / computedTotal) * 100 : 0
          return (
            <div
              key={segment.label}
              className="relative flex items-center justify-center transition-all duration-500"
              style={{
                width: `${pct}%`,
                backgroundColor: segment.color,
                minWidth: segment.value > 0 ? 4 : 0,
              }}
              title={`${segment.label}: ${segment.value}`}
            >
              {pct > 15 && (
                <span className="text-xs font-semibold text-white drop-shadow-sm">
                  {segment.value}
                </span>
              )}
            </div>
          )
        })}
      </div>

      {showLegend && (
        <div className="flex flex-wrap gap-3">
          {segments.map((segment) => (
            <div key={segment.label} className="flex items-center gap-1.5">
              <div
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: segment.color }}
              />
              <span className="text-xs text-muted-foreground">
                {segment.label}
                <span className="ml-1 font-medium text-foreground">{segment.value}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
