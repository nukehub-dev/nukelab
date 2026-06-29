// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export interface DateRangeParams {
  days?: number
  from?: string
  to?: string
}

function buildQueryString(params: DateRangeParams): string {
  const qs = new URLSearchParams()
  if (params.from && params.to) {
    qs.set('from', params.from)
    qs.set('to', params.to)
  } else {
    qs.set('days', String(params.days ?? 30))
  }
  return qs.toString()
}

export interface DailyUsage {
  date: string
  avg_cpu: number
  peak_cpu: number
  avg_memory: number
  peak_memory: number
  avg_network_rx: number
  avg_network_tx: number
  avg_disk_read: number
  avg_disk_write: number
  avg_gpu: number
  peak_gpu: number
  data_points: number
  daily_cost: number
}

export interface ServerBreakdown {
  server_id: string
  server_name: string
  cost: number
}

export interface PeakStats {
  peak_cpu: number
  peak_memory: number
  peak_gpu: number
  overall_avg_cpu: number
  overall_avg_memory: number
}

export interface UserUsageData {
  user_id: string
  period_days: number
  daily_usage: DailyUsage[]
  total_cost: number
  prev_cost: number
  cost_trend: number
  server_breakdown: ServerBreakdown[]
  peak_stats: PeakStats
  active_days: number
}

export interface GlobalUsageData {
  period_days: number
  server_creation_by_day: {
    date: string
    count: number
  }[]
  total_credits_consumed: number
  active_users: number
  total_users: number
  new_users: number
  total_servers: number
  running_servers: number
  server_status_breakdown: Record<string, number>
  avg_platform_cpu: number
  avg_platform_memory: number
  total_runtime_hours: number
}

export interface TopConsumer {
  user_id: string
  username: string
  credits_consumed: number
}

export interface CreditFlowData {
  date: string
  credits_consumed: number
  credits_granted: number
}

export interface UserGrowthData {
  date: string
  count: number
}

export interface LoginEventData {
  date: string
  count: number
}

export interface PlatformMetricsData {
  date: string
  avg_cpu: number
  peak_cpu: number
  avg_memory: number
  peak_memory: number
  avg_network_rx: number
  avg_network_tx: number
  avg_disk_read: number
  avg_disk_write: number
  data_points: number
}

export interface VolumeVisibilityItem {
  visibility: string
  count: number
}

export interface VolumeStatusItem {
  status: string
  count: number
}

export interface VolumeAnalytics {
  total_volumes: number
  total_storage_used_gb: number
  total_storage_capacity_gb: number
  storage_utilization_percent: number
  volumes_by_visibility: VolumeVisibilityItem[]
  volumes_by_status: VolumeStatusItem[]
}

export interface WorkspaceAnalytics {
  total_workspaces: number
  total_members: number
  avg_members_per_workspace: number
  workspace_adoption_rate: number
  unique_workspace_users: number
  total_users: number
}

export interface EnvironmentUsage {
  id: string
  name: string
  server_count: number
}

export interface PlanUsage {
  id: string
  name: string
  server_count: number
}

export interface RequestMetricEndpoint {
  path: string
  method: string
  count: number
  avg_duration_ms: number
  p50_ms: number
  p95_ms: number
  p99_ms: number
  error_count: number
  error_rate: number
}

export interface RequestMetricsData {
  endpoints: RequestMetricEndpoint[]
  summary: {
    total_requests: number
    avg_duration_ms: number
    total_errors: number
    error_rate: number
  }
  recent: Array<{
    id: string
    method: string
    path: string
    status_code: number
    duration_ms: number
    correlation_id: string
    created_at: string
  }>
  filters: Record<string, unknown>
}

export function useUserUsage(userId: string, params: DateRangeParams = {}) {
  const qs = buildQueryString(params)
  return useQuery({
    queryKey: ['analytics', 'user', userId, params],
    queryFn: async () => {
      const response = await api.get<UserUsageData>(`/analytics/users/${userId}/usage?${qs}`)
      return response
    },
    enabled: !!userId,
  })
}

export function useGlobalUsage(params: DateRangeParams = {}) {
  const qs = buildQueryString(params)
  return useQuery({
    queryKey: ['analytics', 'global', params],
    queryFn: async () => {
      const response = await api.get<GlobalUsageData>(`/analytics/global?${qs}`)
      return response
    },
    staleTime: 0,
  })
}

export function useTopConsumers(params: DateRangeParams & { limit?: number } = {}) {
  const { limit = 10, ...dateParams } = params
  const qs = new URLSearchParams(buildQueryString(dateParams))
  qs.set('limit', String(limit))
  return useQuery({
    queryKey: ['analytics', 'top-consumers', params],
    queryFn: async () => {
      const response = await api.get<{ consumers: TopConsumer[] }>(`/analytics/top-consumers?${qs}`)
      return response.consumers
    },
    staleTime: 0,
  })
}

export function useCreditFlow(params: DateRangeParams = {}) {
  const qs = buildQueryString(params)
  return useQuery({
    queryKey: ['analytics', 'credit-flow', params],
    queryFn: async () => {
      const response = await api.get<{ credit_flow: CreditFlowData[] }>(
        `/analytics/credit-flow?${qs}`
      )
      return response.credit_flow
    },
    staleTime: 0,
  })
}

export function useUserGrowth(params: DateRangeParams = {}) {
  const qs = buildQueryString(params)
  return useQuery({
    queryKey: ['analytics', 'user-growth', params],
    queryFn: async () => {
      const response = await api.get<{ user_growth: UserGrowthData[] }>(
        `/analytics/user-growth?${qs}`
      )
      return response.user_growth
    },
    staleTime: 0,
  })
}

export function useLoginEvents(params: DateRangeParams = {}) {
  const qs = buildQueryString(params)
  return useQuery({
    queryKey: ['analytics', 'logins', params],
    queryFn: async () => {
      const response = await api.get<{ login_events: LoginEventData[] }>(`/analytics/logins?${qs}`)
      return response.login_events
    },
    staleTime: 0,
  })
}

export function usePlatformMetrics(params: DateRangeParams = {}) {
  const qs = buildQueryString(params)
  return useQuery({
    queryKey: ['analytics', 'platform-metrics', params],
    queryFn: async () => {
      const response = await api.get<{ metrics: PlatformMetricsData[] }>(
        `/analytics/platform-metrics?${qs}`
      )
      return response.metrics
    },
    staleTime: 0,
  })
}

export function useVolumeAnalytics() {
  return useQuery({
    queryKey: ['analytics', 'volumes'],
    queryFn: async () => {
      const response = await api.get<VolumeAnalytics>('/analytics/volumes')
      return response
    },
  })
}

export function useWorkspaceAnalytics() {
  return useQuery({
    queryKey: ['analytics', 'workspaces'],
    queryFn: async () => {
      const response = await api.get<WorkspaceAnalytics>('/analytics/workspaces')
      return response
    },
  })
}

export function useEnvironmentUsage() {
  return useQuery({
    queryKey: ['analytics', 'environments'],
    queryFn: async () => {
      const response = await api.get<{ environments: EnvironmentUsage[] }>(
        '/analytics/environments'
      )
      return response.environments
    },
  })
}

export function usePlanUsage() {
  return useQuery({
    queryKey: ['analytics', 'plans'],
    queryFn: async () => {
      const response = await api.get<{ plans: PlanUsage[] }>('/analytics/plans')
      return response.plans
    },
  })
}

export function useRequestMetrics(params: DateRangeParams = {}) {
  const qs = buildQueryString(params)
  return useQuery({
    queryKey: ['analytics', 'request-metrics', params],
    queryFn: async () => {
      const response = await api.get<RequestMetricsData>(`/metrics/requests?${qs}`)
      return response
    },
    staleTime: 30000, // 30s cache for metrics
  })
}
