import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface SystemServiceHealth {
  status: 'healthy' | 'unhealthy' | 'disabled';
  latency_ms?: number;
  error?: string;
  host?: string;
  port?: number;
  message?: string;
  version?: string;
  runtime?: string;
}

export interface SystemHealth {
  status: 'healthy' | 'degraded';
  timestamp: number;
  services: {
    database?: SystemServiceHealth;
    redis?: SystemServiceHealth;
    containers?: SystemServiceHealth;
    smtp?: SystemServiceHealth;
    partitions?: SystemServiceHealth;
  };
  resources: {
    cpu: {
      percent: number;
      count: number;
      count_logical: number;
      freq_mhz: number | null;
    };
    memory: {
      percent: number;
      total_bytes: number;
      available_bytes: number;
      used_bytes: number;
    };
    disk: {
      path: string;
      percent: number;
      total_bytes: number;
      used_bytes: number;
      free_bytes: number;
      fstype: string | null;
    };
    container_disk?: {
      path: string;
      percent: number;
      total_bytes: number;
      used_bytes: number;
      free_bytes: number;
      fstype: string | null;
    };
    load_average: [number, number, number];
  };
}

export interface ContainerHealthCheck {
  id: string;
  server_id: string;
  server_name: string;
  username: string;
  container_id: string;
  status: string;
  exit_code: number | null;
  output: string | null;
  consecutive_failures: number;
  last_success_at: string | null;
  checked_at: string | null;
}

export interface RestartEvent {
  id: string;
  server_id: string;
  server_name: string;
  username: string;
  status: string;
  output: string | null;
  checked_at: string | null;
}

export interface PaginationInfo {
  page: number;
  limit: number;
  total: number;
  total_pages: number;
}

export interface ContainerHealthData {
  status_counts: Record<string, number>;
  latest_checks: ContainerHealthCheck[];
  unhealthy_count: number;
  unknown_count: number;
  restarting_count: number;
  restart_failed_count: number;
  pagination: PaginationInfo;
}

export interface HealthMonitoringData {
  system: SystemHealth;
  containers: ContainerHealthData;
  recent_restarts: RestartEvent[];
}

export interface HealthMonitoringParams {
  page?: number;
  limit?: number;
  status?: string | null;
  search?: string | null;
}

export function useHealthMonitoring(params: HealthMonitoringParams = {}) {
  const { page = 1, limit = 20, status, search } = params;

  const queryParams = new URLSearchParams();
  queryParams.set('page', String(page));
  queryParams.set('limit', String(limit));
  if (status) queryParams.set('status', status);
  if (search) queryParams.set('search', search);

  return useQuery<HealthMonitoringData>({
    queryKey: ['health-monitoring', page, limit, status, search],
    queryFn: async () => {
      return api.get<HealthMonitoringData>(`/admin/health/monitoring?${queryParams.toString()}`);
    },
    refetchInterval: 30000,
    staleTime: 1000 * 15,
  });
}
