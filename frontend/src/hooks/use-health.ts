import { useQuery } from '@tanstack/react-query';

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const response = await fetch('/api/health');
      if (!response.ok) throw new Error('Backend unavailable');
      return response.json();
    },
    retry: 3,
    refetchInterval: 30000,
  });
}
