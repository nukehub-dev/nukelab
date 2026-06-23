import { useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, Cpu, HardDrive, Network, Zap, ArrowDown, ArrowUp } from 'lucide-react';
import { useDashboardMetrics } from '../../hooks/use-dashboard-metrics';
import { useServers } from '../../hooks/use-servers';
import { MetricsAreaChart } from './area-chart';
import { formatters } from './chart-formatters';
import { HorizontalBarChart } from './horizontal-bar-chart';
import { SemiCircularGauge } from './semi-circular-gauge';
import { cn, formatBytes } from '../../lib/utils';
import { springs } from '../../lib/animations';

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: React.ReactNode;
  icon: React.ElementType;
  iconColor: string;
  bgColor: string;
  gaugeValue?: number;
  gaugeMax?: number;
}

function MetricCard({
  title,
  value,
  subtitle,
  icon: Icon,
  iconColor,
  bgColor,
  gaugeValue,
  gaugeMax = 100,
}: MetricCardProps) {
  return (
    <motion.div
      className="bubble p-5 hover-lift cursor-default group relative overflow-hidden"
      whileHover={{ y: -4, transition: springs.gentle }}
      initial={{ opacity: 0, scale: 0.95, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={springs.gentle}
    >
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-current/5 via-transparent to-transparent opacity-0 transition-opacity duration-200 group-hover:opacity-100"
        style={{ color: 'var(--primary)' }}
      />
      
      <div className="relative">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className={cn("p-2 rounded-lg", bgColor)}>
              <Icon className={cn("w-4 h-4", iconColor)} />
            </div>
            <span className="text-sm font-medium text-muted-foreground">{title}</span>
          </div>
        </div>
        
        <div className="mt-2 flex items-end justify-between">
          <div>
            <p className="text-2xl font-bold tabular-nums">{value}</p>
            {subtitle && (
              <div className="text-xs text-muted-foreground mt-1">{subtitle}</div>
            )}
          </div>
          {gaugeValue !== undefined && (
            <div className="mb-1">
              <SemiCircularGauge
                value={gaugeValue}
                max={gaugeMax}
                width={80}
                height={48}
                strokeWidth={6}
                color={iconColor.includes('destructive') ? 'var(--destructive)' : iconColor.includes('chart-3') ? 'var(--chart-3)' : 'var(--chart-2)'}
              />
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}

interface ChartCardProps {
  title: string;
  subtitle: string;
  icon: React.ElementType;
  children: React.ReactNode;
  delay?: number;
}

function ChartCard({ title, subtitle, icon: Icon, children, delay = 0 }: ChartCardProps) {
  return (
    <motion.div
      className="bubble p-5"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, ...springs.gentle }}
    >
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="text-base font-semibold">{title}</h3>
          <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>
        </div>
        <Icon className="w-4 h-4 text-muted-foreground mt-1" />
      </div>
      {children}
    </motion.div>
  );
}

export function MetricsDashboard() {
  const { metrics, currentMetrics, serverMetrics, isLoading, isLive } = useDashboardMetrics();
  const { data: servers } = useServers();

  const serverBarData = useMemo(() => {
    const serverMap = new Map(servers?.map((s) => [s.id, s]) ?? []);
    return Object.entries(serverMetrics)
      .map(([id, metrics]) => {
        const server = serverMap.get(id);
        const label = server?.username && server?.name
          ? `${server.username}/${server.name}`
          : `Server ${id.slice(0, 8)}`;
        return {
          label,
          value: metrics.cpu,
          color: metrics.cpu > 80
            ? 'var(--destructive)'
            : metrics.cpu > 60
              ? 'var(--chart-3)'
              : 'var(--chart-2)',
        };
      })
      .sort((a, b) => b.value - a.value);
  }, [serverMetrics, servers]);

  // Prepare chart data with proper timestamps
  const chartData = useMemo(() => {
    return metrics.map((m) => ({
      timestamp: m.timestamp,
      cpu: m.cpu,
      memory: m.memoryPercent,
      memoryUsed: m.memoryUsed,
      memoryTotal: m.memoryTotal,
      diskTotal: m.diskRead + m.diskWrite,
      diskRead: m.diskRead,
      diskWrite: m.diskWrite,
      networkTotal: m.networkRx + m.networkTx,
      networkRx: m.networkRx,
      networkTx: m.networkTx,
    }));
  }, [metrics]);

  const totalNetwork = currentMetrics.networkRx + currentMetrics.networkTx;

  return (
    <div className="space-y-6">
      {/* Connection status */}
      <div className="flex items-center gap-2">
        <div className={cn(
          "w-2 h-2 rounded-full transition-colors",
          isLive ? "bg-emerald-400 live-pulse" : "bg-muted-foreground"
        )} />
        <span className="text-xs text-muted-foreground">
          {isLive ? 'Live metrics' : isLoading ? 'Loading...' : 'Connecting...'}
        </span>
      </div>

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="CPU Usage"
          value={`${currentMetrics.cpu.toFixed(1)}%`}
          subtitle={currentMetrics.cpuCount > 0 ? `${currentMetrics.cpuCount} cores` : undefined}
          icon={Cpu}
          iconColor="text-chart-1"
          bgColor="bg-chart-1/10"
          gaugeValue={currentMetrics.cpu}
        />
        
        <MetricCard
          title="Memory"
          value={`${currentMetrics.memoryPercent.toFixed(1)}%`}
          subtitle={`${formatBytes(currentMetrics.memoryUsed)} / ${formatBytes(currentMetrics.memoryTotal)}`}
          icon={Zap}
          iconColor="text-chart-2"
          bgColor="bg-chart-2/10"
          gaugeValue={currentMetrics.memoryPercent}
        />
        
        <MetricCard
          title="Disk"
          value={`${currentMetrics.diskPercent.toFixed(1)}%`}
          subtitle={`${formatBytes(currentMetrics.diskUsed)} / ${formatBytes(currentMetrics.diskTotal)}`}
          icon={HardDrive}
          iconColor="text-chart-3"
          bgColor="bg-chart-3/10"
          gaugeValue={currentMetrics.diskPercent}
        />
        
        <MetricCard
          title="Network"
          value={`${formatBytes(totalNetwork)}/s`}
          subtitle={
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1">
                <ArrowDown className="w-3 h-3 text-chart-4" />
                {formatBytes(currentMetrics.networkRx)}/s
              </span>
              <span className="flex items-center gap-1">
                <ArrowUp className="w-3 h-3 text-destructive" />
                {formatBytes(currentMetrics.networkTx)}/s
              </span>
            </div>
          }
          icon={Network}
          iconColor="text-chart-4"
          bgColor="bg-chart-4/10"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ChartCard
          title="CPU Usage"
          subtitle="Average system-wide CPU utilization"
          icon={Activity}
          delay={0.1}
        >
          <MetricsAreaChart
            data={chartData}
            series={[{ key: 'cpu', name: 'CPU', color: 'var(--chart-1)' }]}
            height={240}
            yTickFormatter={formatters.percent}
          />
        </ChartCard>
        
        <ChartCard
          title="Memory Usage"
          subtitle="Precise utilization at the recorded time"
          icon={Zap}
          delay={0.2}
        >
          <MetricsAreaChart
            data={chartData}
            series={[{ key: 'memory', name: 'Memory', color: 'var(--chart-2)' }]}
            height={240}
            yTickFormatter={formatters.percent}
          />
        </ChartCard>
        
        <ChartCard
          title="Disk I/O"
          subtitle="Read/Write bytes per second"
          icon={HardDrive}
          delay={0.3}
        >
          <MetricsAreaChart
            data={chartData}
            series={[
              { key: 'diskRead', name: 'Read', color: 'var(--chart-3)' },
              { key: 'diskWrite', name: 'Write', color: 'var(--destructive)' },
            ]}
            height={240}
            yTickFormatter={formatters.bytesPerSecond}
            tooltipFormatter={(data) => [
              { label: 'Write', value: formatters.bytesPerSecond(Number(data.diskWrite || 0)), color: 'var(--destructive)' },
              { label: 'Read', value: formatters.bytesPerSecond(Number(data.diskRead || 0)), color: 'var(--chart-3)' },
              { label: 'Total', value: formatters.bytesPerSecond(Number(data.diskTotal || 0)), color: undefined },
            ]}
          />
        </ChartCard>
        
        <ChartCard
          title="Network Traffic"
          subtitle="Network traffic of public interfaces"
          icon={Network}
          delay={0.4}
        >
          <MetricsAreaChart
            data={chartData}
            series={[
              { key: 'networkRx', name: 'RX (Download)', color: 'var(--chart-4)' },
              { key: 'networkTx', name: 'TX (Upload)', color: 'var(--destructive)' },
            ]}
            height={240}
            yTickFormatter={formatters.bytesPerSecond}
            tooltipFormatter={(data) => [
              { label: 'TX (Upload)', value: formatters.bytesPerSecond(Number(data.networkTx || 0)), color: 'var(--destructive)' },
              { label: 'RX (Download)', value: formatters.bytesPerSecond(Number(data.networkRx || 0)), color: 'var(--chart-4)' },
              { label: 'Total', value: formatters.bytesPerSecond(Number(data.networkTotal || 0)), color: undefined },
            ]}
          />
        </ChartCard>
      </div>

      {/* Server CPU Comparison Bar Chart */}
      <AnimatePresence>
        {serverBarData.length > 0 && (
          <motion.div
            className="bubble p-5"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={springs.gentle}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold">Server CPU Comparison</h3>
              <Cpu className="w-4 h-4 text-muted-foreground" />
            </div>
            {serverBarData.every((d) => d.value === 0) ? (
              <div className="flex flex-col items-center justify-center py-10 text-center">
                <Cpu className="w-8 h-8 text-muted-foreground/30 mb-3" />
                <p className="text-sm text-muted-foreground font-medium">No active server metrics</p>
                <p className="text-xs text-muted-foreground/60 mt-1 max-w-xs">
                  Servers are either powered off or not reporting metrics yet.
                  Start a server to see real-time CPU usage here.
                </p>
              </div>
            ) : (
              <div className="py-2">
                <HorizontalBarChart
                  data={serverBarData}
                  maxValue={100}
                  valueFormatter={(v) => `${v.toFixed(1)}%`}
                />
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

    </div>
  );
}
