import { createFileRoute, Link } from '@tanstack/react-router';
import { useState, useEffect, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  Server,
  ArrowLeft,
  Activity,
  Cpu,
  HardDrive,
  Network,
  Zap,
  Clock,
  Play,
  Square,
  RotateCcw,
  Trash2,
} from 'lucide-react';
import { useWebSocket } from '../../../hooks/use-websocket';
import { MetricsAreaChart } from '../../../components/charts/area-chart';
import { GaugeChart } from '../../../components/charts/gauge-chart';
import { MetricSparkline } from '../../../components/data/metric-sparkline';
import { StatusBadge } from '../../../components/data/status-badge';
import { useServers, useServerActions } from '../../../hooks/use-servers';
import { formatDate, formatBytes, cn } from '../../../lib/utils';
import { springs } from '../../../lib/animations';

export const Route = createFileRoute('/servers/$serverId/')({
  component: ServerDetailPage,
});

interface ServerMetricPoint {
  timestamp: string;
  cpu: number;
  memory: number;
  disk: number;
  network: number;
}

const MAX_POINTS = 60;

function ServerDetailPage() {
  const { serverId } = Route.useParams();
  const { data: servers = [] } = useServers();
  const { startServer, stopServer, restartServer, deleteServer } = useServerActions();
  const { isConnected, subscribe, unsubscribe, onMessage } = useWebSocket({ autoConnect: true });

  const server = servers.find((s) => s.id === serverId);

  const [metrics, setMetrics] = useState<ServerMetricPoint[]>([]);
  const [currentMetrics, setCurrentMetrics] = useState({
    cpu: 0,
    memory: 0,
    disk: 0,
    network: 0,
  });

  useEffect(() => {
    if (isConnected && serverId) {
      subscribe('server', serverId);
      return () => {
        unsubscribe('server', serverId);
      };
    }
  }, [isConnected, serverId, subscribe, unsubscribe]);

  useEffect(() => {
    const unsubscribe = onMessage((message) => {
      if (message.event === 'metrics:server') {
        const data = message.data as {
          server_id: string;
          cpu_usage?: number;
          memory_usage?: number;
          memory_total?: number;
          disk_usage?: number;
          disk_total?: number;
          network_rx?: number;
          network_tx?: number;
        };

        if (data.server_id !== serverId) return;

        const cpu = Number(data.cpu_usage) || 0;
        const memoryTotal = Number(data.memory_total) || 1;
        const memory = ((Number(data.memory_usage) || 0) / memoryTotal) * 100;
        const diskTotal = Number(data.disk_total) || 1;
        const disk = ((Number(data.disk_usage) || 0) / diskTotal) * 100;
        const network = (Number(data.network_rx) || 0) + (Number(data.network_tx) || 0);

        const timestamp = new Date().toLocaleTimeString();

        setCurrentMetrics({ cpu, memory, disk, network });
        setMetrics((prev) => {
          const next = [...prev, { timestamp, cpu, memory, disk, network }];
          return next.slice(-MAX_POINTS);
        });
      }
    });

    return unsubscribe;
  }, [onMessage, serverId]);

  const cpuData = useMemo(
    () => metrics.map((m) => ({ timestamp: m.timestamp, value: m.cpu })),
    [metrics]
  );
  const memoryData = useMemo(
    () => metrics.map((m) => ({ timestamp: m.timestamp, value: m.memory })),
    [metrics]
  );
  const diskData = useMemo(
    () => metrics.map((m) => ({ timestamp: m.timestamp, value: m.disk })),
    [metrics]
  );
  const networkData = useMemo(
    () => metrics.map((m) => ({ timestamp: m.timestamp, value: m.network })),
    [metrics]
  );

  if (!server) {
    return (
      <div className="p-10 text-center"
      >
        <Server className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
        <h2 className="text-lg font-semibold mb-2"
        >Server not found</h2>
        <p className="text-muted-foreground mb-4"
        >The server you are looking for does not exist.</p>
        <Link
          to="/servers"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Servers
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8"
    >
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="flex flex-col md:flex-row md:items-center md:justify-between gap-4"
      >
        <div className="flex items-center gap-4"
        >
          <Link
            to="/servers"
            className="p-2 rounded-lg hover:bg-accent transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <div className="flex items-center gap-3"
            >
              <h1 className="text-2xl font-bold"
              >{server.name}</h1>
              <StatusBadge status={server.status} pulse={server.status === 'running'} />
            </div>
            <p className="text-sm text-muted-foreground mt-1"
            >
              ID: <span className="font-mono"
              >{server.id}</span>
              {server.container_id && (
                <>
                  {' · Container: '}
                  <span className="font-mono"
                  >{server.container_id.slice(0, 12)}</span>
                </>
              )}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2"
        >
          {server.status === 'stopped' && (
            <button
              onClick={() => startServer.mutate(server.id)}
              disabled={startServer.isPending}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-colors text-sm font-medium"
            >
              <Play className="w-4 h-4" />
              Start
            </button>
          )}
          {server.status === 'running' && (
            <button
              onClick={() => stopServer.mutate(server.id)}
              disabled={stopServer.isPending}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-colors text-sm font-medium"
            >
              <Square className="w-4 h-4" />
              Stop
            </button>
          )}
          <button
            onClick={() => restartServer.mutate(server.id)}
            disabled={restartServer.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors text-sm font-medium"
          >
            <RotateCcw className="w-4 h-4" />
            Restart
          </button>
          <button
            onClick={() => {
              if (confirm('Are you sure you want to delete this server?')) {
                deleteServer.mutate(server.id);
              }
            }}
            disabled={deleteServer.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors text-sm font-medium"
          >
            <Trash2 className="w-4 h-4" />
            Delete
          </button>
        </div>
      </motion.div>

      {/* Connection Status */}
      <div className="flex items-center gap-2"
      >
        <div className={cn(
          'w-2 h-2 rounded-full transition-colors',
          isConnected ? 'bg-emerald-400 live-pulse' : 'bg-muted-foreground'
        )} />
        <span className="text-xs text-muted-foreground"
        >
          {isConnected ? 'Live metrics' : 'Connecting...'}
        </span>
      </div>

      {/* Stats Grid */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1, ...springs.gentle }}
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
      >
        <div className="bubble p-5"
        >
          <div className="flex items-center gap-3 mb-3"
          >
            <div className="p-2 rounded-lg bg-chart-1/10"
            >
              <Cpu className="w-4 h-4 text-chart-1" />
            </div>
            <span className="text-sm text-muted-foreground"
            >CPU Usage</span>
          </div>
          <div className="flex items-end justify-between"
          >
            <p className="text-2xl font-bold tabular-nums"
            >{currentMetrics.cpu.toFixed(1)}%</p>
            {metrics.length > 1 && (
              <MetricSparkline data={metrics.map((m) => m.cpu)} width={80} height={24} color="var(--chart-1)" fill />
            )}
          </div>
        </div>

        <div className="bubble p-5"
        >
          <div className="flex items-center gap-3 mb-3"
          >
            <div className="p-2 rounded-lg bg-chart-2/10"
            >
              <Zap className="w-4 h-4 text-chart-2" />
            </div>
            <span className="text-sm text-muted-foreground"
            >Memory</span>
          </div>
          <div className="flex items-end justify-between"
          >
            <p className="text-2xl font-bold tabular-nums"
            >{currentMetrics.memory.toFixed(1)}%</p>
            {metrics.length > 1 && (
              <MetricSparkline data={metrics.map((m) => m.memory)} width={80} height={24} color="var(--chart-2)" fill />
            )}
          </div>
        </div>

        <div className="bubble p-5"
        >
          <div className="flex items-center gap-3 mb-3"
          >
            <div className="p-2 rounded-lg bg-chart-3/10"
            >
              <HardDrive className="w-4 h-4 text-chart-3" />
            </div>
            <span className="text-sm text-muted-foreground"
            >Disk</span>
          </div>
          <div className="flex items-end justify-between"
          >
            <p className="text-2xl font-bold tabular-nums"
            >{currentMetrics.disk.toFixed(1)}%</p>
            {metrics.length > 1 && (
              <MetricSparkline data={metrics.map((m) => m.disk)} width={80} height={24} color="var(--chart-3)" fill />
            )}
          </div>
        </div>

        <div className="bubble p-5"
        >
          <div className="flex items-center gap-3 mb-3"
          >
            <div className="p-2 rounded-lg bg-chart-4/10"
            >
              <Network className="w-4 h-4 text-chart-4" />
            </div>
            <span className="text-sm text-muted-foreground"
            >Network</span>
          </div>
          <div className="flex items-end justify-between"
          >
            <p className="text-2xl font-bold tabular-nums"
            >{formatBytes(currentMetrics.network)}/s</p>
            {metrics.length > 1 && (
              <MetricSparkline data={metrics.map((m) => m.network)} width={80} height={24} color="var(--chart-4)" fill />
            )}
          </div>
        </div>
      </motion.div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4"
      >
        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2, ...springs.gentle }}
        >
          <div className="flex items-center justify-between mb-4"
          >
            <h3 className="text-sm font-semibold"
            >CPU Usage Over Time</h3>
            <Activity className="w-4 h-4 text-muted-foreground" />
          </div>
          <MetricsAreaChart
            data={cpuData}
            color="var(--chart-1)"
            height={200}
            showAxis={cpuData.length > 1}
            showGrid
          />
        </motion.div>

        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, ...springs.gentle }}
        >
          <div className="flex items-center justify-between mb-4"
          >
            <h3 className="text-sm font-semibold"
            >Memory Usage Over Time</h3>
            <Zap className="w-4 h-4 text-muted-foreground" />
          </div>
          <MetricsAreaChart
            data={memoryData}
            color="var(--chart-2)"
            height={200}
            showAxis={memoryData.length > 1}
            showGrid
          />
        </motion.div>

        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.35, ...springs.gentle }}
        >
          <div className="flex items-center justify-between mb-4"
          >
            <h3 className="text-sm font-semibold"
            >Disk Usage Over Time</h3>
            <HardDrive className="w-4 h-4 text-muted-foreground" />
          </div>
          <MetricsAreaChart
            data={diskData}
            color="var(--chart-3)"
            height={200}
            showAxis={diskData.length > 1}
            showGrid
          />
        </motion.div>

        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4, ...springs.gentle }}
        >
          <div className="flex items-center justify-between mb-4"
          >
            <h3 className="text-sm font-semibold"
            >Network I/O Over Time</h3>
            <Network className="w-4 h-4 text-muted-foreground" />
          </div>
          <MetricsAreaChart
            data={networkData}
            color="var(--chart-4)"
            height={200}
            showAxis={networkData.length > 1}
            showGrid
          />
        </motion.div>
      </div>

      {/* Gauges */}
      <motion.div
        className="bubble p-5"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4, ...springs.gentle }}
      >
        <div className="flex items-center justify-between mb-4"
        >
          <h3 className="text-sm font-semibold"
          >Resource Utilization</h3>
          <Activity className="w-4 h-4 text-muted-foreground" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 justify-items-center"
        >
          <GaugeChart value={currentMetrics.cpu} max={100} label="CPU" size={120} strokeWidth={10} />
          <GaugeChart value={currentMetrics.memory} max={100} label="Memory" size={120} strokeWidth={10} />
          <GaugeChart value={currentMetrics.disk} max={100} label="Disk" size={120} strokeWidth={10} />
          <GaugeChart
            value={Math.min(currentMetrics.network / 1e6, 100)}
            max={100}
            label="Network"
            size={120}
            strokeWidth={10}
          />
        </div>
      </motion.div>

      {/* Server Info */}
      <motion.div
        className="bubble p-5"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5, ...springs.gentle }}
      >
        <h3 className="text-sm font-semibold mb-4"
        >Server Details</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4"
        >
          <div className="space-y-3"
          >
            <div className="flex justify-between text-sm"
            >
              <span className="text-muted-foreground"
              >Status</span>
              <StatusBadge status={server.status} pulse={server.status === 'running'} />
            </div>
            <div className="flex justify-between text-sm"
            >
              <span className="text-muted-foreground"
              >Created</span>
              <span className="flex items-center gap-1"
              >
                <Clock className="w-3.5 h-3.5" />
                {formatDate(server.created_at || '')}
              </span>
            </div>
            {server.started_at && (
              <div className="flex justify-between text-sm"
              >
                <span className="text-muted-foreground"
                >Started</span>
                <span
                >{formatDate(server.started_at || '')}</span>
              </div>
            )}
          </div>
          <div className="space-y-3"
          >
            {server.allocated_cpu !== undefined && (
              <div className="flex justify-between text-sm"
              >
                <span className="text-muted-foreground"
                >CPU Cores</span>
                <span className="font-mono"
                >{server.allocated_cpu}</span>
              </div>
            )}
            {server.allocated_memory !== undefined && (
              <div className="flex justify-between text-sm"
              >
                <span className="text-muted-foreground"
                >Memory</span>
                <span className="font-mono"
                >{server.allocated_memory}</span>
              </div>
            )}
            {server.external_url && (
              <div className="flex justify-between text-sm"
              >
                <span className="text-muted-foreground"
                >External URL</span>
                <a
                  href={server.external_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline truncate max-w-[200px]"
                >
                  {server.external_url}
                </a>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
