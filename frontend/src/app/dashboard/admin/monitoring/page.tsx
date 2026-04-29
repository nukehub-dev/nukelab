'use client';

import { useEffect, useState, useRef } from 'react';
import { useAuthStore } from '@/stores/authStore';
import { metricsApi } from '@/lib/api';
import {
  Activity,
  AlertTriangle,
  Server,
  Cpu,
  HardDrive,
  Network,
  MemoryStick,
  CheckCircle,
  XCircle,
  AlertCircle,
  RefreshCw
} from 'lucide-react';

interface SystemMetric {
  cpu: { percent: number; load_1m: number; load_5m: number; load_15m: number };
  memory: { percent: number; used: number; total: number; available: number };
  disk: { percent: number; used: number; total: number; read_bytes: number; write_bytes: number };
  network: { rx_bytes: number; tx_bytes: number };
  docker: { containers_running: number; containers_total: number; images_total: number };
  collected_at: string;
}

interface AlertItem {
  id: string;
  name: string;
  metric_type: string;
  operator: string;
  threshold: number;
  is_active: boolean;
}

interface AlertHistoryItem {
  id: string;
  metric_value: number;
  threshold: number;
  status: string;
  fired_at: string;
  acknowledged: boolean;
}

export default function MonitoringPage() {
  const { isAdmin } = useAuthStore();
  const [systemMetric, setSystemMetric] = useState<SystemMetric | null>(null);
  const [alertRules, setAlertRules] = useState<AlertItem[]>([]);
  const [alertHistory, setAlertHistory] = useState<AlertHistoryItem[]>([]);
  const [healthSummary, setHealthSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const wsRef = useRef<WebSocket | null>(null);

  const fetchData = async () => {
    try {
      const [system, rules, history, health] = await Promise.all([
        metricsApi.getLatestSystemMetrics(),
        metricsApi.getAlertRules(),
        metricsApi.getAlertHistory(),
        metricsApi.getHealthSummary(),
      ]);

      setSystemMetric(system.metric);
      setAlertRules(rules.rules || []);
      setAlertHistory(history.alerts || []);
      setHealthSummary(health);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load monitoring data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isAdmin()) return;
    fetchData();

    // Setup WebSocket for real-time metrics
    const connectWs = () => {
      const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8080/ws';
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('WebSocket connected');
        ws.send(JSON.stringify({ type: 'subscribe', scope: 'global' }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('WebSocket message:', data.event);
          if (data.event === 'metrics:system') {
            // Update system metrics in real-time
            const metric: any = data.data;
            setSystemMetric({
              cpu: {
                percent: metric.cpu_percent,
                load_1m: metric.cpu_load_1m,
                load_5m: metric.cpu_load_5m,
                load_15m: metric.cpu_load_15m,
              },
              memory: {
                percent: metric.memory_percent,
                used: metric.memory_used,
                total: metric.memory_total,
                available: metric.memory_available,
              },
              disk: {
                percent: metric.disk_percent,
                used: metric.disk_used,
                total: metric.disk_total,
                read_bytes: metric.disk_read_bytes,
                write_bytes: metric.disk_write_bytes,
              },
              network: {
                rx_bytes: metric.network_rx_bytes,
                tx_bytes: metric.network_tx_bytes,
              },
              docker: {
                containers_running: metric.docker_containers_running,
                containers_total: metric.docker_containers_total,
                images_total: metric.docker_images_total,
              },
              collected_at: metric.collected_at,
            });
          }
        } catch (err) {
          console.error('WebSocket message error:', err);
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
      };

      ws.onclose = () => {
        console.log('WebSocket closed, reconnecting in 5s...');
        setTimeout(connectWs, 5000);
      };
    };

    connectWs();

    const interval = setInterval(fetchData, 30000);

    return () => {
      clearInterval(interval);
      if (wsRef.current) {
        wsRef.current.onclose = null; // Prevent reconnect on cleanup
        wsRef.current.close();
      }
    };
  }, [isAdmin]);

  if (!isAdmin()) {
    return (
      <div className="text-center py-12">
        <AlertTriangle className="w-12 h-12 text-yellow-500 mx-auto mb-4" />
        <h2 className="text-xl font-bold text-gray-900">Access Denied</h2>
        <p className="text-gray-600 mt-2">You don't have permission to access this page.</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  const formatBytes = (bytes: number) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const activeAlerts = alertHistory.filter(a => a.status === 'fired');
  const acknowledgedAlerts = alertHistory.filter(a => a.status === 'acknowledged');

  return (
    <div>
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Monitoring</h1>
          <p className="mt-2 text-gray-600">Real-time system metrics and health status</p>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-6">
          {error}
        </div>
      )}

      {/* System Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="bg-blue-500 rounded-lg p-3">
              <Cpu className="w-6 h-6 text-white" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">CPU Usage</p>
              <p className="text-2xl font-bold text-gray-900">
                {systemMetric?.cpu?.percent?.toFixed(1) || 0}%
              </p>
              <p className="text-xs text-gray-500">
                Load: {systemMetric?.cpu?.load_1m?.toFixed(2) || 0}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="bg-green-500 rounded-lg p-3">
              <MemoryStick className="w-6 h-6 text-white" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">Memory</p>
              <p className="text-2xl font-bold text-gray-900">
                {systemMetric?.memory?.percent?.toFixed(1) || 0}%
              </p>
              <p className="text-xs text-gray-500">
                {formatBytes(systemMetric?.memory?.used || 0)} / {formatBytes(systemMetric?.memory?.total || 0)}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="bg-purple-500 rounded-lg p-3">
              <HardDrive className="w-6 h-6 text-white" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">Disk</p>
              <p className="text-2xl font-bold text-gray-900">
                {systemMetric?.disk?.percent?.toFixed(1) || 0}%
              </p>
              <p className="text-xs text-gray-500">
                {formatBytes(systemMetric?.disk?.used || 0)} / {formatBytes(systemMetric?.disk?.total || 0)}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="bg-orange-500 rounded-lg p-3">
              <Server className="w-6 h-6 text-white" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">Containers</p>
              <p className="text-2xl font-bold text-gray-900">
                {systemMetric?.docker?.containers_running || 0}
              </p>
              <p className="text-xs text-gray-500">
                {systemMetric?.docker?.containers_total || 0} total
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Health & Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Health Summary */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
            <Activity className="w-5 h-5 mr-2" />
            Health Status
          </h2>

          <div className="grid grid-cols-3 gap-4 mb-4">
            <div className="text-center p-4 bg-green-50 rounded-lg">
              <CheckCircle className="w-8 h-8 text-green-500 mx-auto mb-2" />
              <p className="text-2xl font-bold text-green-700">
                {healthSummary?.status_counts?.healthy || 0}
              </p>
              <p className="text-sm text-green-600">Healthy</p>
            </div>
            <div className="text-center p-4 bg-red-50 rounded-lg">
              <XCircle className="w-8 h-8 text-red-500 mx-auto mb-2" />
              <p className="text-2xl font-bold text-red-700">
                {healthSummary?.unhealthy_count || 0}
              </p>
              <p className="text-sm text-red-600">Unhealthy</p>
            </div>
            <div className="text-center p-4 bg-gray-50 rounded-lg">
              <AlertCircle className="w-8 h-8 text-gray-500 mx-auto mb-2" />
              <p className="text-2xl font-bold text-gray-700">
                {healthSummary?.unknown_count || 0}
              </p>
              <p className="text-sm text-gray-600">Unknown</p>
            </div>
          </div>
        </div>

        {/* Active Alerts */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
            <AlertTriangle className="w-5 h-5 mr-2" />
            Active Alerts
          </h2>

          {activeAlerts.length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-2" />
              <p>No active alerts</p>
            </div>
          ) : (
            <div className="space-y-3 max-h-64 overflow-y-auto">
              {activeAlerts.slice(0, 10).map((alert) => (
                <div key={alert.id} className="flex items-center p-3 bg-red-50 rounded-lg border border-red-200">
                  <AlertTriangle className="w-5 h-5 text-red-500 mr-3 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-red-900">
                      {alert.metric_value?.toFixed(1)} / {alert.threshold}
                    </p>
                    <p className="text-xs text-red-600">
                      {new Date(alert.fired_at).toLocaleString()}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Alert Rules */}
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Alert Rules</h2>

        {alertRules.length === 0 ? (
          <p className="text-gray-500 text-center py-8">No alert rules configured</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead>
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Metric</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Condition</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Threshold</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {alertRules.map((rule) => (
                  <tr key={rule.id}>
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{rule.name}</td>
                    <td className="px-4 py-3 text-sm text-gray-600 capitalize">{rule.metric_type}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{rule.operator}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{rule.threshold}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                        rule.is_active
                          ? 'bg-green-100 text-green-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}>
                        {rule.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
