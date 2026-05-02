import { useQuery } from '@tanstack/react-query';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/health`);
      if (!response.ok) throw new Error('Backend unavailable');
      return response.json();
    },
    retry: 3,
    refetchInterval: 30000,
  });
}
