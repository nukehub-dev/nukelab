import { useEffect, useState, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import { useWebSocket } from './use-websocket';

export interface ServerMetricPoint {
  timestamp: string;
  cpu: number;
  memory: number;
  memoryUsed: number;
  memoryTotal: number;
  diskRead: number;
  diskWrite: number;
  networkRx: number;
  networkTx: number;
}

interface MetricApiResponse {
  metrics: Array<{
    server_id: string;
    container_id: string;
    cpu: { percent: number | null; cores: number | null };
    memory: { percent: number | null; used: number | null; total: number | null };
    disk: { read_bytes: number | null; write_bytes: number | null };
    network: { rx_bytes: number | null; tx_bytes: number | null };
    collected_at: string;
  }>;
  count: number;
}

const MAX_POINTS = 60;

function parseApiMetric(metric: MetricApiResponse['metrics'][number]): ServerMetricPoint {
  const date = new Date(metric.collected_at);
  const timestamp = date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

  return {
    timestamp,
    cpu: Number(metric.cpu?.percent) || 0,
    memory: Number(metric.memory?.percent) || 0,
    memoryUsed: Number(metric.memory?.used) || 0,
    memoryTotal: Number(metric.memory?.total) || 0,
    diskRead: Number(metric.disk?.read_bytes) || 0,
    diskWrite: Number(metric.disk?.write_bytes) || 0,
    networkRx: Number(metric.network?.rx_bytes) || 0,
    networkTx: Number(metric.network?.tx_bytes) || 0,
  };
}

function parseWsMetric(data: {
  server_id: string;
  cpu_percent?: number;
  memory_percent?: number;
  memory_used?: number;
  memory_total?: number;
  disk_read_bytes?: number;
  disk_write_bytes?: number;
  network_rx_bytes?: number;
  network_tx_bytes?: number;
}): ServerMetricPoint {
  const timestamp = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

  return {
    timestamp,
    cpu: Number(data.cpu_percent) || 0,
    memory: Number(data.memory_percent) || 0,
    memoryUsed: Number(data.memory_used) || 0,
    memoryTotal: Number(data.memory_total) || 0,
    diskRead: Number(data.disk_read_bytes) || 0,
    diskWrite: Number(data.disk_write_bytes) || 0,
    networkRx: Number(data.network_rx_bytes) || 0,
    networkTx: Number(data.network_tx_bytes) || 0,
  };
}

export function useServerMetrics(serverId: string | undefined) {
  const [metrics, setMetrics] = useState<ServerMetricPoint[]>([]);
  const [currentMetrics, setCurrentMetrics] = useState({
    cpu: 0,
    memory: 0,
    memoryUsed: 0,
    memoryTotal: 0,
    diskRead: 0,
    diskWrite: 0,
    networkRx: 0,
    networkTx: 0,
  });
  const hasInitializedRef = useRef(false);

  const { isConnected, subscribe, unsubscribe, onMessage } = useWebSocket({ autoConnect: true });

  // 1. Fetch historical data from REST API on mount
  const { data: historyData, isLoading: isHistoryLoading } = useQuery({
    queryKey: ['server-metrics', serverId],
    queryFn: async () => {
      if (!serverId) return null;
      const response = await api.get<MetricApiResponse>(`/metrics/servers/${serverId}?limit=${MAX_POINTS}`);
      return response;
    },
    enabled: !!serverId,
    staleTime: 1000 * 60 * 5, // 5 minutes
  });

  // 2. Initialize metrics from history when data arrives
  useEffect(() => {
    if (historyData && !hasInitializedRef.current) {
      const parsed = historyData.metrics.map(parseApiMetric);
      if (parsed.length > 0) {
        setMetrics(parsed);
        const latest = parsed[parsed.length - 1];
        setCurrentMetrics({
          cpu: latest.cpu,
          memory: latest.memory,
          memoryUsed: latest.memoryUsed,
          memoryTotal: latest.memoryTotal,
          diskRead: latest.diskRead,
          diskWrite: latest.diskWrite,
          networkRx: latest.networkRx,
          networkTx: latest.networkTx,
        });
      }
      hasInitializedRef.current = true;
    }
  }, [historyData]);

  // 3. Subscribe to WebSocket for live updates
  useEffect(() => {
    if (isConnected && serverId) {
      subscribe('server', serverId);
      return () => {
        unsubscribe('server', serverId);
      };
    }
  }, [isConnected, serverId, subscribe, unsubscribe]);

  // 4. Handle incoming WebSocket messages
  useEffect(() => {
    const unsubscribeHandler = onMessage((message) => {
      if (message.event === 'metrics:server') {
        const data = message.data as {
          server_id: string;
          cpu_percent?: number;
          memory_percent?: number;
          memory_used?: number;
          memory_total?: number;
          disk_read_bytes?: number;
          disk_write_bytes?: number;
          network_rx_bytes?: number;
          network_tx_bytes?: number;
        };

        if (data.server_id !== serverId) return;

        const point = parseWsMetric(data);

        setCurrentMetrics({
          cpu: point.cpu,
          memory: point.memory,
          memoryUsed: point.memoryUsed,
          memoryTotal: point.memoryTotal,
          diskRead: point.diskRead,
          diskWrite: point.diskWrite,
          networkRx: point.networkRx,
          networkTx: point.networkTx,
        });

        setMetrics((prev) => {
          const next = [...prev, point];
          return next.slice(-MAX_POINTS);
        });
      }
    });

    return unsubscribeHandler;
  }, [onMessage, serverId]);

  // 5. Reset initialization when serverId changes
  useEffect(() => {
    hasInitializedRef.current = false;
    setMetrics([]);
    setCurrentMetrics({ cpu: 0, memory: 0, memoryUsed: 0, memoryTotal: 0, diskRead: 0, diskWrite: 0, networkRx: 0, networkTx: 0 });
  }, [serverId]);

  return {
    metrics,
    currentMetrics,
    isLoading: isHistoryLoading && metrics.length === 0,
    isLive: isConnected,
  };
}
