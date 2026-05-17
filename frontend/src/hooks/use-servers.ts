import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, useCallback, useEffect } from 'react';
import { api } from '../lib/api';
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

  // Watch servers data and clear pending ops when status matches target
  // Use interval to check since queryClient reference is stable
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

    // Check immediately
    checkPendingOps();
    
    // Then check every second until all pending ops are cleared
    const interval = setInterval(checkPendingOps, 1000);
    return () => clearInterval(interval);
  }, [queryClient]);

  // Auto-clear restart operations after timeout (docker restart is fast)
  useEffect(() => {
    const restartOps = pendingOps.filter((op) => op.type === 'restart');
    if (restartOps.length === 0) return;

    const timers = restartOps.map((op) =>
      setTimeout(() => {
        removePendingOp(op.serverId);
      }, 10000) // 10 second max for restart
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
    mutationFn: ({ serverId, data }: { serverId: string; data: UpdateServerData }) =>
      api.patch<Server>(`/servers/${serverId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });

  const startServer = useMutation({
    mutationFn: (serverId: string) =>
      api.post<{ message: string }>(`/servers/${serverId}/start`, {}),
    onMutate: (serverId) => {
      addPendingOp(serverId, 'start', 'running');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (error: Error, serverId) => {
      removePendingOp(serverId);
      console.error('Failed to start server:', error.message);
      alert(`Failed to start server: ${error.message}`);
    },
  });

  const stopServer = useMutation({
    mutationFn: (serverId: string) =>
      api.post<{ message: string }>(`/servers/${serverId}/stop`, {}),
    onMutate: (serverId) => {
      addPendingOp(serverId, 'stop', 'stopped');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (error: Error, serverId) => {
      removePendingOp(serverId);
      console.error('Failed to stop server:', error.message);
      alert(`Failed to stop server: ${error.message}`);
    },
  });

  const restartServer = useMutation({
    mutationFn: (serverId: string) =>
      api.post<{ message: string }>(`/servers/${serverId}/restart`, {}),
    onMutate: (serverId) => {
      addPendingOp(serverId, 'restart', 'running');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (error: Error, serverId) => {
      removePendingOp(serverId);
      console.error('Failed to restart server:', error.message);
      alert(`Failed to restart server: ${error.message}`);
    },
  });

  const deleteServer = useMutation({
    mutationFn: (serverId: string) =>
      api.delete<{ message: string }>(`/servers/${serverId}`),
    onMutate: (serverId) => {
      addPendingOp(serverId, 'delete', 'deleted');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
    onError: (error: Error, serverId) => {
      removePendingOp(serverId);
      console.error('Failed to delete server:', error.message);
      alert(`Failed to delete server: ${error.message}`);
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
