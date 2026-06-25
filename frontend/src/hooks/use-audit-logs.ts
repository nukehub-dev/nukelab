import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export interface ActivityLog {
  id: string
  actor_id: string | null
  action: string
  target_type: string
  target_id: string | null
  details: Record<string, unknown>
  before_state: Record<string, unknown>
  after_state: Record<string, unknown>
  request_id: string | null
  ip_address: string | null
  user_agent: string | null
  created_at: string
}

export interface AuditLogsResponse {
  logs: ActivityLog[]
  pagination: {
    page: number
    limit: number
    total: number
    total_pages: number
  }
}

export interface UseAuditLogsOptions {
  user_id?: string
  action?: string
  target_type?: string
  from_date?: string
  to_date?: string
  page?: number
  limit?: number
}

export function useAuditLogs(options: UseAuditLogsOptions = {}) {
  const { user_id, action, target_type, from_date, to_date, page = 1, limit = 50 } = options

  const params = new URLSearchParams()
  params.set('page', String(page))
  params.set('limit', String(limit))
  if (user_id) params.set('user_id', user_id)
  if (action) params.set('action', action)
  if (target_type) params.set('target_type', target_type)
  if (from_date) params.set('from_date', from_date)
  if (to_date) params.set('to_date', to_date)

  return useQuery<AuditLogsResponse>({
    queryKey: ['audit-logs', user_id, action, target_type, from_date, to_date, page, limit],
    queryFn: () => api.get<AuditLogsResponse>(`/admin/activity?${params.toString()}`),
  })
}
