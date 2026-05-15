import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import { isAuthenticated } from './use-auth';

export interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  severity: 'info' | 'success' | 'warning' | 'error';
  read: boolean;
  read_at?: string;
  action_url?: string;
  extra_data: Record<string, any>;
  created_at: string;
}

export interface NotificationListResponse {
  notifications: Notification[];
  unread_count: number;
  total: number;
  page: number;
  page_size: number;
}

export function useNotifications(unreadOnly = false, page = 1, pageSize = 20, enabled = true) {
  return useQuery({
    queryKey: ['notifications', unreadOnly, page, pageSize],
    queryFn: async () => {
      const response = await api.get<NotificationListResponse>(
        `/notifications/?unread_only=${unreadOnly}&page=${page}&page_size=${pageSize}`
      );
      return response;
    },
    enabled: enabled && isAuthenticated(),
    refetchOnWindowFocus: true,
    refetchOnMount: true,
  });
}

export function useUnreadCount(enabled = true) {
  return useQuery({
    queryKey: ['notifications', 'unread-count'],
    queryFn: async () => {
      const response = await api.get<{ unread_count: number }>('/notifications/unread-count');
      return response.unread_count;
    },
    enabled: enabled && isAuthenticated(),
    refetchInterval: 5 * 60 * 1000, // Fallback poll every 5 min if WebSocket is down
    refetchOnWindowFocus: true,
    refetchOnMount: true,
  });
}

export function useMarkAsRead() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (notificationId: string) => {
      const response = await api.put<Notification>(`/notifications/${notificationId}/read`, {});
      return response;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
}

export function useMarkAllAsRead() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async () => {
      const response = await api.put<{ message: string }>('/notifications/read-all', {});
      return response;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
}

export function useDeleteNotification() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (notificationId: string) => {
      await api.delete(`/notifications/${notificationId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    },
  });
}
