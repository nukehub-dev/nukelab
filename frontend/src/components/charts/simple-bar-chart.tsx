import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

export interface SimpleBarData {
  label: string;
  value: number;
  color?: string;
}

export interface SimpleBarChartProps {
  data: SimpleBarData[];
  height?: number;
  name?: string;
  className?: string;
}

export function SimpleBarChart({
  data,
  height = 240,
  className,
}: SimpleBarChartProps) {
  const maxValue = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className={cn('w-full', className)} style={{ height }}>
      <div className="flex flex-col justify-center h-full gap-4">
        {data.map((item, index) => {
          const pct = (item.value / maxValue) * 100;
          return (
            <div key={item.label} className="flex items-center gap-3">
              {/* Label */}
              <span className="text-xs text-muted-foreground w-16 text-right shrink-0 truncate">
                {item.label}
              </span>

              {/* Bar track */}
              <div className="flex-1 h-8 bg-muted/50 rounded-md overflow-hidden relative">
                <motion.div
                  className="h-full rounded-md flex items-center justify-end pr-2"
                  style={{
                    backgroundColor: item.color || 'var(--chart-1)',
                    width: `${Math.max(pct, 4)}%`,
                  }}
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.max(pct, 4)}%` }}
                  transition={{ duration: 0.6, ease: 'easeOut', delay: index * 0.05 }}
                >
                  {pct > 25 && (
                    <span className="text-xs font-semibold text-white drop-shadow-sm">
                      {item.value}
                    </span>
                  )}
                </motion.div>
                {pct <= 25 && (
                  <span className="absolute inset-y-0 right-2 flex items-center text-xs font-medium text-muted-foreground">
                    {item.value}
                  </span>
                )}
              </div>
            </div>
          );
        })}

        {data.length === 0 && (
          <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
            No data available
          </div>
        )}
      </div>
    </div>
  );
}
