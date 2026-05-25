import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, useCallback, useEffect } from 'react';
import { api } from '../lib/api';
import { useToastStore } from '../stores/toast-store';
import type { Server } from '../types/api';

export function useServers() {
  return useQuery({
    queryKey: ['servers'],
    queryFn: async () => {
      const response = await api.get<{ servers: Server[] }>('/servers/');
      return response.servers;
    },
  });
}

export function useServerByPath(username: string, serverName: string) {
  return useQuery({
    queryKey: ['server-by-path', username, serverName],
    queryFn: async () => {
      const response = await api.get<Server>(`/servers/by-path/${username}/${serverName}`);
      return response;
    },
    enabled: !!username && !!serverName,
    retry: (failureCount, error) => {
      if (error instanceof Error && error.message.includes('404')) {
        return false;
      }
      return failureCount < 2;
    },
  });
}

interface VolumeMountData {
  volume_id: string;
  mount_path: string;
  mode: string;
  max_size_bytes?: number;
}

interface CreateServerData {
  name: string;
  plan_id: string;
  environment_id: string;
  volume_id?: string;
  volume_mode?: string;
  volume_mounts?: VolumeMountData[];
}

interface UpdateServerData {
  name?: string;
  plan_id?: string;
  environment_id?: string;
  volume_mounts?: VolumeMountData[];
}

type PendingOperation = {
  serverId: string;
  type: 'start' | 'stop' | 'restart' | 'delete';
  targetStatus: 'running' | 'stopped' | 'deleted';
};

export function useServerActions() {
  const queryClient = useQueryClient();

  const [pendingOps, setPendingOps] = useState<PendingOperation[]>([]);

  const addPendingOp = useCallback((serverId: string, type: PendingOperation['type'], targetStatus: PendingOperation['targetStatus']) => {
    setPendingOps((prev) => [...prev.filter((op) => op.serverId !== serverId), { serverId, type, targetStatus }]);
  }, []);

  const removePendingOp = useCallback((serverId: string) => {
    setPendingOps((prev) => prev.filter((op) => op.serverId !== serverId));
  }, []);

  // Watch servers data and clear pending ops when status matches target.
  // Subscribe to query cache changes so we react instantly when the cache
  // is updated (via WebSocket, mutation response, or refetch) instead of polling.
  useEffect(() => {
    const checkPendingOps = () => {
      const servers = queryClient.getQueryData<Server[]>(['servers']);
      if (!servers) return;

      setPendingOps((prev) => {
        if (prev.length === 0) return prev;
        const next = prev.filter((op) => {
          if (op.targetStatus === 'deleted') {
            // Remove if server no longer exists
            return servers.some((s) => s.id === op.serverId);
          }
          const server = servers.find((s) => s.id === op.serverId);
          if (!server) return false;
          // For restart, also clear if status is running (restart completed)
          if (op.type === 'restart' && server.status === 'running') {
            return false;
          }
          // Keep pending if status doesn't match target yet
          return server.status !== op.targetStatus;
        });
        return next.length === prev.length ? prev : next;
      });
    };

    // Check immediately on mount
    checkPendingOps();

    // Subscribe to query cache changes for instant reaction when ['servers'] updates
    const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
      if (event.type === 'updated' && event.query.queryKey[0] === 'servers') {
        checkPendingOps();
      }
    });

    return () => unsubscribe();
  }, [queryClient]);

  // Auto-clear operations after timeout to prevent buttons stuck loading forever
  // if the cache update or refetch somehow fails
  useEffect(() => {
    const opsWithTimeout = pendingOps.filter((op) => op.type !== 'delete');
    if (opsWithTimeout.length === 0) return;

    const timers = opsWithTimeout.map((op) =>
      setTimeout(() => {
        removePendingOp(op.serverId);
      }, op.type === 'restart' ? 15000 : 30000) // 15s for restart, 30s for start/stop
    );

    return () => timers.forEach(clearTimeout);
  }, [pendingOps]);

  const isOperationPending = useCallback(
    (serverId: string, type?: PendingOperation['type']) => {
      return pendingOps.some((op) => {
        if (op.serverId !== serverId) return false;
        return type ? op.type === type : true;
      });
    },
    [pendingOps]
  );

  const createServer = useMutation({
    mutationFn: (data: CreateServerData) =>
      api.post<Server>('/servers/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });

  const updateServer = useMutation({
    mutationFn: ({ serverId, data }: { serverId: string; data: UpdateServerData & { reason?: string } }) =>
      api.patch<Server>(`/servers/${serverId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });

  const startServer = useMutation({
    mutationFn: ({ serverId, reason }: { serverId: string; reason?: string }) =>
      api.post<{ message: string; server_id: string; status: Server['status'] }>(`/servers/${serverId}/start`, { reason }),
    onMutate: (variables) => {
      addPendingOp(variables.serverId, 'start', 'running');
    },
    onSuccess: (data, variables) => {
      const serverId = variables.serverId;
      // Immediately update cache so UI reflects the new status without waiting
      // for the slow list_servers refetch (which checks Docker status for all servers)
      queryClient.setQueryData(['servers'], (old: Server[] | undefined) => {
        if (!old) return old;
        return old.map((s) => (s.id === serverId ? { ...s, status: data.status } : s));
      });
      removePendingOp(serverId);
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (error: Error, variables) => {
      removePendingOp(variables.serverId);
      console.error('Failed to start server:', error.message);
      useToastStore.getState().addToast({ type: 'error', title: 'Failed to start server', message: error.message, duration: 8000 });
    },
  });

  const stopServer = useMutation({
    mutationFn: ({ serverId, reason }: { serverId: string; reason?: string }) =>
      api.post<{ message: string; server_id: string; status: Server['status'] }>(`/servers/${serverId}/stop`, { reason }),
    onMutate: (variables) => {
      addPendingOp(variables.serverId, 'stop', 'stopped');
    },
    onSuccess: (data, variables) => {
      const serverId = variables.serverId;
      // Immediately update cache so UI reflects the new status without waiting
      // for the slow list_servers refetch (which checks Docker status for all servers)
      queryClient.setQueryData(['servers'], (old: Server[] | undefined) => {
        if (!old) return old;
        return old.map((s) => (s.id === serverId ? { ...s, status: data.status } : s));
      });
      removePendingOp(serverId);
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (error: Error, variables) => {
      removePendingOp(variables.serverId);
      console.error('Failed to stop server:', error.message);
      useToastStore.getState().addToast({ type: 'error', title: 'Failed to stop server', message: error.message, duration: 8000 });
    },
  });

  const restartServer = useMutation({
    mutationFn: ({ serverId, reason }: { serverId: string; reason?: string }) =>
      api.post<{ message: string; server_id: string; status: Server['status'] }>(`/servers/${serverId}/restart`, { reason }),
    onMutate: (variables) => {
      addPendingOp(variables.serverId, 'restart', 'running');
    },
    onSuccess: (data, variables) => {
      const serverId = variables.serverId;
      // Immediately update cache so UI reflects the new status without waiting
      // for the slow list_servers refetch (which checks Docker status for all servers)
      queryClient.setQueryData(['servers'], (old: Server[] | undefined) => {
        if (!old) return old;
        return old.map((s) => (s.id === serverId ? { ...s, status: data.status } : s));
      });
      removePendingOp(serverId);
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (error: Error, variables) => {
      removePendingOp(variables.serverId);
      console.error('Failed to restart server:', error.message);
      useToastStore.getState().addToast({ type: 'error', title: 'Failed to restart server', message: error.message, duration: 8000 });
    },
  });

  const deleteServer = useMutation({
    mutationFn: ({ serverId, reason }: { serverId: string; reason?: string }) =>
      api.delete<{ message: string }>(`/servers/${serverId}`, reason ? { reason } : undefined),
    onMutate: (variables) => {
      addPendingOp(variables.serverId, 'delete', 'deleted');
    },
    onSuccess: (_, variables) => {
      const serverId = variables.serverId;
      // Immediately remove the server from cache so the row disappears
      // without waiting for the slow list_servers refetch
      queryClient.setQueryData(['servers'], (old: Server[] | undefined) => {
        if (!old) return old;
        return old.filter((s) => s.id !== serverId);
      });
      removePendingOp(serverId);
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (error: Error, variables) => {
      removePendingOp(variables.serverId);
      console.error('Failed to delete server:', error.message);
      useToastStore.getState().addToast({ type: 'error', title: 'Failed to delete server', message: error.message, duration: 8000 });
    },
  });

  return {
    createServer,
    updateServer,
    startServer,
    stopServer,
    restartServer,
    deleteServer,
    isOperationPending,
  };
}

export interface ServerSchedule {
  id: string;
  server_id: string;
  user_id: string;
  action: 'start' | 'stop' | 'restart';
  cron_expression: string;
  timezone: string;
  is_active: boolean;
  last_run_at?: string;
  next_run_at?: string;
  run_count: number;
  created_at?: string;
}

export function useServerSchedules(serverId: string) {
  return useQuery({
    queryKey: ['server-schedules', serverId],
    queryFn: async () => {
      const response = await api.get<{ schedules: ServerSchedule[] }>(`/schedules/servers/${serverId}/schedules`);
      return response.schedules;
    },
    enabled: !!serverId,
  });
}

export function useCreateSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ serverId, data }: { serverId: string; data: Omit<ServerSchedule, 'id' | 'server_id' | 'user_id' | 'run_count' | 'created_at'> }) =>
      api.post<ServerSchedule>(`/schedules/servers/${serverId}/schedules`, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['server-schedules', variables.serverId] });
    },
  });
}

export function useDeleteSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ serverId, scheduleId }: { serverId: string; scheduleId: string }) =>
      api.delete(`/schedules/servers/${serverId}/schedules/${scheduleId}`),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['server-schedules', variables.serverId] });
    },
  });
}

export function useServerLogs(serverId: string, tail: number = 100, paused: boolean = false, active: boolean = true) {
  return useQuery({
    queryKey: ['server-logs', serverId, tail],
    queryFn: async () => {
      const response = await api.get<{ logs: string; tail: number; status?: string }>(`/servers/${serverId}/logs?tail=${tail}`);
      return response;
    },
    enabled: !!serverId && !paused && active,
    refetchInterval: (paused || !active) ? false : 5000,
  });
}

export interface BulkActionRequest {
  action: 'start' | 'stop' | 'restart' | 'delete';
  server_ids: string[];
  reason?: string;
}

export interface BulkActionResponse {
  succeeded: string[];
  failed: Array<{ server_id: string; error: string }>;
  total: number;
  success_count: number;
  failure_count: number;
}

export function useBulkServerActions() {
  const queryClient = useQueryClient();

  const bulkAction = useMutation({
    mutationFn: (data: BulkActionRequest) =>
      api.post<BulkActionResponse>('/bulk/servers/bulk-action', data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      if (data.failure_count > 0) {
        const errors = data.failed.slice(0, 3).map((f) => f.error).join('; ');
        const more = data.failed.length > 3 ? ` and ${data.failed.length - 3} more` : '';
        useToastStore.getState().addToast({
          type: 'error',
          title: `${data.failure_count} server(s) failed`,
          message: errors + more,
          duration: 8000,
        });
      }
      if (data.success_count > 0) {
        useToastStore.getState().addToast({
          type: 'success',
          title: 'Bulk action completed',
          message: `${data.success_count} server(s) processed successfully`,
          duration: 4000,
        });
      }
    },
    onError: (error: Error) => {
      console.error('Bulk action failed:', error.message);
      useToastStore.getState().addToast({
        type: 'error',
        title: 'Bulk action failed',
        message: error.message,
        duration: 8000,
      });
    },
  });

  return { bulkAction };
}
