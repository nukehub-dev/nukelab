import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Environment } from '../types/api';

interface EnvironmentsQueryParams {
  category?: string;
  is_active?: boolean;
  search?: string;
  page?: number;
  limit?: number;
}

export function useEnvironments(params: EnvironmentsQueryParams = {}) {
  return useQuery({
    queryKey: ['environments', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params.category) searchParams.set('category', params.category);
      if (params.is_active !== undefined) searchParams.set('is_active', String(params.is_active));
      if (params.search) searchParams.set('search', params.search);
      if (params.page) searchParams.set('page', String(params.page));
      if (params.limit) searchParams.set('limit', String(params.limit));

      const queryString = searchParams.toString();
      const response = await api.get<{ success: boolean; data: { items: Environment[]; total: number; page: number; limit: number; pages: number } }>(`/environments/?${queryString}`);
      
      return {
        data: response.data.items,
        pagination: {
          page: response.data.page,
          limit: response.data.limit,
          total: response.data.total,
          totalPages: response.data.pages,
        },
      };
    },
  });
}

export function useEnvironmentActions() {
  const queryClient = useQueryClient();

  const activateEnvironment = useMutation({
    mutationFn: (envId: string) =>
      api.post<{ success: boolean }>(`/environments/${envId}/activate`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['environments'] });
    },
  });

  const deactivateEnvironment = useMutation({
    mutationFn: (envId: string) =>
      api.delete<{ success: boolean }>(`/environments/${envId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['environments'] });
    },
  });

  return {
    activateEnvironment,
    deactivateEnvironment,
  };
}
