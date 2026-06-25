import { useMemo } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LabelList,
  type TooltipProps,
} from 'recharts'

export interface TimeSeriesBarPoint {
  label: string
  value: number
}

export interface TimeSeriesBarChartProps {
  data: TimeSeriesBarPoint[]
  height?: number
  name?: string
  color?: string
  className?: string
}

function CustomTooltip({
  active,
  payload,
  label,
  name,
}: TooltipProps<number, string> & { name?: string }) {
  if (!active || !payload || !payload.length) return null

  const entry = payload[0]
  const value =
    typeof entry.value === 'number'
      ? Number.isInteger(entry.value)
        ? entry.value
        : entry.value.toFixed(2)
      : entry.value

  return (
    <div
      className="rounded-lg border px-3 py-2 text-sm shadow-lg"
      style={{
        background: 'var(--popover)',
        borderColor: 'var(--border)',
        color: 'var(--popover-foreground)',
      }}
    >
      <p className="font-medium text-muted-foreground mb-2">{label}</p>
      <div className="flex items-center gap-2">
        <div
          className="w-2 h-4 rounded-sm"
          style={{ backgroundColor: entry.color || 'var(--primary)' }}
        />
        <span className="text-xs text-muted-foreground">{name || entry.name || 'Value'}</span>
        <span className="font-semibold" style={{ color: 'var(--primary)' }}>
          {value}
        </span>
      </div>
    </div>
  )
}

export function TimeSeriesBarChart({
  data,
  height = 240,
  name = 'Value',
  color = 'var(--chart-1)',
  className,
}: TimeSeriesBarChartProps) {
  const chartColors = useMemo(
    () => ({
      grid: 'var(--border)',
      axis: 'var(--muted-foreground)',
    }),
    []
  )

  // For many data points, skip some X-axis labels to avoid overlap
  const labelInterval = useMemo(() => {
    if (data.length <= 7) return 0
    if (data.length <= 14) return 1
    if (data.length <= 30) return 2
    if (data.length <= 60) return 4
    return Math.floor(data.length / 10)
  }, [data.length])

  // Determine if we need angled labels
  const shouldAngleLabels = data.length > 7

  return (
    <div className={className} style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{
            top: 16,
            right: 10,
            bottom: shouldAngleLabels ? 50 : 30,
            left: 4,
          }}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke={chartColors.grid}
            strokeOpacity={0.3}
            vertical={false}
          />
          <XAxis
            dataKey="label"
            stroke={chartColors.axis}
            tick={{
              fill: chartColors.axis,
              fontSize: 10,
            }}
            tickLine={false}
            axisLine={{ stroke: chartColors.grid, strokeOpacity: 0.3 }}
            interval={labelInterval}
            angle={shouldAngleLabels ? -45 : 0}
            textAnchor={shouldAngleLabels ? 'end' : 'middle'}
            height={shouldAngleLabels ? 50 : 30}
          />
          <YAxis
            stroke={chartColors.axis}
            tick={{ fill: chartColors.axis, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={36}
            allowDecimals={false}
          />
          <Tooltip
            content={<CustomTooltip name={name} />}
            cursor={{ fill: 'var(--muted)', opacity: 0.2 }}
          />
          <Bar
            dataKey="value"
            name={name}
            radius={[4, 4, 0, 0]}
            animationDuration={800}
            animationEasing="ease-out"
            fill={color}
          >
            <LabelList
              dataKey="value"
              position="top"
              style={{
                fill: 'var(--muted-foreground)',
                fontSize: 10,
                fontWeight: 500,
              }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
