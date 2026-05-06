import type { LucideIcon } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';
import { MetricSparkline } from './metric-sparkline';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { useEffect, useState, useRef } from 'react';

// Simple animated number component to replace react-countup
function AnimatedNumber({ 
  value, 
  duration = 2000, 
  decimals = 0,
  suffix = '',
  separator = ','
}: { 
  value: number; 
  duration?: number; 
  decimals?: number;
  suffix?: string;
  separator?: string;
}) {
  const [displayValue, setDisplayValue] = useState(0);
  const startTime = useRef<number | null>(null);
  const startValue = useRef(0);
  const rafId = useRef<number | null>(null);

  useEffect(() => {
    const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);
    
    const animate = (timestamp: number) => {
      if (!startTime.current) {
        startTime.current = timestamp;
        startValue.current = displayValue;
      }
      
      const elapsed = timestamp - startTime.current;
      const progress = Math.min(elapsed / duration, 1);
      const easedProgress = easeOutCubic(progress);
      
      const currentValue = startValue.current + (value - startValue.current) * easedProgress;
      setDisplayValue(currentValue);
      
      if (progress < 1) {
        rafId.current = requestAnimationFrame(animate);
      }
    };
    
    rafId.current = requestAnimationFrame(animate);
    
    return () => {
      if (rafId.current) {
        cancelAnimationFrame(rafId.current);
      }
    };
  }, [value, duration]);

  const formatNumber = (num: number) => {
    const fixed = num.toFixed(decimals);
    const parts = fixed.split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, separator);
    return parts.join('.') + suffix;
  };

  return <span>{formatNumber(displayValue)}</span>;
}

export interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  iconColor?: string;
  bgColor?: string;
  variant?: 'default' | 'mini' | 'compact';
  trend?: { value: number; direction: 'up' | 'down' };
  sparkline?: number[];
  animate?: boolean;
}

export function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  iconColor = 'text-primary',
  bgColor = 'bg-primary/10',
  variant = 'default',
  trend,
  sparkline,
  animate = true,
}: StatCardProps) {
  // Parse numeric value for CountUp
  const numericValue = typeof value === 'number' ? value : parseFloat(value.replace(/[^0-9.-]/g, ''));
  const isNumeric = !isNaN(numericValue);
  const suffix = typeof value === 'string' ? value.replace(/[0-9.-]/g, '') : '';

  if (variant === 'mini') {
    return (
      <div className="flex items-center gap-3 px-3 py-2">
        <div className={cn("p-2 rounded-lg", bgColor)}>
          <Icon className={cn("w-4 h-4", iconColor)} />
        </div>
        <div>
          <p className="text-sm font-medium">{value}</p>
          <p className="text-xs text-muted-foreground">{title}</p>
        </div>
      </div>
    );
  }

  if (variant === 'compact') {
    return (
      <motion.div
        className="bubble p-4 hover-lift cursor-default group"
        whileHover={{ y: -2, transition: { type: 'spring', stiffness: 300, damping: 20 } }}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring', stiffness: 120, damping: 14 }}
      >
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{title}</p>
            <p className="text-xl font-bold tracking-tight">
              {isNumeric && animate ? (
                <AnimatedNumber
                  value={numericValue}
                  duration={2000}
                  decimals={numericValue % 1 !== 0 ? 2 : 0}
                  suffix={suffix}
                />
              ) : (
                value
              )}
            </p>
          </div>
          <div className={cn("p-2.5 rounded-lg", bgColor)}>
            <Icon className={cn("w-4 h-4", iconColor)} />
          </div>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      className="bubble p-5 hover-lift cursor-default group relative overflow-hidden"
      whileHover={{ y: -2, transition: { type: 'spring', stiffness: 300, damping: 20 } }}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 120, damping: 14 }}
    >
      {/* Hover tint overlay */}
      <div 
        className="pointer-events-none absolute inset-0 bg-gradient-to-br from-current/5 via-transparent to-transparent opacity-0 transition-opacity duration-200 group-hover:opacity-100"
        style={{ color: 'var(--primary)' }}
      />
      
      <div className="relative flex items-start justify-between">
        <div className="space-y-3 flex-1">
          <p className="text-sm font-medium text-muted-foreground tracking-wide">{title}</p>
          <p className="text-3xl font-bold tracking-tight tabular-nums">
            {isNumeric && animate ? (
              <AnimatedNumber
                value={numericValue}
                duration={2000}
                decimals={numericValue % 1 !== 0 ? 2 : 0}
                suffix={suffix}
              />
            ) : (
              value
            )}
          </p>
          
          {subtitle && (
            <div className="flex items-center gap-2">
              <p className="text-xs text-muted-foreground">{subtitle}</p>
              {trend && (
                <motion.div
                  className={cn(
                    "flex items-center gap-0.5 text-xs font-medium",
                    trend.direction === 'up' ? 'text-emerald-400' : 'text-red-400'
                  )}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ type: 'spring', delay: 0.5 }}
                >
                  {trend.direction === 'up' ? (
                    <TrendingUp className="w-3 h-3" />
                  ) : (
                    <TrendingDown className="w-3 h-3" />
                  )}
                  <span>{trend.value}%</span>
                </motion.div>
              )}
            </div>
          )}
          
          {sparkline && sparkline.length > 1 && (
            <div className="pt-2">
              <MetricSparkline 
                data={sparkline} 
                width={120} 
                height={30} 
                color="currentColor"
                fill 
              />
            </div>
          )}
        </div>
        <div
          className={cn(
            "flex items-center justify-center w-10 h-10 rounded-full transition-all duration-200",
            bgColor,
            "group-hover:bg-primary/10 group-hover:-translate-y-[1px]"
          )}
        >
          <Icon className={cn("w-5 h-5", iconColor)} />
        </div>
      </div>
    </motion.div>
  );
}
