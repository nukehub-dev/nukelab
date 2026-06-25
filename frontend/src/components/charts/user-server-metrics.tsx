import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Cpu, HardDrive, Network, Server, Activity } from 'lucide-react'
import { useSharedWebSocket } from '../../hooks/use-shared-websocket'
import { GaugeChart } from './gauge-chart'
import { formatBytes } from '../../lib/utils'
import { springs } from '../../lib/animations'
import type { Server as ServerType } from '../../types/api'

interface ServerMetricData {
  cpu_percent: number
  memory_percent: number
  memory_used: number
  memory_total: number
  network_rx: number
  network_tx: number
  disk_read: number
  disk_write: number
  timestamp: number
}

interface ServerMetricCardProps {
  server: ServerType
  metric: ServerMetricData
}

function ServerMetricCard({ server, metric }: ServerMetricCardProps) {
  return (
    <motion.div
      className="bubble p-5 hover-lift cursor-default"
      initial={{ opacity: 0, scale: 0.95, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={springs.gentle}
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <Server className="w-4 h-4 text-primary" />
          </div>
          <div>
            <h3 className="font-medium text-sm">{server.name}</h3>
            <p className="text-xs text-muted-foreground">{server.external_url || 'No URL'}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
          </span>
          <span className="text-xs text-emerald-400">Running</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* CPU */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Cpu className="w-3.5 h-3.5 text-chart-1" />
              <span className="text-xs text-muted-foreground">CPU</span>
            </div>
            <span className="text-sm font-bold">{metric.cpu_percent.toFixed(1)}%</span>
          </div>
          <GaugeChart
            value={metric.cpu_percent}
            max={100}
            size={60}
            strokeWidth={5}
            showValue={false}
          />
        </div>

        {/* Memory */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-chart-2" />
              <span className="text-xs text-muted-foreground">Memory</span>
            </div>
            <span className="text-sm font-bold">{metric.memory_percent.toFixed(1)}%</span>
          </div>
          <GaugeChart
            value={metric.memory_percent}
            max={100}
            size={60}
            strokeWidth={5}
            showValue={false}
          />
          <p className="text-[10px] text-muted-foreground text-center">
            {formatBytes(metric.memory_used)} / {formatBytes(metric.memory_total)}
          </p>
        </div>

        {/* Network */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Network className="w-3.5 h-3.5 text-chart-4" />
              <span className="text-xs text-muted-foreground">Network</span>
            </div>
          </div>
          <div className="space-y-1">
            <div className="flex justify-between text-[10px]">
              <span className="text-muted-foreground">RX</span>
              <span className="font-medium">{formatBytes(metric.network_rx)}/s</span>
            </div>
            <div className="flex justify-between text-[10px]">
              <span className="text-muted-foreground">TX</span>
              <span className="font-medium">{formatBytes(metric.network_tx)}/s</span>
            </div>
          </div>
        </div>

        {/* Disk I/O */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <HardDrive className="w-3.5 h-3.5 text-chart-3" />
              <span className="text-xs text-muted-foreground">Disk I/O</span>
            </div>
          </div>
          <div className="space-y-1">
            <div className="flex justify-between text-[10px]">
              <span className="text-muted-foreground">Read</span>
              <span className="font-medium">{formatBytes(metric.disk_read)}/s</span>
            </div>
            <div className="flex justify-between text-[10px]">
              <span className="text-muted-foreground">Write</span>
              <span className="font-medium">{formatBytes(metric.disk_write)}/s</span>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  )
}

interface UserServerMetricsProps {
  servers: ServerType[]
}

export function UserServerMetrics({ servers }: UserServerMetricsProps) {
  const runningServers = useMemo(
    () => servers.filter((s) => s.status === 'running' && s.container_id),
    [servers]
  )

  const { isConnected, subscribe, unsubscribe, onMessage } = useSharedWebSocket()
  const subscribedRef = useRef<Set<string>>(new Set())

  const [serverMetrics, setServerMetrics] = useState<Record<string, ServerMetricData>>({})

  // Subscribe to each running server
  useEffect(() => {
    if (!isConnected) return

    runningServers.forEach((server) => {
      if (!subscribedRef.current.has(server.id)) {
        subscribe('server', server.id)
        subscribedRef.current.add(server.id)
      }
    })

    // Unsubscribe from stopped servers
    const currentIds = new Set(runningServers.map((s) => s.id))
    subscribedRef.current.forEach((id) => {
      if (!currentIds.has(id)) {
        unsubscribe('server', id)
        subscribedRef.current.delete(id)
        setServerMetrics((prev) => {
          const next = { ...prev }
          delete next[id]
          return next
        })
      }
    })

    const subscribedIds = Array.from(subscribedRef.current)

    return () => {
      subscribedIds.forEach((id) => {
        unsubscribe('server', id)
      })
    }
  }, [isConnected, runningServers, subscribe, unsubscribe])

  // Handle incoming metrics
  useEffect(() => {
    const unsubscribeHandler = onMessage((message) => {
      if (message.event === 'metrics:server' || message.event === 'metrics:all') {
        const raw = message.data as Partial<{
          server_id: string
          cpu_percent?: number
          memory_percent?: number
          memory_used?: number
          memory_total?: number
          network_rx_bytes?: number
          network_tx_bytes?: number
          disk_read_bytes?: number
          disk_write_bytes?: number
        }>

        const serverId = raw.server_id
        if (!serverId) return

        setServerMetrics((prev) => ({
          ...prev,
          [serverId]: {
            cpu_percent: Number(raw.cpu_percent) || 0,
            memory_percent: Number(raw.memory_percent) || 0,
            memory_used: Number(raw.memory_used) || 0,
            memory_total: Number(raw.memory_total) || 0,
            network_rx: Number(raw.network_rx_bytes) || 0,
            network_tx: Number(raw.network_tx_bytes) || 0,
            disk_read: Number(raw.disk_read_bytes) || 0,
            disk_write: Number(raw.disk_write_bytes) || 0,
            timestamp: Date.now(),
          },
        }))
      }
    })

    return unsubscribeHandler
  }, [onMessage])

  if (runningServers.length === 0) {
    return (
      <motion.div
        className="bubble p-8 text-center"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
      >
        <Server className="w-12 h-12 text-muted-foreground mx-auto mb-4 opacity-50" />
        <h3 className="text-lg font-medium mb-2">No Active Servers</h3>
        <p className="text-sm text-muted-foreground mb-4">
          You don&apos;t have any running servers. Deploy a server to see live metrics.
        </p>
      </motion.div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <div
          className={`w-2 h-2 rounded-full transition-colors ${isConnected ? 'bg-emerald-400 live-pulse' : 'bg-muted-foreground'}`}
        />
        <span className="text-xs text-muted-foreground">
          {isConnected ? 'Live metrics' : 'Connecting...'}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {runningServers.map((server) => (
          <ServerMetricCard
            key={server.id}
            server={server}
            metric={
              serverMetrics[server.id] || {
                cpu_percent: 0,
                memory_percent: 0,
                memory_used: 0,
                memory_total: 0,
                network_rx: 0,
                network_tx: 0,
                disk_read: 0,
                disk_write: 0,
                timestamp: 0,
              }
            }
          />
        ))}
      </div>
    </div>
  )
}
