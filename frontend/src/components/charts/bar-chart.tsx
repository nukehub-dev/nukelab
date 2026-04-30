import { useMemo } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  type TooltipProps,
} from 'recharts';

export interface BarChartDataPoint {
  label: string;
  value: number;
  color?: string;
}

export interface BarChartProps {
  data: BarChartDataPoint[];
  horizontal?: boolean;
  height?: number;
  showAxis?: boolean;
  showGrid?: boolean;
  showTooltip?: boolean;
  barSize?: number;
  radius?: number;
  className?: string;
}

function CustomTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload || !payload.length) return null;

  return (
    <div
      className="rounded-lg border px-3 py-2 text-sm shadow-lg"
      style={{
        background: 'var(--popover)',
        borderColor: 'var(--border)',
        color: 'var(--popover-foreground)',
      }}
    >
      <p className="font-medium text-muted-foreground mb-1">{label}</p>
      <p className="font-semibold" style={{ color: 'var(--primary)' }}>
        {typeof payload[0].value === 'number' ? payload[0].value.toFixed(2) : payload[0].value}
      </p>
    </div>
  );
}

const DEFAULT_COLORS = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
];

export function MetricsBarChart({
  data,
  horizontal = false,
  height = 200,
  showAxis = true,
  showGrid = true,
  showTooltip = true,
  barSize = 24,
  radius = 6,
  className,
}: BarChartProps) {
  const chartColors = useMemo(() => ({
    grid: 'var(--border)',
    axis: 'var(--muted-foreground)',
  }), []);

  return (
    <div className={className} style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout={horizontal ? 'vertical' : 'horizontal'}
          margin={{ top: 5, right: 5, bottom: 5, left: 5 }}
        >
          {showGrid && (
            <CartesianGrid
              strokeDasharray="3 3"
              stroke={chartColors.grid}
              strokeOpacity={0.3}
              vertical={!horizontal}
              horizontal={horizontal}
            />
          )}
          {showAxis && (
            <>
              <XAxis
                type={horizontal ? 'number' : 'category'}
                dataKey={horizontal ? undefined : 'label'}
                stroke={chartColors.axis}
                tick={{ fill: chartColors.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: chartColors.grid, strokeOpacity: 0.3 }}
                minTickGap={30}
              />
              <YAxis
                type={horizontal ? 'category' : 'number'}
                dataKey={horizontal ? 'label' : undefined}
                stroke={chartColors.axis}
                tick={{ fill: chartColors.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={horizontal ? 80 : 40}
              />
            </>
          )}
          {showTooltip && <Tooltip content={<CustomTooltip />} cursor={{ fill: 'var(--muted)', opacity: 0.2 }} />}
          <Bar
            dataKey="value"
            barSize={barSize}
            radius={[radius, radius, radius, radius]}
            animationDuration={800}
            animationEasing="ease-out"
          >
            {data.map((entry, index) => (
              <Cell
                key={`cell-${index}`}
                fill={entry.color || DEFAULT_COLORS[index % DEFAULT_COLORS.length]}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
