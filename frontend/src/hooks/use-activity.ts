import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface ActivityItem {
  id: string;
  actor_id: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  timestamp: string;
  details: Record<string, unknown>;
}

export interface ActivityResponse {
  activities: ActivityItem[];
  pagination: {
    page: number;
    limit: number;
    total: number;
    total_pages: number;
  };
}

export interface UseActivityOptions {
  page?: number;
  limit?: number;
  action?: string;
  target_type?: string;
  from_date?: string;
  to_date?: string;
}

export function useActivity(options: UseActivityOptions = {}) {
  const { page = 1, limit = 25, action, target_type, from_date, to_date } = options;

  const params = new URLSearchParams();
  params.set('page', String(page));
  params.set('limit', String(limit));
  if (action) params.set('action', action);
  if (target_type) params.set('target_type', target_type);
  if (from_date) params.set('from_date', from_date);
  if (to_date) params.set('to_date', to_date);

  return useQuery({
    queryKey: ['activity', page, limit, action, target_type, from_date, to_date],
    queryFn: () => api.get<ActivityResponse>(`/users/me/activity?${params.toString()}`),
    staleTime: 10000,
  });
}
