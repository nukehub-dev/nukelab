import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, Cpu, HardDrive, Network, Zap } from 'lucide-react';
import { useWebSocket } from '../../hooks/use-websocket';
import { MetricsAreaChart } from './area-chart';
import { MetricsBarChart } from './bar-chart';
import { GaugeChart } from './gauge-chart';
import { MetricSparkline } from '../data/metric-sparkline';
import { cn, formatBytes } from '../../lib/utils';
import { springs } from '../../lib/animations';

interface MetricDataPoint {
  timestamp: string;
  value: number;
}

interface ServerMetrics {
  cpu_usage: number;
  memory_usage: number;
  memory_total: number;
  disk_usage: number;
  disk_total: number;
  network_rx: number;
  network_tx: number;
}

interface SystemMetrics {
  total_servers: number;
  active_servers: number;
  total_cpu_usage: number;
  total_memory_usage: number;
  total_memory: number;
  total_disk_usage: number;
  total_disk: number;
  network_throughput: number;
  // Raw fields from backend
  cpu_percent?: number;
  memory_used?: number;
  memory_total?: number;
  memory_percent?: number;
  disk_used?: number;
  disk_total?: number;
  disk_percent?: number;
  network_rx_bytes?: number;
  network_tx_bytes?: number;
  docker_containers_running?: number;
  docker_containers_total?: number;
}

const MAX_HISTORY_POINTS = 60;
const STORAGE_KEY = 'nukelab_metrics_history';
const STORAGE_MAX_AGE_MS = 30 * 60 * 1000; // 30 minutes

interface StoredMetrics {
  timestamp: number;
  cpuHistory: MetricDataPoint[];
  memoryHistory: MetricDataPoint[];
  networkHistory: MetricDataPoint[];
  diskHistory: MetricDataPoint[];
}

function loadStoredMetrics(): StoredMetrics | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as StoredMetrics;
    if (Date.now() - data.timestamp > STORAGE_MAX_AGE_MS) return null;
    return data;
  } catch {
    return null;
  }
}

function saveStoredMetrics(data: StoredMetrics) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // ignore storage errors
  }
}

function useMetricHistory() {
  const stored = loadStoredMetrics();

  const [cpuHistory, setCpuHistory] = useState<MetricDataPoint[]>(stored?.cpuHistory ?? []);
  const [memoryHistory, setMemoryHistory] = useState<MetricDataPoint[]>(stored?.memoryHistory ?? []);
  const [networkHistory, setNetworkHistory] = useState<MetricDataPoint[]>(stored?.networkHistory ?? []);
  const [diskHistory, setDiskHistory] = useState<MetricDataPoint[]>(stored?.diskHistory ?? []);

  const addPoint = useCallback((
    cpu: number,
    memoryPercent: number,
    networkThroughput: number,
    diskPercent: number
  ) => {
    const timestamp = new Date().toLocaleTimeString();

    setCpuHistory((prev) => {
      const next = [...prev, { timestamp, value: cpu }];
      return next.slice(-MAX_HISTORY_POINTS);
    });
    setMemoryHistory((prev) => {
      const next = [...prev, { timestamp, value: memoryPercent }];
      return next.slice(-MAX_HISTORY_POINTS);
    });
    setNetworkHistory((prev) => {
      const next = [...prev, { timestamp, value: networkThroughput }];
      return next.slice(-MAX_HISTORY_POINTS);
    });
    setDiskHistory((prev) => {
      const next = [...prev, { timestamp, value: diskPercent }];
      return next.slice(-MAX_HISTORY_POINTS);
    });
  }, []);

  // Persist to localStorage whenever history changes
  useEffect(() => {
    saveStoredMetrics({
      timestamp: Date.now(),
      cpuHistory,
      memoryHistory,
      networkHistory,
      diskHistory,
    });
  }, [cpuHistory, memoryHistory, networkHistory, diskHistory]);

  return {
    cpuHistory,
    memoryHistory,
    networkHistory,
    diskHistory,
    addPoint,
  };
}

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ElementType;
  iconColor: string;
  bgColor: string;
  sparkline?: number[];
  gauge?: number;
  children?: React.ReactNode;
}

function MetricCard({
  title,
  value,
  subtitle,
  icon: Icon,
  iconColor,
  bgColor,
  sparkline,
  gauge,
  children,
}: MetricCardProps) {
  return (
    <motion.div
      className="bubble p-5 hover-lift cursor-default group relative overflow-hidden"
      whileHover={{ y: -4, transition: springs.gentle }}
      initial={{ opacity: 0, scale: 0.95, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={springs.gentle}
    >
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-current/5 via-transparent to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100"
        style={{ color: 'var(--primary)' }}
      />
      
      <div className="relative">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className={cn("p-2 rounded-lg", bgColor)}>
              <Icon className={cn("w-4 h-4", iconColor)} />
            </div>
            <span className="text-sm font-medium text-muted-foreground">{title}</span>
          </div>
          {sparkline && sparkline.length > 1 && (
            <MetricSparkline
              data={sparkline}
              width={80}
              height={24}
              color="currentColor"
              fill
            />
          )}
        </div>
        
        <div className="flex items-end justify-between">
          <div>
            <p className="text-2xl font-bold tabular-nums">{value}</p>
            {subtitle && (
              <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
            )}
          </div>
          {gauge !== undefined && (
            <GaugeChart
              value={gauge}
              max={100}
              size={80}
              strokeWidth={6}
              showValue={false}
            />
          )}
        </div>
        
        {children && <div className="mt-4">{children}</div>}
      </div>
    </motion.div>
  );
}

export function MetricsDashboard() {
  const { isConnected, subscribe, onMessage } = useWebSocket({ autoConnect: true });
  const subscribedRef = useRef(false);
  
  const [systemMetrics, setSystemMetrics] = useState<SystemMetrics | null>(null);
  const [serverMetrics, setServerMetrics] = useState<Record<string, ServerMetrics>>({});
  
  const {
    cpuHistory,
    memoryHistory,
    networkHistory,
    diskHistory,
    addPoint,
  } = useMetricHistory();

  useEffect(() => {
    if (isConnected && !subscribedRef.current) {
      subscribe('global');
      subscribedRef.current = true;
    }
  }, [isConnected, subscribe]);

  useEffect(() => {
    const unsubscribe = onMessage((message) => {
      if (message.event === 'metrics:system') {
        const raw = message.data as Partial<SystemMetrics & {
          cpu_percent?: number;
          memory_used?: number;
          memory_total?: number;
          memory_percent?: number;
          disk_used?: number;
          disk_total?: number;
          disk_percent?: number;
          network_rx_bytes?: number;
          network_tx_bytes?: number;
        }>;
        
        // Handle both old aggregated field names and new host metric field names
        const data: SystemMetrics = {
          total_servers: Number(raw.total_servers ?? raw.docker_containers_running) || 0,
          active_servers: Number(raw.active_servers) || 0,
          total_cpu_usage: Number(raw.total_cpu_usage ?? raw.cpu_percent) || 0,
          total_memory_usage: Number(raw.total_memory_usage ?? raw.memory_used) || 0,
          total_memory: Number(raw.total_memory ?? raw.memory_total) || 0,
          total_disk_usage: Number(raw.total_disk_usage ?? raw.disk_used) || 0,
          total_disk: Number(raw.total_disk ?? raw.disk_total) || 0,
          network_throughput: Number(raw.network_throughput ?? raw.network_rx_bytes) || 0,
        };
        
        setSystemMetrics(data);
        
        const memoryPercent = data.total_memory > 0
          ? (data.total_memory_usage / data.total_memory) * 100
          : Number(raw.memory_percent) || 0;
        const diskPercent = data.total_disk > 0
          ? (data.total_disk_usage / data.total_disk) * 100
          : Number(raw.disk_percent) || 0;
        
        addPoint(
          data.total_cpu_usage,
          memoryPercent,
          data.network_throughput,
          diskPercent
        );
      } else if (message.event === 'metrics:server' || message.event === 'metrics:all') {
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

        // Map backend field names to frontend field names
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
  }, [onMessage, addPoint]);

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

  const latestCpu = cpuHistory.length > 0 ? Number(cpuHistory[cpuHistory.length - 1].value) || 0 : 0;
  const latestMemory = memoryHistory.length > 0 ? Number(memoryHistory[memoryHistory.length - 1].value) || 0 : 0;
  const latestDisk = diskHistory.length > 0 ? Number(diskHistory[diskHistory.length - 1].value) || 0 : 0;
  const latestNetwork = networkHistory.length > 0 ? Number(networkHistory[networkHistory.length - 1].value) || 0 : 0;

  const sparklineData = useMemo(() => ({
    cpu: cpuHistory.map((p) => Number(p.value) || 0),
    memory: memoryHistory.map((p) => Number(p.value) || 0),
    network: networkHistory.map((p) => Number(p.value) || 0),
    disk: diskHistory.map((p) => Number(p.value) || 0),
  }), [cpuHistory, memoryHistory, networkHistory, diskHistory]);

  return (
    <div className="space-y-6">
      {/* Connection status */}
      <div className="flex items-center gap-2">
        <div className={cn(
          "w-2 h-2 rounded-full transition-colors",
          isConnected ? "bg-emerald-400 live-pulse" : "bg-muted-foreground"
        )} />
        <span className="text-xs text-muted-foreground">
          {isConnected ? 'Live metrics' : 'Connecting...'}
        </span>
      </div>

      {/* Metric Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="CPU Usage"
          value={`${latestCpu.toFixed(1)}%`}
          subtitle={systemMetrics ? `${systemMetrics.active_servers} active servers` : undefined}
          icon={Cpu}
          iconColor="text-chart-1"
          bgColor="bg-chart-1/10"
          sparkline={sparklineData.cpu}
          gauge={latestCpu}
        />
        
        <MetricCard
          title="Memory"
          value={`${latestMemory.toFixed(1)}%`}
          subtitle={systemMetrics
            ? `${formatBytes(systemMetrics.total_memory_usage)} / ${formatBytes(systemMetrics.total_memory)}`
            : undefined
          }
          icon={Zap}
          iconColor="text-chart-2"
          bgColor="bg-chart-2/10"
          sparkline={sparklineData.memory}
          gauge={latestMemory}
        />
        
        <MetricCard
          title="Disk"
          value={`${latestDisk.toFixed(1)}%`}
          subtitle={systemMetrics
            ? `${formatBytes(systemMetrics.total_disk_usage)} / ${formatBytes(systemMetrics.total_disk)}`
            : undefined
          }
          icon={HardDrive}
          iconColor="text-chart-3"
          bgColor="bg-chart-3/10"
          sparkline={sparklineData.disk}
          gauge={latestDisk}
        />
        
        <MetricCard
          title="Network"
          value={systemMetrics
            ? `${formatBytes(systemMetrics.network_throughput)}/s`
            : `${formatBytes(latestNetwork)}/s`
          }
          subtitle="Throughput"
          icon={Network}
          iconColor="text-chart-4"
          bgColor="bg-chart-4/10"
          sparkline={sparklineData.network}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* CPU & Memory Area Charts */}
        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, ...springs.gentle }}
        >
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold">CPU Usage Over Time</h3>
            <Activity className="w-4 h-4 text-muted-foreground" />
          </div>
          <MetricsAreaChart
            data={cpuHistory}
            color="var(--chart-1)"
            height={200}
            showAxis={cpuHistory.length > 1}
            showGrid
          />
        </motion.div>
        
        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, ...springs.gentle }}
        >
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold">Memory Usage Over Time</h3>
            <Zap className="w-4 h-4 text-muted-foreground" />
          </div>
          <MetricsAreaChart
            data={memoryHistory}
            color="var(--chart-2)"
            height={200}
            showAxis={memoryHistory.length > 1}
            showGrid
          />
        </motion.div>
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

      {/* Gauges Row */}
      <motion.div
        className="bubble p-5"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3, ...springs.gentle }}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold">Resource Utilization</h3>
          <Activity className="w-4 h-4 text-muted-foreground" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 justify-items-center">
          <div className="flex flex-col items-center">
            <GaugeChart
              value={latestCpu}
              max={100}
              label="CPU"
              size={120}
              strokeWidth={10}
            />
          </div>
          <div className="flex flex-col items-center">
            <GaugeChart
              value={latestMemory}
              max={100}
              label="Memory"
              size={120}
              strokeWidth={10}
            />
          </div>
          <div className="flex flex-col items-center">
            <GaugeChart
              value={latestDisk}
              max={100}
              label="Disk"
              size={120}
              strokeWidth={10}
            />
          </div>
          <div className="flex flex-col items-center">
            <GaugeChart
              value={Math.min(latestNetwork / 1048576, 100)}
              max={100}
              label="Network"
              size={120}
              strokeWidth={10}
            />
          </div>
        </div>
      </motion.div>
    </div>
  );
}
