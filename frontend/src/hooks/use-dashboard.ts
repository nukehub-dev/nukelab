// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

interface DashboardData {
  my_servers: {
    total: number
    running: number
    stopped: number
    pending: number
  }
  my_nukes: {
    balance: number
    daily_allowance: number
    hourly_cost: number
    estimated_hours_left: number
  }
  recent_activity: Array<{
    id: string
    action: string
    target_type: string
    target_id: string | null
    timestamp: string
  }>
  platform_stats?: {
    total_users: number
    total_servers: number
    active_servers: number
    total_nukes: number
    system_health: string
  }
}

export function useDashboard() {
  return useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api.get<DashboardData>('/dashboard/'),
    refetchInterval: 30000, // Refresh every 30 seconds
    staleTime: 15000, // Consider data stale after 15 seconds
  })
}
