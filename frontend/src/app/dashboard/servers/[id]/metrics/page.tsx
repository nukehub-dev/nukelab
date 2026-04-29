'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { metricsApi, serversApi } from '@/lib/api';
import {
  Cpu,
  MemoryStick,
  HardDrive,
  Network,
  Activity,
  ArrowLeft,
  RefreshCw
} from 'lucide-react';
import Link from 'next/link';

interface MetricData {
  cpu: { percent: number; cores: number };
  memory: { percent: number; used: number; total: number };
  disk: { read_bytes: number; write_bytes: number };
  network: { rx_bytes: number; tx_bytes: number };
  pids: number;
  collected_at: string;
}

export default function ServerMetricsPage() {
  const params = useParams();
  const serverId = params.id as string;
  const [metrics, setMetrics] = useState<MetricData[]>([]);
  const [latest, setLatest] = useState<MetricData | null>(null);
  const [serverName, setServerName] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchData = async () => {
    try {
      const [metricsData, latestData, serversData] = await Promise.all([
        metricsApi.getServerMetrics(serverId, { interval: '5m' }),
        metricsApi.getServerLatestMetrics(serverId),
        serversApi.list(),
      ]);

      setMetrics(metricsData.metrics || []);
      setLatest(latestData.metric);
      setError('');

      const server = serversData.find((s: any) => s.id === serverId);
      if (server) setServerName(server.name);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load metrics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [serverId]);

  const formatBytes = (bytes: number) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center">
          <Link
            href="/dashboard/servers"
            className="flex items-center text-gray-600 hover:text-blue-600 mr-4"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{serverName || 'Server'} Metrics</h1>
            <p className="text-gray-600">Real-time container performance</p>
          </div>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
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

      {/* Latest Metrics Cards */}
      {latest && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="bg-blue-500 rounded-lg p-3">
                <Cpu className="w-6 h-6 text-white" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">CPU</p>
                <p className="text-2xl font-bold text-gray-900">{latest.cpu?.percent?.toFixed(1) || 0}%</p>
                <p className="text-xs text-gray-500">{latest.cpu?.cores || 0} cores</p>
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
                <p className="text-2xl font-bold text-gray-900">{latest.memory?.percent?.toFixed(1) || 0}%</p>
                <p className="text-xs text-gray-500">{formatBytes(latest.memory?.used || 0)} / {formatBytes(latest.memory?.total || 0)}</p>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="bg-purple-500 rounded-lg p-3">
                <HardDrive className="w-6 h-6 text-white" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Disk I/O</p>
                <p className="text-2xl font-bold text-gray-900">R: {formatBytes(latest.disk?.read_bytes || 0)}</p>
                <p className="text-xs text-gray-500">W: {formatBytes(latest.disk?.write_bytes || 0)}</p>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="bg-orange-500 rounded-lg p-3">
                <Network className="w-6 h-6 text-white" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Network</p>
                <p className="text-2xl font-bold text-gray-900">↑; {formatBytes(latest.network?.tx_bytes || 0)}</p>
                <p className="text-xs text-gray-500">↓; {formatBytes(latest.network?.rx_bytes || 0)}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Metrics History Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="px-6 py-4 border-b">
          <h2 className="text-lg font-semibold text-gray-900">Metrics History</h2>
        </div>

        {metrics.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            <Activity className="w-12 h-12 mx-auto mb-4 text-gray-400" />
            <p>No metrics data available yet</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">CPU%</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Memory%</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Memory</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Network ↑;</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Network ↓;</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">PIDs</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {metrics.slice(0, 50).map((metric, idx) => (
                  <tr key={idx} className="hover:bg-gray-50">
                    <td className="px-4 py-3 text-sm text-gray-900">
                      {new Date(metric.collected_at).toLocaleTimeString()}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{metric.cpu?.percent?.toFixed(1)}%</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{metric.memory?.percent?.toFixed(1)}%</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{formatBytes(metric.memory?.used || 0)}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{formatBytes(metric.network?.tx_bytes || 0)}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{formatBytes(metric.network?.rx_bytes || 0)}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{metric.pids || 0}</td>
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
