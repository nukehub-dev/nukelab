import { createFileRoute, Link } from '@tanstack/react-router';
import { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Server,
  ArrowLeft,
  Activity,
  Cpu,
  HardDrive,
  Network,
  Zap,
  Play,
  Square,
  RotateCcw,
  Trash2,
  ArrowDown,
  ArrowUp,
  Globe,
  Calendar,
  Timer,
  ExternalLink,
  ServerIcon,
  DollarSign,
  Clock,
  AlertTriangle,
  Plus,
  Trash,
  Terminal,
} from 'lucide-react';
import { MetricsAreaChart, formatters } from '../components/charts/area-chart';
import { SemiCircularGauge } from '../components/charts/semi-circular-gauge';
import { StatusBadge } from '../components/data/status-badge';
import { useServers, useServerActions, useServerSchedules, useServerLogs, useCreateSchedule, useDeleteSchedule } from '../hooks/use-servers';
import { CronBuilder } from '../components/cron-builder';
import { useServerMetrics } from '../hooks/use-server-metrics';
import { formatDate, formatBytes, formatPlanResource, cn } from '../lib/utils';
import { springs } from '../lib/animations';

export const Route = createFileRoute('/servers/$serverId')({
  component: ServerDetailPage,
});

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
                color={iconColor.includes('destructive') ? 'var(--destructive)' : iconColor.includes('chart-3') ? 'var(--chart-3)' : iconColor.includes('chart-4') ? 'var(--chart-4)' : 'var(--chart-2)'}
              />
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function ServerDetailPage() {
  const { serverId } = Route.useParams();
  const { data: servers = [] } = useServers();
  const { startServer, stopServer, restartServer, deleteServer, isOperationPending } = useServerActions();
  const { metrics, currentMetrics, isLive } = useServerMetrics(serverId);
  const { data: schedules = [] } = useServerSchedules(serverId);
  const { data: logsData } = useServerLogs(serverId, 100);
  const createSchedule = useCreateSchedule();
  const deleteSchedule = useDeleteSchedule();

  const [activeTab, setActiveTab] = useState<'overview' | 'schedules' | 'logs'>('overview');
  const [showScheduleForm, setShowScheduleForm] = useState(false);
  const [newSchedule, setNewSchedule] = useState({ action: 'start' as const, cron_expression: '0 9 * * *', timezone: 'UTC', is_active: true });

  const server = servers.find((s) => s.id === serverId);

  const chartData = useMemo(() => {
    return metrics.map((m) => ({
      timestamp: m.timestamp,
      cpu: m.cpu,
      memory: m.memory,
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

  if (!server) {
    return (
      <div className="p-10 text-center">
        <Server className="w-12 h-12 mx-auto text-muted-foreground mb-4" />
        <h2 className="text-lg font-semibold mb-2">Server not found</h2>
        <p className="text-muted-foreground mb-4">The server you are looking for does not exist.</p>
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
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="flex flex-col md:flex-row md:items-center md:justify-between gap-4"
      >
        <div className="flex items-center gap-4">
          <Link
            to="/servers"
            className="p-2 rounded-lg hover:bg-accent transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold">{server.name}</h1>
              <StatusBadge status={server.status} pulse={server.status === 'running'} />
            </div>
            <p className="text-sm text-muted-foreground mt-1">
              ID: <span className="font-mono">{server.id}</span>
              {server.container_id && (
                <>
                  {' · Container: '}
                  <span className="font-mono">{server.container_id.slice(0, 12)}</span>
                </>
              )}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {server.status === 'stopped' && (
            <button
              onClick={() => startServer.mutate(server.id)}
              disabled={isOperationPending(server.id, 'start')}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 transition-all duration-100 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
            >
              {isOperationPending(server.id, 'start') ? (
                <RotateCcw className="w-4 h-4 animate-spin" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              {isOperationPending(server.id, 'start') ? 'Starting...' : 'Start'}
            </button>
          )}
          {server.status === 'running' && (
            <>
              <button
                onClick={() => stopServer.mutate(server.id)}
                disabled={isOperationPending(server.id, 'stop')}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-all duration-100 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
              >
                {isOperationPending(server.id, 'stop') ? (
                  <RotateCcw className="w-4 h-4 animate-spin" />
                ) : (
                  <Square className="w-4 h-4" />
                )}
                {isOperationPending(server.id, 'stop') ? 'Stopping...' : 'Stop'}
              </button>
              <button
                onClick={() => restartServer.mutate(server.id)}
                disabled={isOperationPending(server.id, 'restart')}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-all duration-100 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
              >
                {isOperationPending(server.id, 'restart') ? (
                  <RotateCcw className="w-4 h-4 animate-spin" />
                ) : (
                  <RotateCcw className="w-4 h-4" />
                )}
                {isOperationPending(server.id, 'restart') ? 'Restarting...' : 'Restart'}
              </button>
            </>
          )}
          <button
            onClick={() => {
              if (confirm('Are you sure you want to delete this server?')) {
                deleteServer.mutate(server.id);
              }
            }}
            disabled={isOperationPending(server.id, 'delete')}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive/10 text-destructive hover:bg-destructive/20 transition-all duration-100 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-[1px] active:translate-y-[1px]"
          >
            {isOperationPending(server.id, 'delete') ? (
              <RotateCcw className="w-4 h-4 animate-spin" />
            ) : (
              <Trash2 className="w-4 h-4" />
            )}
            {isOperationPending(server.id, 'delete') ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </motion.div>

      {/* Server Details */}
      <motion.div
        className="bubble p-5"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1, ...springs.gentle }}
      >
        <div className="flex items-center gap-2 mb-6">
          <ServerIcon className="w-4 h-4 text-primary" />
          <h3 className="text-base font-semibold">Server Details</h3>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Status Card */}
          <div className="flex items-start gap-4 p-4 rounded-xl bg-surface/50 border border-border/50">
            <div className="p-2.5 rounded-lg bg-primary/10">
              <Activity className="w-4 h-4 text-primary" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground mb-1">Status</p>
              <StatusBadge status={server.status} pulse={server.status === 'running'} />
            </div>
          </div>

          {/* Created Card */}
          <div className="flex items-start gap-4 p-4 rounded-xl bg-surface/50 border border-border/50">
            <div className="p-2.5 rounded-lg bg-chart-2/10">
              <Calendar className="w-4 h-4 text-chart-2" />
            </div>
            <div className="min-w-0">
              <p className="text-xs text-muted-foreground mb-1">Created</p>
              <p className="text-sm font-medium truncate">{formatDate(server.created_at || '')}</p>
            </div>
          </div>

          {/* Started Card */}
          <div className="flex items-start gap-4 p-4 rounded-xl bg-surface/50 border border-border/50">
            <div className="p-2.5 rounded-lg bg-chart-3/10">
              <Timer className="w-4 h-4 text-chart-3" />
            </div>
            <div className="min-w-0">
              <p className="text-xs text-muted-foreground mb-1">Started</p>
              {server.status === 'running' && server.started_at ? (
                <p className="text-sm font-medium truncate">{formatDate(server.started_at || '')}</p>
              ) : (
                <p className="text-sm font-medium text-muted-foreground">Not started</p>
              )}
            </div>
          </div>

          {/* CPU Card */}
          {server.allocated_cpu !== undefined && (
            <div className="flex items-start gap-4 p-4 rounded-xl bg-surface/50 border border-border/50">
              <div className="p-2.5 rounded-lg bg-chart-1/10">
                <Cpu className="w-4 h-4 text-chart-1" />
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">CPU Cores</p>
                <p className="text-sm font-medium">{server.allocated_cpu}</p>
              </div>
            </div>
          )}

          {/* Memory Card */}
          {server.allocated_memory !== undefined && (
            <div className="flex items-start gap-4 p-4 rounded-xl bg-surface/50 border border-border/50">
              <div className="p-2.5 rounded-lg bg-chart-2/10">
                <Zap className="w-4 h-4 text-chart-2" />
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Memory</p>
                <p className="text-sm font-medium">{formatPlanResource(server.allocated_memory)}</p>
              </div>
            </div>
          )}

          {/* Storage Card */}
          {server.allocated_disk !== undefined && (
            <div className="flex items-start gap-4 p-4 rounded-xl bg-surface/50 border border-border/50">
              <div className="p-2.5 rounded-lg bg-chart-3/10">
                <HardDrive className="w-4 h-4 text-chart-3" />
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Storage</p>
                <p className="text-sm font-medium">{formatPlanResource(server.allocated_disk)}</p>
              </div>
            </div>
          )}

          {/* External URL Card */}
          {server.external_url && (
            <div className="flex items-start gap-4 p-4 rounded-xl bg-surface/50 border border-border/50">
              <div className="p-2.5 rounded-lg bg-chart-4/10">
                <Globe className="w-4 h-4 text-chart-4" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs text-muted-foreground mb-1">External URL</p>
                {server.status === 'running' ? (
                  <a
                    href={server.external_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-medium text-primary hover:underline flex items-center gap-1 truncate"
                  >
                    {server.external_url}
                    <ExternalLink className="w-3 h-3 flex-shrink-0" />
                  </a>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-medium text-muted-foreground truncate">
                      {server.external_url}
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground whitespace-nowrap">
                      Start server to access
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </motion.div>

          {/* Cost Card */}
          {server.total_cost !== undefined && (
            <div className="flex items-start gap-4 p-4 rounded-xl bg-surface/50 border border-border/50">
              <div className="p-2.5 rounded-lg bg-chart-1/10">
                <DollarSign className="w-4 h-4 text-chart-1" />
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Total Cost</p>
                <p className="text-sm font-medium">{server.total_cost} NUKE</p>
              </div>
            </div>
          )}

          {/* Expiration Card */}
          {server.expires_at && (
            <div className="flex items-start gap-4 p-4 rounded-xl bg-surface/50 border border-border/50">
              <div className="p-2.5 rounded-lg bg-destructive/10">
                <Clock className="w-4 h-4 text-destructive" />
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Expires</p>
                <p className="text-sm font-medium">{formatDate(server.expires_at)}</p>
              </div>
            </div>
          )}

          {/* Stop Reason Card */}
          {server.stop_reason && (
            <div className="flex items-start gap-4 p-4 rounded-xl bg-surface/50 border border-border/50">
              <div className="p-2.5 rounded-lg bg-amber-500/10">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
              </div>
              <div>
                <p className="text-xs text-muted-foreground mb-1">Stop Reason</p>
                <p className="text-sm font-medium capitalize">{server.stop_reason.replace(/_/g, ' ')}</p>
              </div>
            </div>
          )}

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-border">
        {(['overview', 'schedules', 'logs']).map((tab: string) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab as 'overview' | 'schedules' | 'logs')}
            className={cn(
              "px-4 py-2 text-sm font-medium capitalize transition-colors relative",
              activeTab === tab ? "text-primary" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {tab}
            {activeTab === tab && (
              <motion.div
                layoutId="activeTab"
                className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary"
                transition={springs.gentle}
              />
            )}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Connection Status */}
          <div className="flex items-center gap-2">
            <div className={cn(
              'w-2 h-2 rounded-full transition-colors',
              isLive ? 'bg-emerald-400 live-pulse' : 'bg-muted-foreground'
            )} />
            <span className="text-xs text-muted-foreground">
              {isLive ? 'Live metrics' : server.status === 'stopped' ? 'Server stopped' : 'Connecting...'}
            </span>
          </div>

          {/* Metric Cards Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              title="CPU Usage"
              value={`${currentMetrics.cpu.toFixed(1)}%`}
              subtitle={server.allocated_cpu ? `${server.allocated_cpu} cores allocated` : undefined}
              icon={Cpu}
              iconColor="text-chart-1"
              bgColor="bg-chart-1/10"
              gaugeValue={currentMetrics.cpu}
            />
            
            <MetricCard
              title="Memory"
              value={`${currentMetrics.memory.toFixed(1)}%`}
              subtitle={`${formatBytes(currentMetrics.memoryUsed)} / ${formatBytes(currentMetrics.memoryTotal)}`}
              icon={Zap}
              iconColor="text-chart-2"
              bgColor="bg-chart-2/10"
              gaugeValue={currentMetrics.memory}
            />
            
            <MetricCard
              title="Disk I/O"
              value={`${formatBytes(currentMetrics.diskRead + currentMetrics.diskWrite)}/s`}
              subtitle={`${formatBytes(currentMetrics.diskRead)}/s read · ${formatBytes(currentMetrics.diskWrite)}/s write`}
              icon={HardDrive}
              iconColor="text-chart-3"
              bgColor="bg-chart-3/10"
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

          {/* Charts Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <motion.div
              className="bubble p-5 overflow-hidden"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2, ...springs.gentle }}
            >
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-base font-semibold">CPU Usage</h3>
                  <p className="text-sm text-muted-foreground mt-0.5">Average CPU utilization</p>
                </div>
                <Activity className="w-4 h-4 text-muted-foreground mt-1" />
              </div>
              <MetricsAreaChart
                data={chartData}
                series={[{ key: 'cpu', name: 'CPU', color: 'var(--chart-1)' }]}
                height={240}
                yTickFormatter={formatters.percent}
              />
            </motion.div>

            <motion.div
              className="bubble p-5 overflow-hidden"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3, ...springs.gentle }}
            >
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-base font-semibold">Memory Usage</h3>
                  <p className="text-sm text-muted-foreground mt-0.5">Memory utilization over time</p>
                </div>
                <Zap className="w-4 h-4 text-muted-foreground mt-1" />
              </div>
              <MetricsAreaChart
                data={chartData}
                series={[{ key: 'memory', name: 'Memory', color: 'var(--chart-2)' }]}
                height={240}
                yTickFormatter={formatters.percent}
              />
            </motion.div>

            <motion.div
              className="bubble p-5 overflow-hidden"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.35, ...springs.gentle }}
            >
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-base font-semibold">Disk I/O</h3>
                  <p className="text-sm text-muted-foreground mt-0.5">Read/Write bytes per second</p>
                </div>
                <HardDrive className="w-4 h-4 text-muted-foreground mt-1" />
              </div>
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
            </motion.div>

            <motion.div
              className="bubble p-5 overflow-hidden"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4, ...springs.gentle }}
            >
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-base font-semibold">Network Traffic</h3>
                  <p className="text-sm text-muted-foreground mt-0.5">Network traffic of interfaces</p>
                </div>
                <Network className="w-4 h-4 text-muted-foreground mt-1" />
              </div>
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
            </motion.div>
          </div>
        </div>
      )}

      {activeTab === 'schedules' && (
        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.gentle}
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Calendar className="w-4 h-4 text-primary" />
              <h3 className="text-base font-semibold">Scheduled Actions</h3>
            </div>
            <button
              onClick={() => setShowScheduleForm(!showScheduleForm)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-all text-sm font-medium"
            >
              <Plus className="w-3.5 h-3.5" />
              Add Schedule
            </button>
          </div>

          {showScheduleForm && (
            <div className="mb-4 p-4 rounded-xl bg-surface/50 border border-border/50 space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Action</label>
                  <select
                    value={newSchedule.action}
                    onChange={(e) => setNewSchedule({ ...newSchedule, action: e.target.value as any })}
                    className="w-full px-3 py-2 rounded-lg bg-background border border-border text-sm"
                  >
                    <option value="start">Start</option>
                    <option value="stop">Stop</option>
                    <option value="restart">Restart</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Timezone</label>
                  <input
                    type="text"
                    value={newSchedule.timezone}
                    onChange={(e) => setNewSchedule({ ...newSchedule, timezone: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg bg-background border border-border text-sm"
                    placeholder="UTC"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Schedule</label>
                <CronBuilder
                  value={newSchedule.cron_expression}
                  onChange={(cron) => setNewSchedule({ ...newSchedule, cron_expression: cron })}
                />
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    createSchedule.mutate({ serverId, data: newSchedule });
                    setShowScheduleForm(false);
                    setNewSchedule({ action: 'start', cron_expression: '0 9 * * *', timezone: 'UTC', is_active: true });
                  }}
                  className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
                >
                  Create Schedule
                </button>
                <button
                  onClick={() => setShowScheduleForm(false)}
                  className="px-4 py-2 rounded-lg bg-muted text-muted-foreground text-sm font-medium hover:bg-muted/80 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {schedules.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Calendar className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No schedules configured</p>
              <p className="text-xs mt-1">Create a schedule to automate server actions</p>
            </div>
          ) : (
            <div className="space-y-2">
              {schedules.map((schedule) => (
                <div key={schedule.id} className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50">
                  <div className="flex items-center gap-3">
                    <div className={cn(
                      "p-1.5 rounded",
                      schedule.action === 'start' ? "bg-emerald-500/10 text-emerald-400" :
                      schedule.action === 'stop' ? "bg-amber-500/10 text-amber-400" :
                      "bg-primary/10 text-primary"
                    )}>
                      {schedule.action === 'start' ? <Play className="w-3.5 h-3.5" /> :
                       schedule.action === 'stop' ? <Square className="w-3.5 h-3.5" /> :
                       <RotateCcw className="w-3.5 h-3.5" />}
                    </div>
                    <div>
                      <p className="text-sm font-medium capitalize">{schedule.action}</p>
                      <p className="text-xs text-muted-foreground font-mono">{schedule.cron_expression}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={cn(
                      "text-xs px-2 py-0.5 rounded-full",
                      schedule.is_active ? "bg-emerald-500/10 text-emerald-400" : "bg-muted text-muted-foreground"
                    )}>
                      {schedule.is_active ? 'Active' : 'Inactive'}
                    </span>
                    {schedule.next_run_at && (
                      <span className="text-xs text-muted-foreground">
                        Next: {formatDate(schedule.next_run_at)}
                      </span>
                    )}
                    <button
                      onClick={() => {
                        if (confirm('Delete this schedule?')) {
                          deleteSchedule.mutate({ serverId, scheduleId: schedule.id });
                        }
                      }}
                      className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors"
                    >
                      <Trash className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </motion.div>
      )}

      {activeTab === 'logs' && (
        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.gentle}
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-primary" />
              <h3 className="text-base font-semibold">Container Logs</h3>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">
                {logsData?.tail ? `Last ${logsData.tail} lines` : 'Loading...'}
              </span>
            </div>
          </div>

          <div className="relative">
            <pre className="p-4 rounded-lg bg-black/50 border border-border/50 font-mono text-xs text-foreground/80 overflow-auto max-h-[600px] whitespace-pre-wrap break-all">
              {logsData?.logs || 'No logs available'}
            </pre>
          </div>
        </motion.div>
      )}
    </div>
  );
}
