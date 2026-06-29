// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useState, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useSharedWebSocket } from './use-shared-websocket'
import { useAuthStore, PERMISSIONS } from '../stores/auth-store'

export interface DashboardMetricPoint {
  timestamp: string
  // CPU
  cpu: number
  cpuCount: number
  // Memory (in bytes for chart, percent for display)
  memoryPercent: number
  memoryUsed: number
  memoryTotal: number
  memoryAvailable: number
  // Disk I/O (bytes/sec)
  diskRead: number
  diskWrite: number
  diskPercent: number
  diskUsed: number
  diskTotal: number
  // Network (bytes/sec)
  networkRx: number
  networkTx: number
}

interface SystemMetricApiResponse {
  metrics: Array<{
    cpu: {
      percent: number | null
      count: number | null
      load_1m: number | null
      load_5m: number | null
      load_15m: number | null
    }
    memory: {
      used: number | null
      total: number | null
      percent: number | null
      available: number | null
    }
    disk: {
      used: number | null
      total: number | null
      percent: number | null
      read_bytes: number | null
      write_bytes: number | null
    }
    network: {
      rx_bytes: number | null
      tx_bytes: number | null
    }
    collected_at: string
  }>
  count: number
}

const MAX_POINTS = 60

function parseApiMetric(metric: SystemMetricApiResponse['metrics'][number]): DashboardMetricPoint {
  const date = new Date(metric.collected_at)
  const timestamp = date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })

  return {
    timestamp,
    cpu: Number(metric.cpu?.percent) || 0,
    cpuCount: Number(metric.cpu?.count) || 0,
    memoryPercent: Number(metric.memory?.percent) || 0,
    memoryUsed: Number(metric.memory?.used) || 0,
    memoryTotal: Number(metric.memory?.total) || 0,
    memoryAvailable: Number(metric.memory?.available) || 0,
    diskRead: Number(metric.disk?.read_bytes) || 0,
    diskWrite: Number(metric.disk?.write_bytes) || 0,
    diskPercent: Number(metric.disk?.percent) || 0,
    diskUsed: Number(metric.disk?.used) || 0,
    diskTotal: Number(metric.disk?.total) || 0,
    networkRx: Number(metric.network?.rx_bytes) || 0,
    networkTx: Number(metric.network?.tx_bytes) || 0,
  }
}

function parseWsMetric(data: {
  cpu_percent?: number
  cpu_count?: number
  memory_percent?: number
  memory_used?: number
  memory_total?: number
  memory_available?: number
  disk_percent?: number
  disk_used?: number
  disk_total?: number
  disk_read_bytes?: number
  disk_write_bytes?: number
  network_rx_bytes?: number
  network_tx_bytes?: number
}): DashboardMetricPoint {
  const timestamp = new Date().toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })

  return {
    timestamp,
    cpu: Number(data.cpu_percent) || 0,
    cpuCount: Number(data.cpu_count) || 0,
    memoryPercent: Number(data.memory_percent) || 0,
    memoryUsed: Number(data.memory_used) || 0,
    memoryTotal: Number(data.memory_total) || 0,
    memoryAvailable: Number(data.memory_available) || 0,
    diskRead: Number(data.disk_read_bytes) || 0,
    diskWrite: Number(data.disk_write_bytes) || 0,
    diskPercent: Number(data.disk_percent) || 0,
    diskUsed: Number(data.disk_used) || 0,
    diskTotal: Number(data.disk_total) || 0,
    networkRx: Number(data.network_rx_bytes) || 0,
    networkTx: Number(data.network_tx_bytes) || 0,
  }
}

export function useDashboardMetrics() {
  const [metrics, setMetrics] = useState<DashboardMetricPoint[]>([])
  const [currentMetrics, setCurrentMetrics] = useState({
    cpu: 0,
    cpuCount: 0,
    memoryPercent: 0,
    memoryUsed: 0,
    memoryTotal: 0,
    diskRead: 0,
    diskWrite: 0,
    diskPercent: 0,
    diskUsed: 0,
    diskTotal: 0,
    networkRx: 0,
    networkTx: 0,
  })
  const [serverMetrics, setServerMetrics] = useState<
    Record<
      string,
      {
        cpu: number
        memoryPercent: number
        memoryUsed: number
        memoryTotal: number
        diskRead: number
        diskWrite: number
        networkRx: number
        networkTx: number
      }
    >
  >({})
  const hasInitializedRef = useRef(false)
  const canViewSystemMetrics = useAuthStore((state) =>
    state.hasPermission(PERMISSIONS.ADMIN_ACCESS)
  )

  const { isConnected, subscribe, unsubscribe, onMessage } = useSharedWebSocket()

  // 1. Fetch historical system metrics from REST API (admin only)
  const { data: historyData, isLoading: isHistoryLoading } = useQuery({
    queryKey: ['system-metrics'],
    queryFn: async () => {
      if (!canViewSystemMetrics) return null
      const response = await api.get<SystemMetricApiResponse>(`/metrics/system?limit=${MAX_POINTS}`)
      return response
    },
    enabled: canViewSystemMetrics,
    staleTime: 1000 * 60 * 5, // 5 minutes
  })

  // 2. Initialize from history (admin only)
  useEffect(() => {
    if (historyData && !hasInitializedRef.current) {
      const parsed = historyData.metrics.map(parseApiMetric)
      if (parsed.length > 0) {
        queueMicrotask(() => {
          setMetrics(parsed)
          const latest = parsed[parsed.length - 1]
          setCurrentMetrics({
            cpu: latest.cpu,
            cpuCount: latest.cpuCount,
            memoryPercent: latest.memoryPercent,
            memoryUsed: latest.memoryUsed,
            memoryTotal: latest.memoryTotal,
            diskRead: latest.diskRead,
            diskWrite: latest.diskWrite,
            diskPercent: latest.diskPercent,
            diskUsed: latest.diskUsed,
            diskTotal: latest.diskTotal,
            networkRx: latest.networkRx,
            networkTx: latest.networkTx,
          })
        })
      }
      hasInitializedRef.current = true
    }
  }, [historyData])

  // 3. Subscribe to global WebSocket (admin only for system metrics)
  useEffect(() => {
    if (isConnected && canViewSystemMetrics) {
      subscribe('global')
      return () => {
        unsubscribe('global')
      }
    }
  }, [isConnected, subscribe, unsubscribe, canViewSystemMetrics])

  // 4. Handle incoming WebSocket messages (admin only for system metrics)
  useEffect(() => {
    if (!canViewSystemMetrics) return

    const unsubscribeHandler = onMessage((message) => {
      if (message.event === 'metrics:system') {
        const data = message.data as {
          cpu_percent?: number
          cpu_count?: number
          memory_percent?: number
          memory_used?: number
          memory_total?: number
          memory_available?: number
          disk_percent?: number
          disk_used?: number
          disk_total?: number
          disk_read_bytes?: number
          disk_write_bytes?: number
          network_rx_bytes?: number
          network_tx_bytes?: number
        }

        const point = parseWsMetric(data)

        setCurrentMetrics({
          cpu: point.cpu,
          cpuCount: point.cpuCount,
          memoryPercent: point.memoryPercent,
          memoryUsed: point.memoryUsed,
          memoryTotal: point.memoryTotal,
          diskRead: point.diskRead,
          diskWrite: point.diskWrite,
          diskPercent: point.diskPercent,
          diskUsed: point.diskUsed,
          diskTotal: point.diskTotal,
          networkRx: point.networkRx,
          networkTx: point.networkTx,
        })

        setMetrics((prev) => {
          const next = [...prev, point]
          return next.slice(-MAX_POINTS)
        })
      }

      if (message.event === 'metrics:all' || message.event === 'metrics:server') {
        const raw = message.data as {
          server_id?: string
          cpu_percent?: number
          memory_percent?: number
          memory_used?: number
          memory_total?: number
          disk_read_bytes?: number
          disk_write_bytes?: number
          network_rx_bytes?: number
          network_tx_bytes?: number
        }

        if (!raw.server_id) return

        setServerMetrics((prev) => ({
          ...prev,
          [raw.server_id!]: {
            cpu: Number(raw.cpu_percent) || 0,
            memoryPercent: Number(raw.memory_percent) || 0,
            memoryUsed: Number(raw.memory_used) || 0,
            memoryTotal: Number(raw.memory_total) || 0,
            diskRead: Number(raw.disk_read_bytes) || 0,
            diskWrite: Number(raw.disk_write_bytes) || 0,
            networkRx: Number(raw.network_rx_bytes) || 0,
            networkTx: Number(raw.network_tx_bytes) || 0,
          },
        }))
      }
    })

    return unsubscribeHandler
  }, [onMessage, canViewSystemMetrics])

  return {
    metrics,
    currentMetrics,
    serverMetrics,
    isLoading: isHistoryLoading && metrics.length === 0,
    isLive: isConnected,
  }
}
