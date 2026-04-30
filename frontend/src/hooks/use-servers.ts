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

export function useServerActions() {
  const queryClient = useQueryClient();

  const startServer = useMutation({
    mutationFn: (serverId: string) =>
      api.post<{ message: string }>(`/servers/${serverId}/start`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
    },
  });

  const stopServer = useMutation({
    mutationFn: (serverId: string) =>
      api.post<{ message: string }>(`/servers/${serverId}/stop`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
    },
  });

  const restartServer = useMutation({
    mutationFn: (serverId: string) =>
      api.post<{ message: string }>(`/servers/${serverId}/restart`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
    },
  });

  const deleteServer = useMutation({
    mutationFn: (serverId: string) =>
      api.delete<{ message: string }>(`/servers/${serverId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] });
    },
  });

  return {
    startServer,
    stopServer,
    restartServer,
    deleteServer,
  };
}
