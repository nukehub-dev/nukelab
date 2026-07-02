// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMemo } from 'react'
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'

export interface GaugeChartProps {
  value: number // 0-100
  max?: number
  label?: string
  warningAt?: number
  criticalAt?: number
  size?: number
  strokeWidth?: number
  showValue?: boolean
  className?: string
}

export function GaugeChart({
  value,
  max = 100,
  label,
  warningAt = 70,
  criticalAt = 90,
  size = 160,
  strokeWidth = 12,
  showValue = true,
  className,
}: GaugeChartProps) {
  const safeValue = Number(value) || 0
  const safeMax = Number(max) || 100
  const percentage = Math.min(Math.max((safeValue / safeMax) * 100, 0), 100)

  const color = useMemo(() => {
    if (percentage >= criticalAt) return 'var(--destructive)'
    if (percentage >= warningAt) return 'var(--chart-3)'
    return 'var(--chart-2)'
  }, [percentage, warningAt, criticalAt])

  const data = useMemo(
    () => [
      { name: 'value', value: percentage },
      { name: 'empty', value: 100 - percentage },
    ],
    [percentage]
  )

  const trackColor = 'var(--muted)'
  const trackOpacity = 0.2

  return (
    <div
      className={`relative inline-flex items-center justify-center ${className || ''}`}
      style={{ width: size, height: size }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            startAngle={180}
            endAngle={0}
            innerRadius={(size - strokeWidth) / 2 - 10}
            outerRadius={(size - strokeWidth) / 2}
            stroke="none"
            paddingAngle={0}
            dataKey="value"
            animationDuration={1000}
            animationEasing="ease-out"
          >
            <Cell fill={color} />
            <Cell fill={trackColor} fillOpacity={trackOpacity} />
          </Pie>
        </PieChart>
      </ResponsiveContainer>

      {/* Center content */}
      <div className="absolute inset-0 flex flex-col items-center justify-center pt-4">
        {showValue && (
          <span className="text-2xl font-bold tabular-nums" style={{ color }}>
            {percentage.toFixed(1)}%
          </span>
        )}
        {label && <span className="text-xs text-muted-foreground mt-0.5">{label}</span>}
      </div>
    </div>
  )
}
