import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface Volume {
  name: string;
  driver: string;
  mountpoint: string;
  created_at?: string;
  labels: Record<string, string>;
  size?: number | null;
}

export function useVolumes() {
  return useQuery({
    queryKey: ['volumes'],
    queryFn: async () => {
      const response = await api.get<{ volumes: Volume[] }>('/volumes/');
      return response.volumes;
    },
  });
}
