import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface SystemConfig {
  app_name: string;
  app_env: string;
  app_debug: boolean;
  maintenance_mode: boolean;
  maintenance_message: string;
}

export function useSystemConfig() {
  return useQuery({
    queryKey: ['system-config'],
    queryFn: async () => {
      return api.get<SystemConfig>('/system/config');
    },
    enabled: true,
  });
}

export function useUpdateSystemConfig() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: { maintenance_mode?: boolean; maintenance_message?: string }) => {
      return api.put<{ success: boolean; updates: Record<string, unknown> }>('/system/config', payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['system-config'] });
    },
  });
}

export function useToggleMaintenance() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ enabled, message }: { enabled: boolean; message?: string }) => {
      return api.post<{ success: boolean; maintenance_mode: boolean; message: string }>(
        `/system/maintenance?enabled=${enabled}${message ? `&message=${encodeURIComponent(message)}` : ''}`,
        {}
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['system-config'] });
      queryClient.invalidateQueries({ queryKey: ['health'] });
    },
  });
}
