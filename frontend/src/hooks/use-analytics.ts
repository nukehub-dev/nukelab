import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface UserUsageData {
  user_id: string;
  period_days: number;
  daily_usage: {
    date: string;
    avg_cpu: number;
    avg_memory: number;
    data_points: number;
  }[];
  total_cost: number;
}

export interface GlobalUsageData {
  period_days: number;
  server_creation_by_day: {
    date: string;
    count: number;
  }[];
  total_credits_consumed: number;
  active_users: number;
}

export interface TopConsumer {
  user_id: string;
  username: string;
  credits_consumed: number;
}

export interface EnvironmentUsage {
  id: string;
  name: string;
  server_count: number;
}

export interface PlanUsage {
  id: string;
  name: string;
  server_count: number;
}

export function useUserUsage(userId: string, days: number = 30) {
  return useQuery({
    queryKey: ['analytics', 'user', userId, days],
    queryFn: async () => {
      const response = await api.get<UserUsageData>(`/analytics/users/${userId}/usage?days=${days}`);
      return response;
    },
    enabled: !!userId,
  });
}

export function useGlobalUsage(days: number = 30) {
  return useQuery({
    queryKey: ['analytics', 'global', days],
    queryFn: async () => {
      const response = await api.get<GlobalUsageData>(`/analytics/global?days=${days}`);
      return response;
    },
  });
}

export function useTopConsumers(days: number = 30, limit: number = 10) {
  return useQuery({
    queryKey: ['analytics', 'top-consumers', days, limit],
    queryFn: async () => {
      const response = await api.get<{ consumers: TopConsumer[] }>(`/analytics/top-consumers?days=${days}&limit=${limit}`);
      return response.consumers;
    },
  });
}

export function useEnvironmentUsage() {
  return useQuery({
    queryKey: ['analytics', 'environments'],
    queryFn: async () => {
      const response = await api.get<{ environments: EnvironmentUsage[] }>('/analytics/environments');
      return response.environments;
    },
  });
}

export function usePlanUsage() {
  return useQuery({
    queryKey: ['analytics', 'plans'],
    queryFn: async () => {
      const response = await api.get<{ plans: PlanUsage[] }>('/analytics/plans');
      return response.plans;
    },
  });
}
