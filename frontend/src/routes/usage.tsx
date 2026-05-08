import { createFileRoute } from '@tanstack/react-router';
import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Activity,
  CreditCard,
  TrendingUp,
  Calendar,
} from 'lucide-react';
import { useUserUsage } from '../hooks/use-analytics';
import { useCurrentUser } from '../hooks/use-current-user';
import { MetricsAreaChart, formatters } from '../components/charts/area-chart';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';

export const Route = createFileRoute('/usage')({
  component: UsagePage,
});

function UsagePage() {
  const { data: user } = useCurrentUser();
  const [days, setDays] = useState(30);
  const { data: usage, isLoading } = useUserUsage(user?.id || '', days);

  const cpuData = usage?.daily_usage?.map((d) => ({
    timestamp: d.date,
    cpu: d.avg_cpu,
    memory: d.avg_memory,
  })) || [];

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="flex flex-col md:flex-row md:items-center md:justify-between gap-4"
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <Activity className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Usage Trends</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Your server usage and NUKE consumption over time
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                days === d
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              )}
            >
              {d}d
            </button>
          ))}
        </div>
      </motion.div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <motion.div
          className="bubble p-5"
          whileHover={{ y: -4, transition: springs.gentle }}
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          transition={springs.gentle}
        >
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 rounded-lg bg-chart-1/10">
              <CreditCard className="w-4 h-4 text-chart-1" />
            </div>
            <span className="text-sm font-medium text-muted-foreground">Total Cost</span>
          </div>
          <p className="text-2xl font-bold tabular-nums">
            {isLoading ? '...' : `${usage?.total_cost || 0} NUKE`}
          </p>
          <p className="text-xs text-muted-foreground mt-1">Last {days} days</p>
        </motion.div>

        <motion.div
          className="bubble p-5"
          whileHover={{ y: -4, transition: springs.gentle }}
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          transition={{ delay: 0.1, ...springs.gentle }}
        >
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 rounded-lg bg-chart-2/10">
              <TrendingUp className="w-4 h-4 text-chart-2" />
            </div>
            <span className="text-sm font-medium text-muted-foreground">Data Points</span>
          </div>
          <p className="text-2xl font-bold tabular-nums">
            {isLoading
              ? '...'
              : usage?.daily_usage?.reduce((sum, d) => sum + d.data_points, 0) || 0}
          </p>
          <p className="text-xs text-muted-foreground mt-1">Metric readings</p>
        </motion.div>

        <motion.div
          className="bubble p-5"
          whileHover={{ y: -4, transition: springs.gentle }}
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          transition={{ delay: 0.2, ...springs.gentle }}
        >
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 rounded-lg bg-chart-3/10">
              <Calendar className="w-4 h-4 text-chart-3" />
            </div>
            <span className="text-sm font-medium text-muted-foreground">Active Days</span>
          </div>
          <p className="text-2xl font-bold tabular-nums">
            {isLoading ? '...' : usage?.daily_usage?.length || 0}
          </p>
          <p className="text-xs text-muted-foreground mt-1">With recorded activity</p>
        </motion.div>
      </div>

      {/* CPU Usage Chart */}
      <motion.div
        className="bubble p-5 overflow-hidden"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3, ...springs.gentle }}
      >
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-base font-semibold">CPU Usage</h3>
            <p className="text-sm text-muted-foreground mt-0.5">Average CPU utilization per day</p>
          </div>
          <Activity className="w-4 h-4 text-muted-foreground mt-1" />
        </div>
        <MetricsAreaChart
          data={cpuData}
          series={[{ key: 'cpu', name: 'CPU %', color: 'var(--chart-1)' }]}
          height={280}
          yTickFormatter={formatters.percent}
        />
      </motion.div>

      {/* Memory Usage Chart */}
      <motion.div
        className="bubble p-5 overflow-hidden"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4, ...springs.gentle }}
      >
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-base font-semibold">Memory Usage</h3>
            <p className="text-sm text-muted-foreground mt-0.5">Average memory utilization per day</p>
          </div>
          <Activity className="w-4 h-4 text-muted-foreground mt-1" />
        </div>
        <MetricsAreaChart
          data={cpuData}
          series={[{ key: 'memory', name: 'Memory %', color: 'var(--chart-2)' }]}
          height={280}
          yTickFormatter={formatters.percent}
        />
      </motion.div>
    </div>
  );
}
