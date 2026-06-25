import { cn } from '../../lib/utils'

interface SemiCircularGaugeProps {
  value: number
  max?: number
  width?: number
  height?: number
  strokeWidth?: number
  color?: string
  bgColor?: string
  showValue?: boolean
  className?: string
}

export function SemiCircularGauge({
  value,
  max = 100,
  width = 80,
  height = 48,
  strokeWidth = 6,
  color = 'var(--chart-2)',
  bgColor = 'var(--border)',
  showValue = false,
  className,
}: SemiCircularGaugeProps) {
  const radius = (width - strokeWidth) / 2
  const circumference = Math.PI * radius // Half circle
  const percentage = Math.min(Math.max((value / max) * 100, 0), 100)
  const offset = circumference - (percentage / 100) * circumference

  // Determine color based on percentage
  const getColor = () => {
    if (percentage >= 90) return 'var(--destructive)'
    if (percentage >= 70) return 'var(--chart-3)'
    return color
  }

  const centerY = height - strokeWidth / 2

  return (
    <div className={cn('relative inline-flex flex-col items-center', className)}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        {/* Background arc */}
        <path
          d={`M ${strokeWidth / 2} ${centerY} A ${radius} ${radius} 0 0 1 ${width - strokeWidth / 2} ${centerY}`}
          fill="none"
          stroke={bgColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          opacity={0.3}
        />
        {/* Progress arc */}
        <path
          d={`M ${strokeWidth / 2} ${centerY} A ${radius} ${radius} 0 0 1 ${width - strokeWidth / 2} ${centerY}`}
          fill="none"
          stroke={getColor()}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{
            transition: 'stroke-dashoffset 0.5s ease-out, stroke 0.3s ease',
          }}
        />
      </svg>
      {showValue && (
        <span className="absolute bottom-0 text-[10px] font-semibold tabular-nums">
          {Math.round(percentage)}%
        </span>
      )}
    </div>
  )
}
