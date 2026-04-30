import { useMemo } from 'react';
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
  value: number;
}

export interface AreaChartProps {
  data: AreaChartDataPoint[];
  dataKey?: string;
  color?: string;
  gradient?: boolean;
  height?: number;
  showAxis?: boolean;
  showGrid?: boolean;
  showTooltip?: boolean;
  strokeWidth?: number;
  fillOpacity?: number;
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

export function MetricsAreaChart({
  data,
  dataKey = 'value',
  color = 'var(--primary)',
  gradient = true,
  height = 200,
  showAxis = true,
  showGrid = true,
  showTooltip = true,
  strokeWidth = 2,
  fillOpacity = 0.15,
  className,
}: AreaChartProps) {
  const chartColors = useMemo(() => {
    const resolvedColor = color;
    return {
      stroke: resolvedColor,
      fill: resolvedColor,
      grid: 'var(--border)',
      axis: 'var(--muted-foreground)',
    };
  }, [color]);

  const gradientId = useMemo(() => `area-gradient-${Math.random().toString(36).slice(2, 9)}`, []);

  return (
    <div className={className} style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
          {gradient && (
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={chartColors.fill} stopOpacity={fillOpacity * 2} />
                <stop offset="100%" stopColor={chartColors.fill} stopOpacity={0} />
              </linearGradient>
            </defs>
          )}
          {showGrid && (
            <CartesianGrid
              strokeDasharray="3 3"
              stroke={chartColors.grid}
              strokeOpacity={0.3}
              vertical={false}
            />
          )}
          {showAxis && (
            <>
              <XAxis
                dataKey="timestamp"
                stroke={chartColors.axis}
                tick={{ fill: chartColors.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: chartColors.grid, strokeOpacity: 0.3 }}
                minTickGap={30}
              />
              <YAxis
                stroke={chartColors.axis}
                tick={{ fill: chartColors.axis, fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={40}
              />
            </>
          )}
          {showTooltip && <Tooltip content={<CustomTooltip />} />}
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={chartColors.stroke}
            strokeWidth={strokeWidth}
            fill={gradient ? `url(#${gradientId})` : chartColors.fill}
            fillOpacity={gradient ? 1 : fillOpacity}
            animationDuration={800}
            animationEasing="ease-out"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
