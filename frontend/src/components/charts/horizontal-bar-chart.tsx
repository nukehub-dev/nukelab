import { useState } from 'react'
import { cn } from '../../lib/utils'

export interface HorizontalBarDataPoint {
  label: string
  value: number
  color?: string
}

interface HorizontalBarChartProps {
  data: HorizontalBarDataPoint[]
  maxValue?: number
  labelWidth?: number
  barHeight?: number
  className?: string
  valueFormatter?: (value: number) => string
  showValues?: boolean
}

export function HorizontalBarChart({
  data,
  maxValue,
  labelWidth = 140,
  barHeight = 24,
  className,
  valueFormatter,
  showValues = true,
}: HorizontalBarChartProps) {
  const computedMax = maxValue ?? Math.max(...data.map((d) => d.value), 1)
  const [hovered, setHovered] = useState<number | null>(null)

  return (
    <div className={cn('space-y-1.5', className)}>
      {data.map((item, index) => {
        const percentage = computedMax > 0 ? (item.value / computedMax) * 100 : 0
        const clampedPercentage = Math.min(percentage, 100)
        const displayValue = valueFormatter ? valueFormatter(item.value) : item.value.toFixed(2)
        const isHovered = hovered === index

        return (
          <div
            key={`${item.label}-${index}`}
            className="flex items-center gap-3 relative cursor-pointer"
            onMouseEnter={() => setHovered(index)}
            onMouseLeave={() => setHovered(null)}
          >
            {/* Label */}
            <div
              className="shrink-0 text-right text-xs text-muted-foreground truncate"
              style={{ width: labelWidth }}
            >
              {item.label}
            </div>

            {/* Bar track */}
            <div className="flex-1 relative overflow-visible" style={{ height: barHeight }}>
              <div
                className="absolute inset-0 rounded-r-md"
                style={{ backgroundColor: 'var(--muted)', opacity: 0.2 }}
              />
              {/* Bar fill */}
              <div
                className="absolute left-0 top-0 h-full rounded-r-md transition-all duration-500 ease-out"
                style={{
                  width: `${clampedPercentage}%`,
                  backgroundColor: item.color || 'var(--primary)',
                  opacity: isHovered ? 1 : 0.85,
                }}
              />
              {/* Tooltip at bar end */}
              {isHovered && (
                <div
                  className="absolute z-10 pointer-events-none -top-10"
                  style={{ left: `${Math.min(clampedPercentage, 92)}%` }}
                >
                  <div
                    className="rounded-lg border px-3 py-2 text-sm shadow-lg whitespace-nowrap"
                    style={{
                      background: 'var(--popover)',
                      borderColor: 'var(--border)',
                      color: 'var(--popover-foreground)',
                    }}
                  >
                    <p className="font-medium text-muted-foreground mb-1">{item.label}</p>
                    <div className="flex items-center gap-2">
                      <div
                        className="w-2 h-4 rounded-sm"
                        style={{ backgroundColor: item.color || 'var(--primary)' }}
                      />
                      <span className="text-xs text-muted-foreground">CPU</span>
                      <span className="font-semibold" style={{ color: 'var(--primary)' }}>
                        {displayValue}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Value */}
            {showValues && (
              <div className="shrink-0 w-12 text-right text-xs text-muted-foreground tabular-nums">
                {displayValue}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
