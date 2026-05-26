import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface MaintenanceWindow {
  id: string;
  title: string;
  message: string;
  start_at: string;
  end_at: string;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  notify_offsets: number[];
  notified_offsets: number[];
  notified_at: string | null;
  auto_enabled: boolean;
  auto_disabled: boolean;
}

export interface MaintenanceWindowListResponse {
  windows: MaintenanceWindow[];
}

export interface MaintenanceWindowCreatePayload {
  title: string;
  message: string;
  start_at: string;
  end_at: string;
  is_active?: boolean;
  notify_offsets?: number[];
}

export interface MaintenanceWindowUpdatePayload {
  title?: string;
  message?: string;
  start_at?: string;
  end_at?: string;
  is_active?: boolean;
  notify_offsets?: number[];
}

export function useMaintenanceWindows(activeOnly?: boolean, futureOnly?: boolean) {
  return useQuery({
    queryKey: ['maintenance-windows', { activeOnly, futureOnly }],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (activeOnly) params.set('active_only', 'true');
      if (futureOnly) params.set('future_only', 'true');
      const query = params.toString();
      return api.get<MaintenanceWindowListResponse>(`/system/maintenance-windows${query ? `?${query}` : ''}`);
    },
  });
}

export function useCreateMaintenanceWindow() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (payload: MaintenanceWindowCreatePayload) => {
      return api.post<{ success: boolean; window: MaintenanceWindow }>('/system/maintenance-windows', payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['maintenance-windows'] });
    },
  });
}

export function useUpdateMaintenanceWindow() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ id, payload }: { id: string; payload: MaintenanceWindowUpdatePayload }) => {
      return api.put<{ success: boolean; window: MaintenanceWindow }>(`/system/maintenance-windows/${id}`, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['maintenance-windows'] });
    },
  });
}

export function useDeleteMaintenanceWindow() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (id: string) => {
      return api.delete<{ success: boolean; message: string }>(`/system/maintenance-windows/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['maintenance-windows'] });
    },
  });
}
