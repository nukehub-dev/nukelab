import { useQuery } from '@tanstack/react-query';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

export interface HealthStatus {
  status: 'healthy' | 'maintenance';
  message?: string;
  timestamp?: string;
}

export function useHealth() {
  return useQuery<HealthStatus>({
    queryKey: ['health'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/health`);
      const data = await response.json();
      
      if (data.status === 'maintenance') {
        return {
          status: 'maintenance',
          message: data.message,
        };
      }
      
      if (!response.ok) throw new Error('Backend unavailable');
      return data;
    },
    retry: 3,
    refetchInterval: 30000,
  });
}
