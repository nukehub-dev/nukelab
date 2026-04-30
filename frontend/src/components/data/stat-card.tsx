import type { LucideIcon } from 'lucide-react';
import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: LucideIcon;
  iconColor?: string;
  bgColor?: string;
  variant?: 'default' | 'mini' | 'compact';
  trend?: { value: number; direction: 'up' | 'down' };
  sparkline?: number[];
}

export function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  iconColor = 'text-primary',
  bgColor = 'bg-primary/10',
  variant = 'default',
}: StatCardProps) {
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

  return (
    <motion.div
      className="bubble p-5 hover-lift cursor-default group"
      whileHover={{ y: -4, transition: { type: 'spring', stiffness: 300, damping: 20 } }}
    >
      <div className="flex items-start justify-between">
        <div className="space-y-3">
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          <p className="text-2xl font-bold tracking-tight">{value}</p>
          {subtitle && (
            <p className="text-sm text-muted-foreground">{subtitle}</p>
          )}
        </div>
        <motion.div
          className={cn("p-3 rounded-xl", bgColor)}
          whileHover={{ scale: 1.1, rotate: 5 }}
          transition={{ type: 'spring', stiffness: 400, damping: 17 }}
        >
          <Icon className={cn("w-5 h-5", iconColor)} />
        </motion.div>
      </div>
    </motion.div>
  );
}
