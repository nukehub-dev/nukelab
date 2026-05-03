import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
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

interface CreateServerData {
  name: string;
  plan_id: string;
  environment_id: string;
}

export function useServerActions() {
  const queryClient = useQueryClient();

  const createServer = useMutation({
    mutationFn: (data: CreateServerData) =>
      api.post<Server>('/servers/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
    },
  });

  const startServer = useMutation({
    mutationFn: (serverId: string) =>
      api.post<{ message: string }>(`/servers/${serverId}/start`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
    },
    onError: (error: Error) => {
      console.error('Failed to start server:', error.message);
      alert(`Failed to start server: ${error.message}`);
    },
  });

  const stopServer = useMutation({
    mutationFn: (serverId: string) =>
      api.post<{ message: string }>(`/servers/${serverId}/stop`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
    },
    onError: (error: Error) => {
      console.error('Failed to stop server:', error.message);
      alert(`Failed to stop server: ${error.message}`);
    },
  });

  const restartServer = useMutation({
    mutationFn: (serverId: string) =>
      api.post<{ message: string }>(`/servers/${serverId}/restart`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
    },
    onError: (error: Error) => {
      console.error('Failed to restart server:', error.message);
      alert(`Failed to restart server: ${error.message}`);
    },
  });

  const deleteServer = useMutation({
    mutationFn: (serverId: string) =>
      api.delete<{ message: string }>(`/servers/${serverId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
    },
    onError: (error: Error) => {
      console.error('Failed to delete server:', error.message);
      alert(`Failed to delete server: ${error.message}`);
    },
  });

  return {
    createServer,
    startServer,
    stopServer,
    restartServer,
    deleteServer,
  };
}
