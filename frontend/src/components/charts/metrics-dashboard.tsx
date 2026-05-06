import { useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, Cpu, HardDrive, Network, Zap, ArrowDown, ArrowUp } from 'lucide-react';
import { useWebSocket } from '../../hooks/use-websocket';
import { useDashboardMetrics } from '../../hooks/use-dashboard-metrics';
import { MetricsAreaChart, formatters } from './area-chart';
import { MetricsBarChart } from './bar-chart';
import { SemiCircularGauge } from './semi-circular-gauge';
import { cn, formatBytes } from '../../lib/utils';
import { springs } from '../../lib/animations';

interface ServerMetrics {
  cpu_usage: number;
  memory_usage: number;
  memory_total: number;
  disk_usage: number;
  disk_total: number;
  network_rx: number;
  network_tx: number;
}

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
  const { metrics, currentMetrics, isLoading, isLive } = useDashboardMetrics();
  const { onMessage } = useWebSocket({ autoConnect: true });
  const [serverMetrics, setServerMetrics] = useState<Record<string, ServerMetrics>>({});
  
  // Handle server-specific metrics for the bar chart
  useMemo(() => {
    const unsubscribe = onMessage((message) => {
      if (message.event === 'metrics:server' || message.event === 'metrics:all') {
        const raw = message.data as Partial<ServerMetrics & {
          server_id: string;
          cpu_percent?: number;
          memory_percent?: number;
          memory_used?: number;
          disk_read_bytes?: number;
          disk_write_bytes?: number;
          network_rx_bytes?: number;
          network_tx_bytes?: number;
        }>;
        if (!raw.server_id) return;

        const data: ServerMetrics = {
          cpu_usage: Number(raw.cpu_usage ?? raw.cpu_percent) || 0,
          memory_usage: Number(raw.memory_usage ?? raw.memory_percent ?? raw.memory_used) || 0,
          memory_total: Number(raw.memory_total) || 0,
          disk_usage: Number(raw.disk_usage ?? raw.disk_read_bytes) || 0,
          disk_total: Number(raw.disk_total) || 0,
          network_rx: Number(raw.network_rx ?? raw.network_rx_bytes) || 0,
          network_tx: Number(raw.network_tx ?? raw.network_tx_bytes) || 0,
        };

        setServerMetrics((prev) => ({
          ...prev,
          [raw.server_id!]: data,
        }));
      }
    });

    return unsubscribe;
  }, [onMessage]);

  const serverBarData = useMemo(() => {
    return Object.entries(serverMetrics).map(([id, metrics]) => ({
      label: `Server ${id.slice(0, 8)}`,
      value: metrics.cpu_usage,
      color: metrics.cpu_usage > 80
        ? 'var(--destructive)'
        : metrics.cpu_usage > 60
          ? 'var(--chart-3)'
          : 'var(--chart-2)',
    }));
  }, [serverMetrics]);

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
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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
            <MetricsBarChart
              data={serverBarData}
              height={200}
              showAxis
              showGrid
              horizontal
            />
          </motion.div>
        )}
      </AnimatePresence>

    </div>
  );
}
