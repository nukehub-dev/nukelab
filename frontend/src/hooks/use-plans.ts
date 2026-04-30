import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Plan } from '../types/api';

interface PlansQueryParams {
  category?: string;
  is_active?: boolean;
  page?: number;
  limit?: number;
}

export function usePlans(params: PlansQueryParams = {}) {
  return useQuery({
    queryKey: ['plans', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params.category) searchParams.set('category', params.category);
      if (params.is_active !== undefined) searchParams.set('is_active', String(params.is_active));
      if (params.page) searchParams.set('page', String(params.page));
      if (params.limit) searchParams.set('limit', String(params.limit));

      const queryString = searchParams.toString();
      const response = await api.get<{ success: boolean; data: { items: Plan[]; total: number; page: number; limit: number; pages: number } }>(`/plans/?${queryString}`);
      
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

interface CreatePlanData {
  name: string;
  slug: string;
  description?: string;
  category?: string;
  cpu_limit?: number;
  memory_limit?: string;
  disk_limit?: string;
  gpu_limit?: number;
  max_servers_per_user?: number;
  cost_per_hour?: number;
  cooldown_seconds?: number;
  requires_approval?: boolean;
  allowed_roles?: string[];
  priority?: number;
}

interface UpdatePlanData {
  name?: string;
  description?: string;
  category?: string;
  cpu_limit?: number;
  memory_limit?: string;
  disk_limit?: string;
  gpu_limit?: number;
  max_servers_per_user?: number;
  cost_per_hour?: number;
  cooldown_seconds?: number;
  requires_approval?: boolean;
  allowed_roles?: string[];
  priority?: number;
  is_active?: boolean;
}

export function usePlanActions() {
  const queryClient = useQueryClient();

  const createPlan = useMutation({
    mutationFn: (data: CreatePlanData) =>
      api.post<{ success: boolean; data: Plan }>('/plans/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] });
    },
  });

  const updatePlan = useMutation({
    mutationFn: ({ planId, data }: { planId: string; data: UpdatePlanData }) =>
      api.put<{ success: boolean; data: Plan }>(`/plans/${planId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] });
    },
  });

  const deletePlan = useMutation({
    mutationFn: (planId: string) =>
      api.delete<{ success: boolean }>(`/plans/${planId}/permanent`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] });
    },
  });

  const activatePlan = useMutation({
    mutationFn: (planId: string) =>
      api.post<{ success: boolean }>(`/plans/${planId}/activate`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] });
    },
  });

  const deactivatePlan = useMutation({
    mutationFn: (planId: string) =>
      api.delete<{ success: boolean }>(`/plans/${planId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] });
    },
  });

  return {
    createPlan,
    updatePlan,
    deletePlan,
    activatePlan,
    deactivatePlan,
  };
}
