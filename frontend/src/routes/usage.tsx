import { createFileRoute } from '@tanstack/react-router'
import { useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import {
  Activity,
  CreditCard,
  TrendingUp,
  TrendingDown,
  Calendar,
  Cpu,
  HardDrive,
  Network,
  Gauge,
  Zap,
  Server,
  Download,
  Database,
  BarChart3,
  LineChart,
} from 'lucide-react'
import { useUserUsage } from '../hooks/use-analytics'
import { useCurrentUser } from '../hooks/use-current-user'
import { MetricsAreaChart } from '../components/charts/area-chart'
import { formatters } from '../components/charts/chart-formatters'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  ResponsiveContainer,
} from 'recharts'
import { StatCard } from '../components/data/stat-card'
import { EmptyState } from '../components/feedback/empty-state'
import { Button } from '../components/ui/button'
import { DateRangePicker, type DateRange } from '../components/ui/date-range-picker'
import { exportToCSV } from '../lib/export'
import { springs } from '../lib/animations'
import { cn, formatBytes } from '../lib/utils'

export const Route = createFileRoute('/usage')({
  component: UsagePage,
})

function getDefaultDateRange(): DateRange {
  const to = new Date().toISOString().split('T')[0]
  const from = new Date()
  from.setDate(from.getDate() - 29)
  return { from: from.toISOString().split('T')[0], to }
}

function UsagePage() {
  const { data: user } = useCurrentUser()
  const [dateRange, setDateRange] = useState<DateRange>(getDefaultDateRange)
  const { data: usage, isLoading } = useUserUsage(user?.id || '', {
    from: dateRange.from,
    to: dateRange.to,
  })

  const hasData = usage && usage.daily_usage && usage.daily_usage.length > 0

  const chartData = useMemo(() => {
    if (!usage?.daily_usage) return []
    return usage.daily_usage.map((d) => ({
      timestamp: d.date,
      cpu: d.avg_cpu,
      memory: d.avg_memory,
      networkRx: d.avg_network_rx,
      networkTx: d.avg_network_tx,
      diskRead: d.avg_disk_read,
      diskWrite: d.avg_disk_write,
      peakCpu: d.peak_cpu,
      peakMemory: d.peak_memory,
    }))
  }, [usage])

  const serverBreakdownData = useMemo(() => {
    if (!usage?.server_breakdown) return []
    return usage.server_breakdown.map((s, i) => ({
      label: s.server_name,
      value: s.cost,
      color: [
        'var(--chart-1)',
        'var(--chart-2)',
        'var(--chart-3)',
        'var(--chart-4)',
        'var(--chart-5)',
      ][i % 5],
    }))
  }, [usage])

  const cpuSparkline = useMemo(() => usage?.daily_usage?.map((d) => d.avg_cpu) || [], [usage])
  const memorySparkline = useMemo(() => usage?.daily_usage?.map((d) => d.avg_memory) || [], [usage])
  const costSparkline = useMemo(() => {
    if (!usage?.daily_usage) return []
    return usage.daily_usage.map((d) => d.daily_cost)
  }, [usage])

  const handleExport = () => {
    if (!usage?.daily_usage) return
    const data = usage.daily_usage.map((d) => ({
      Date: d.date,
      'Avg CPU %': d.avg_cpu.toFixed(2),
      'Peak CPU %': d.peak_cpu.toFixed(2),
      'Avg Memory %': d.avg_memory.toFixed(2),
      'Peak Memory %': d.peak_memory.toFixed(2),
      'Network RX': d.avg_network_rx,
      'Network TX': d.avg_network_tx,
      'Disk Read': d.avg_disk_read,
      'Disk Write': d.avg_disk_write,
      'Data Points': d.data_points,
    }))
    exportToCSV(data, `usage-report-${dateRange.from}-to-${dateRange.to}`)
  }

  if (!isLoading && !hasData) {
    return (
      <div className="min-h-screen p-6 lg:p-10">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.gentle}
          className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-8"
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
        </motion.div>

        <EmptyState
          icon={BarChart3}
          title="No Usage Data Yet"
          description="You don't have any usage data for the selected period. Start using servers to collect real metrics."
        />
      </div>
    )
  }

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

        <div className="flex items-center gap-2 flex-wrap">
          <DateRangePicker value={dateRange} onChange={setDateRange} />
          <Button
            variant="outline"
            size="sm"
            className="gap-2"
            onClick={handleExport}
            disabled={!hasData}
          >
            <Download className="w-4 h-4" />
            Export
          </Button>
        </div>
      </motion.div>

      {/* KPI Cards Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Cost"
          value={`${usage?.total_cost || 0} NUKE`}
          subtitle={`Period cost`}
          icon={CreditCard}
          iconColor="text-chart-1"
          bgColor="bg-chart-1/10"
          variant="compact"
          trend={
            usage?.cost_trend
              ? {
                  value: Math.abs(usage.cost_trend),
                  direction: usage.cost_trend >= 0 ? 'up' : 'down',
                }
              : undefined
          }
          sparkline={costSparkline}
        />

        <StatCard
          title="Avg CPU"
          value={`${(usage?.peak_stats?.overall_avg_cpu || 0).toFixed(1)}%`}
          subtitle={`Peak: ${(usage?.peak_stats?.peak_cpu || 0).toFixed(1)}%`}
          icon={Cpu}
          iconColor="text-chart-2"
          bgColor="bg-chart-2/10"
          variant="compact"
          sparkline={cpuSparkline}
        />

        <StatCard
          title="Avg Memory"
          value={`${(usage?.peak_stats?.overall_avg_memory || 0).toFixed(1)}%`}
          subtitle={`Peak: ${(usage?.peak_stats?.peak_memory || 0).toFixed(1)}%`}
          icon={Database}
          iconColor="text-chart-3"
          bgColor="bg-chart-3/10"
          variant="compact"
          sparkline={memorySparkline}
        />

        <StatCard
          title="Active Days"
          value={usage?.active_days || 0}
          subtitle={`of ${usage?.period_days || 0} days`}
          icon={Calendar}
          iconColor="text-chart-4"
          bgColor="bg-chart-4/10"
          variant="compact"
        />
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* CPU Usage Chart */}
        <motion.div
          className="bubble p-5 overflow-hidden"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, ...springs.gentle }}
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold flex items-center gap-2">
                <Cpu className="w-4 h-4 text-chart-1" />
                CPU Usage
              </h3>
              <p className="text-sm text-muted-foreground mt-0.5">
                Average vs Peak CPU utilization per day
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-chart-1" />
                Avg
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-chart-3" />
                Peak
              </span>
            </div>
          </div>
          <MetricsAreaChart
            data={chartData}
            series={[
              { key: 'cpu', name: 'Avg CPU %', color: 'var(--chart-1)' },
              { key: 'peakCpu', name: 'Peak CPU %', color: 'var(--chart-3)' },
            ]}
            height={300}
            yTickFormatter={formatters.percent}
            xTickFormatter={formatters.date}
          />
        </motion.div>

        {/* Memory Usage Chart */}
        <motion.div
          className="bubble p-5 overflow-hidden"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, ...springs.gentle }}
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold flex items-center gap-2">
                <Database className="w-4 h-4 text-chart-2" />
                Memory Usage
              </h3>
              <p className="text-sm text-muted-foreground mt-0.5">
                Average vs Peak memory utilization per day
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-chart-2" />
                Avg
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-chart-4" />
                Peak
              </span>
            </div>
          </div>
          <MetricsAreaChart
            data={chartData}
            series={[
              { key: 'memory', name: 'Avg Memory %', color: 'var(--chart-2)' },
              { key: 'peakMemory', name: 'Peak Memory %', color: 'var(--chart-4)' },
            ]}
            height={300}
            yTickFormatter={formatters.percent}
            xTickFormatter={formatters.date}
          />
        </motion.div>

        {/* Network I/O Chart */}
        <motion.div
          className="bubble p-5 overflow-hidden"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, ...springs.gentle }}
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold flex items-center gap-2">
                <Network className="w-4 h-4 text-chart-4" />
                Network I/O
              </h3>
              <p className="text-sm text-muted-foreground mt-0.5">
                Daily average network throughput
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-chart-4" />
                RX
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-chart-5" />
                TX
              </span>
            </div>
          </div>
          <MetricsAreaChart
            data={chartData}
            series={[
              { key: 'networkRx', name: 'RX', color: 'var(--chart-4)' },
              { key: 'networkTx', name: 'TX', color: 'var(--chart-5)' },
            ]}
            height={300}
            yTickFormatter={(v) => formatBytes(v)}
            xTickFormatter={formatters.date}
          />
        </motion.div>

        {/* Disk I/O Chart */}
        <motion.div
          className="bubble p-5 overflow-hidden"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4, ...springs.gentle }}
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold flex items-center gap-2">
                <HardDrive className="w-4 h-4 text-chart-3" />
                Disk I/O
              </h3>
              <p className="text-sm text-muted-foreground mt-0.5">
                Daily average disk read/write activity
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-chart-3" />
                Read
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-chart-1" />
                Write
              </span>
            </div>
          </div>
          <MetricsAreaChart
            data={chartData}
            series={[
              { key: 'diskRead', name: 'Read', color: 'var(--chart-3)' },
              { key: 'diskWrite', name: 'Write', color: 'var(--chart-1)' },
            ]}
            height={300}
            yTickFormatter={(v) => formatBytes(v)}
            xTickFormatter={formatters.date}
          />
        </motion.div>
      </div>

      {/* Bottom Section: Server Breakdown + Peak Stats */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Server Cost Breakdown */}
        <motion.div
          className="bubble p-5 overflow-hidden xl:col-span-2"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, ...springs.gentle }}
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold flex items-center gap-2">
                <Server className="w-4 h-4 text-primary" />
                Cost by Server
              </h3>
              <p className="text-sm text-muted-foreground mt-0.5">
                NUKE consumption breakdown per server
              </p>
            </div>
          </div>
          {serverBreakdownData.length > 0 ? (
            <div className="h-[240px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={serverBreakdownData}
                  layout="vertical"
                  margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="var(--border)"
                    strokeOpacity={0.2}
                    horizontal={false}
                  />
                  <XAxis
                    type="number"
                    stroke="var(--muted-foreground)"
                    tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="label"
                    stroke="var(--muted-foreground)"
                    tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }}
                    tickLine={false}
                    axisLine={false}
                    width={120}
                  />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (!active || !payload || !payload.length) return null
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
                            {payload[0].value} NUKE
                          </p>
                        </div>
                      )
                    }}
                    cursor={{ fill: 'var(--muted)', opacity: 0.2 }}
                  />
                  <Bar
                    dataKey="value"
                    barSize={32}
                    radius={[0, 6, 6, 0]}
                    animationDuration={800}
                    animationEasing="ease-out"
                  >
                    {serverBreakdownData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-[240px] flex items-center justify-center text-sm text-muted-foreground">
              No server cost data available
            </div>
          )}
        </motion.div>

        {/* Peak Stats + Details */}
        <motion.div
          className="bubble p-5 overflow-hidden"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6, ...springs.gentle }}
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold flex items-center gap-2">
                <Gauge className="w-4 h-4 text-primary" />
                Peak Usage
              </h3>
              <p className="text-sm text-muted-foreground mt-0.5">Maximum recorded values</p>
            </div>
          </div>

          <div className="space-y-4">
            {/* Peak CPU */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground flex items-center gap-2">
                  <Cpu className="w-3.5 h-3.5" />
                  Peak CPU
                </span>
                <span className="font-bold">{(usage?.peak_stats?.peak_cpu || 0).toFixed(1)}%</span>
              </div>
              <div className="h-2 bg-muted rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-chart-1 rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(usage?.peak_stats?.peak_cpu || 0, 100)}%` }}
                  transition={{ delay: 0.8, duration: 1, ease: 'easeOut' }}
                />
              </div>
            </div>

            {/* Peak Memory */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground flex items-center gap-2">
                  <Database className="w-3.5 h-3.5" />
                  Peak Memory
                </span>
                <span className="font-bold">
                  {(usage?.peak_stats?.peak_memory || 0).toFixed(1)}%
                </span>
              </div>
              <div className="h-2 bg-muted rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-chart-2 rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(usage?.peak_stats?.peak_memory || 0, 100)}%` }}
                  transition={{ delay: 0.9, duration: 1, ease: 'easeOut' }}
                />
              </div>
            </div>

            {/* Peak GPU */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground flex items-center gap-2">
                  <Zap className="w-3.5 h-3.5" />
                  Peak GPU
                </span>
                <span className="font-bold">{(usage?.peak_stats?.peak_gpu || 0).toFixed(1)}%</span>
              </div>
              <div className="h-2 bg-muted rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-chart-5 rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(usage?.peak_stats?.peak_gpu || 0, 100)}%` }}
                  transition={{ delay: 1.0, duration: 1, ease: 'easeOut' }}
                />
              </div>
            </div>

            {/* Data Points */}
            <div className="pt-2 border-t border-border">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground flex items-center gap-2">
                  <LineChart className="w-3.5 h-3.5" />
                  Total Data Points
                </span>
                <span className="font-bold">
                  {usage?.daily_usage?.reduce((sum, d) => sum + d.data_points, 0) || 0}
                </span>
              </div>
            </div>

            {/* Cost Trend */}
            {typeof usage?.cost_trend === 'number' && usage.cost_trend !== 0 && (
              <div className="pt-2 border-t border-border">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground flex items-center gap-2">
                    {usage.cost_trend >= 0 ? (
                      <TrendingUp className="w-3.5 h-3.5 text-red-400" />
                    ) : (
                      <TrendingDown className="w-3.5 h-3.5 text-emerald-400" />
                    )}
                    Cost Trend
                  </span>
                  <span
                    className={cn(
                      'font-bold',
                      usage.cost_trend >= 0 ? 'text-red-400' : 'text-emerald-400'
                    )}
                  >
                    {usage.cost_trend >= 0 ? '+' : ''}
                    {usage.cost_trend.toFixed(1)}%
                  </span>
                </div>
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </div>
  )
}
