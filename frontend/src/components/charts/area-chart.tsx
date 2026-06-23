import { useMemo, useId } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  type TooltipProps,
} from 'recharts';

export interface AreaChartDataPoint {
  timestamp: string;
  [key: string]: string | number;
}

export interface ChartSeries {
  key: string;
  name: string;
  color: string;
}

export interface TooltipItem {
  label: string;
  value: string | number;
  color?: string;
}

export interface AreaChartProps {
  data: AreaChartDataPoint[];
  series: ChartSeries[];
  height?: number;
  showGrid?: boolean;
  showTooltip?: boolean;
  fillOpacity?: number;
  className?: string;
  yTickFormatter?: (value: number) => string;
  xTickFormatter?: (value: string) => string;
  tooltipFormatter?: (data: AreaChartDataPoint) => TooltipItem[];
}

interface CustomTooltipProps extends TooltipProps<number, string> {
  series: ChartSeries[];
  tooltipFormatter?: (data: AreaChartDataPoint) => TooltipItem[];
  yTickFormatter?: (value: number) => string;
}

function CustomTooltip({ active, payload, label, series, tooltipFormatter, yTickFormatter }: CustomTooltipProps) {
  if (!active || !payload || !payload.length) return null;

  // Get the full data point for custom tooltip
  const dataPoint = payload[0]?.payload as AreaChartDataPoint | undefined;
  const customItems = tooltipFormatter && dataPoint ? tooltipFormatter(dataPoint) : null;

  return (
    <div
      className="rounded-lg border px-3 py-2 text-sm shadow-lg"
      style={{
        background: 'var(--popover)',
        borderColor: 'var(--border)',
        color: 'var(--popover-foreground)',
      }}
    >
      <p className="font-medium text-muted-foreground mb-2">
        {typeof label === 'string' && label.includes('T')
          ? new Date(label).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
          : label}
      </p>
      <div className="space-y-1">
        {customItems ? (
          // Custom tooltip items
          <>
            {customItems.map((item, index) => (
              <div key={index}>
                {index === customItems.length - 1 && customItems.length > 1 && (
                  <div className="border-t border-border my-1.5" />
                )}
                <div className="flex items-center justify-between gap-4">
                  <div className="flex items-center gap-2">
                    {item.color && (
                      <div
                        className="w-1 h-3 rounded-sm"
                        style={{ backgroundColor: item.color }}
                      />
                    )}
                    <span className="text-xs">{item.label}</span>
                  </div>
                  <span className="font-semibold text-xs">{item.value}</span>
                </div>
              </div>
            ))}
          </>
        ) : (
          // Default tooltip items - use yTickFormatter for value formatting
          payload.map((entry, index) => {
            const seriesName = series.find(s => s.key === entry.dataKey)?.name || entry.dataKey;
            const value = typeof entry.value === 'number' 
              ? (yTickFormatter ? yTickFormatter(entry.value) : entry.value.toFixed(2))
              : entry.value;
            return (
              <div key={index} className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-2">
                  <div
                    className="w-1 h-3 rounded-sm"
                    style={{ backgroundColor: entry.color }}
                  />
                  <span className="text-xs">{seriesName}</span>
                </div>
                <span className="font-semibold text-xs">{value}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export function MetricsAreaChart({
  data,
  series,
  height = 240,
  showGrid = true,
  showTooltip = true,
  fillOpacity = 0.15,
  className,
  yTickFormatter,
  xTickFormatter,
  tooltipFormatter,
}: AreaChartProps) {
  const chartColors = useMemo(() => ({
    grid: 'var(--border)',
    axis: 'var(--muted-foreground)',
  }), []);

  const idPrefix = useId();

  const gradientIds = useMemo(() =>
    series.map((_, i) => `area-gradient-${idPrefix}-${i}`),
    [series, idPrefix]
  );

  // Calculate nice Y-axis ticks
  const allValues = data.flatMap(d => series.map(s => Number(d[s.key]) || 0));
  const maxValue = Math.max(...allValues, 1);
  const minValue = Math.min(...allValues, 0);
  const range = maxValue - minValue;
  const tickCount = 5;
  const step = range / (tickCount - 1) || 1;
  const domainMax = maxValue + step * 0.1;

  return (
    <div className={className} style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart
          data={data}
          margin={{ top: 10, right: 10, bottom: 10, left: 10 }}
        >
          <defs>
            {series.map((s, i) => (
              <linearGradient
                key={gradientIds[i]}
                id={gradientIds[i]}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop offset="0%" stopColor={s.color} stopOpacity={fillOpacity * 2} />
                <stop offset="100%" stopColor={s.color} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          
          {showGrid && (
            <CartesianGrid
              strokeDasharray="3 3"
              stroke={chartColors.grid}
              strokeOpacity={0.2}
              vertical={false}
            />
          )}
          
          <XAxis
            dataKey="timestamp"
            stroke={chartColors.axis}
            tick={{ fill: chartColors.axis, fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: chartColors.grid, strokeOpacity: 0.3 }}
            minTickGap={40}
            tickFormatter={xTickFormatter}
          />
          
          <YAxis
            stroke={chartColors.axis}
            tick={{ fill: chartColors.axis, fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={60}
            domain={[0, domainMax]}
            tickFormatter={yTickFormatter}
            tickCount={tickCount}
          />
          
          {showTooltip && (
            <Tooltip
              content={<CustomTooltip series={series} tooltipFormatter={tooltipFormatter} yTickFormatter={yTickFormatter} />}
              wrapperStyle={{ outline: 'none' }}
            />
          )}
          
          {series.map((s, i) => (
            <Area
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.name}
              stroke={s.color}
              strokeWidth={2}
              fill={`url(#${gradientIds[i]})`}
              fillOpacity={1}
              animationDuration={800}
              animationEasing="ease-out"
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
