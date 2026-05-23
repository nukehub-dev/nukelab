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
  LabelList,
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
  showValues?: boolean;
  barSize?: number;
  radius?: number | [number, number, number, number];
  className?: string;
  name?: string;
  color?: string;
  xAxisLabel?: string;
  yAxisLabel?: string;
}

function CustomTooltip({
  active,
  payload,
  label,
  name,
}: TooltipProps<number, string> & { name?: string }) {
  if (!active || !payload || !payload.length) return null;

  const entry = payload[0];
  const value =
    typeof entry.value === 'number'
      ? Number.isInteger(entry.value)
        ? entry.value
        : entry.value.toFixed(2)
      : entry.value;

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
        <span className="text-xs text-muted-foreground">
          {name || entry.name || 'Value'}
        </span>
        <span className="font-semibold" style={{ color: 'var(--primary)' }}>
          {value}
        </span>
      </div>
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
  showValues = true,
  barSize = 24,
  radius = 6,
  className,
  name,
  color,
  xAxisLabel,
  yAxisLabel,
}: BarChartProps) {
  const chartColors = useMemo(
    () => ({
      grid: 'var(--border)',
      axis: 'var(--muted-foreground)',
    }),
    []
  );

  const barFill = color || 'var(--primary)';

  return (
    <div className={className} style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout={horizontal ? 'vertical' : 'horizontal'}
          margin={{
            top: showValues ? 16 : 5,
            right: showValues ? 30 : 10,
            bottom: showAxis ? 36 : 5,
            left: showAxis ? (horizontal ? 100 : 10) : 5,
          }}
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
                label={
                  xAxisLabel && !horizontal
                    ? {
                        value: xAxisLabel,
                        position: 'insideBottom',
                        offset: -22,
                        style: {
                          fill: 'var(--muted-foreground)',
                          fontSize: 11,
                          fontWeight: 500,
                        },
                      }
                    : xAxisLabel && horizontal
                      ? {
                          value: xAxisLabel,
                          position: 'insideBottom',
                          offset: -22,
                          style: {
                            fill: 'var(--muted-foreground)',
                            fontSize: 11,
                            fontWeight: 500,
                          },
                        }
                      : undefined
                }
              />
              <YAxis
                type={horizontal ? 'category' : 'number'}
                dataKey={horizontal ? 'label' : undefined}
                stroke={chartColors.axis}
                tick={{ fill: chartColors.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={horizontal ? 90 : 36}
                label={
                  yAxisLabel && horizontal
                    ? {
                        value: yAxisLabel,
                        angle: -90,
                        position: 'insideLeft',
                        offset: -80,
                        style: {
                          fill: 'var(--muted-foreground)',
                          fontSize: 11,
                          fontWeight: 500,
                          textAnchor: 'middle',
                        },
                      }
                    : yAxisLabel && !horizontal
                      ? {
                          value: yAxisLabel,
                          angle: -90,
                          position: 'insideLeft',
                          offset: -30,
                          style: {
                            fill: 'var(--muted-foreground)',
                            fontSize: 11,
                            fontWeight: 500,
                            textAnchor: 'middle',
                          },
                        }
                      : undefined
                }
              />
            </>
          )}
          {showTooltip && (
            <Tooltip
              content={<CustomTooltip name={name} />}
              cursor={{ fill: 'var(--muted)', opacity: 0.2 }}
            />
          )}
          <Bar
            dataKey="value"
            name={name || 'Value'}
            barSize={barSize}
            radius={
              Array.isArray(radius)
                ? radius
                : horizontal
                  ? [0, radius, radius, 0]
                  : [radius, radius, 0, 0]
            }
            animationDuration={800}
            animationEasing="ease-out"
            fill={barFill}
          >
            {!color &&
              data.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={entry.color || DEFAULT_COLORS[index % DEFAULT_COLORS.length]}
                />
              ))}
            {showValues && (
              <LabelList
                dataKey="value"
                position={horizontal ? 'right' : 'top'}
                style={{
                  fill: 'var(--muted-foreground)',
                  fontSize: 11,
                  fontWeight: 500,
                }}
              />
            )}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
