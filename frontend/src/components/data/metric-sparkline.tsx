// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { cn } from '../../lib/utils'

interface SparklineProps {
  data: number[]
  width?: number
  height?: number
  color?: string
  fill?: boolean
  className?: string
}

export function MetricSparkline({
  data,
  width = 80,
  height = 24,
  color = 'var(--primary)',
  fill = false,
  className,
}: SparklineProps) {
  if (data.length < 2) return null

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1

  const padding = 2
  const chartWidth = width - padding * 2
  const chartHeight = height - padding * 2

  const points = data.map((value, index) => {
    const x = padding + (index / (data.length - 1)) * chartWidth
    const y = padding + chartHeight - ((value - min) / range) * chartHeight
    return `${x},${y}`
  })

  const pathD = `M ${points.join(' L ')}`

  // Create fill path
  const fillPath = fill
    ? `${pathD} L ${padding + chartWidth},${padding + chartHeight} L ${padding},${padding + chartHeight} Z`
    : undefined

  return (
    <svg
      width={width}
      height={height}
      className={cn('overflow-visible', className)}
      viewBox={`0 0 ${width} ${height}`}
    >
      {fill && fillPath && (
        <path d={fillPath} fill={color} fillOpacity={0.1} className="transition-all duration-500" />
      )}
      <path
        d={pathD}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="transition-all duration-500"
      >
        <animate
          attributeName="stroke-dasharray"
          from={`0, ${width * 2}`}
          to={`${width * 2}, 0`}
          dur="1s"
          fill="freeze"
          calcMode="spline"
          keySplines="0.22 1 0.36 1"
        />
      </path>
      {/* End dot */}
      <circle
        cx={points[points.length - 1].split(',')[0]}
        cy={points[points.length - 1].split(',')[1]}
        r={2}
        fill={color}
        className="animate-pulse"
      />
    </svg>
  )
}
