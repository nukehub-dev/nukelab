import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface RetentionPolicy {
  metrics_retention_days: number;
  system_metrics_retention_days: number;
  health_check_retention_days: number;
  alert_history_retention_days: number;
  activity_log_retention_days: number;
  notification_retention_days: number;
  daily_rollup_retention_days: number;
  cleanup_enabled: boolean;
  cleanup_run_hour: number;
}

export function useRetentionPolicy() {
  return useQuery({
    queryKey: ['retention-policy'],
    queryFn: async () => {
      const response = await api.get<{ retention_policy: RetentionPolicy }>('/admin/retention');
      return response.retention_policy;
    },
    staleTime: 0,
  });
}

export function useUpdateRetentionPolicy() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: Partial<RetentionPolicy>) => {
      const response = await api.put<{ retention_policy: RetentionPolicy; success: boolean }>(
        '/admin/retention',
        payload
      );
      return response;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['retention-policy'] });
    },
  });
}
