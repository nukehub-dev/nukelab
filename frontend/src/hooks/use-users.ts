import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { User } from '../types/api';

interface UsersQueryParams {
  role?: string;
  status?: string;
  search?: string;
  sort_by?: string;
  sort_order?: string;
  page?: number;
  limit?: number;
}

export function useUsers(params: UsersQueryParams = {}) {
  return useQuery({
    queryKey: ['users', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params.role) searchParams.set('role', params.role);
      if (params.status) searchParams.set('status', params.status);
      if (params.search) searchParams.set('search', params.search);
      if (params.sort_by) searchParams.set('sort_by', params.sort_by);
      if (params.sort_order) searchParams.set('sort_order', params.sort_order);
      if (params.page) searchParams.set('page', String(params.page));
      if (params.limit) searchParams.set('limit', String(params.limit));

      const queryString = searchParams.toString();
      const response = await api.get<{ users: User[]; pagination: { page: number; limit: number; total: number; total_pages: number } }>(`/users/?${queryString}`);
      
      return {
        data: response.users,
        pagination: {
          page: response.pagination.page,
          limit: response.pagination.limit,
          total: response.pagination.total,
          totalPages: response.pagination.total_pages,
        },
      };
    },
  });
}

interface CreateUserData {
  username: string;
  email: string;
  password: string;
  role?: string;
  first_name?: string;
  last_name?: string;
  credits?: number;
}

interface UpdateUserData {
  first_name?: string;
  last_name?: string;
  email?: string;
  role?: string;
  nuke_balance?: number;
}

export function useUserActions() {
  const queryClient = useQueryClient();

  const createUser = useMutation({
    mutationFn: (data: CreateUserData) =>
      api.post<User>('/users/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });

  const updateUser = useMutation({
    mutationFn: ({ userId, data }: { userId: string; data: UpdateUserData }) =>
      api.put<User>(`/users/${userId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });

  const disableUser = useMutation({
    mutationFn: ({ userId, disabled }: { userId: string; disabled: boolean }) =>
      api.post<User>(`/users/${userId}/disable`, { disabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });

  const deleteUser = useMutation({
    mutationFn: (userId: string) => api.delete(`/users/${userId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
    },
  });

  return {
    createUser,
    updateUser,
    disableUser,
    deleteUser,
  };
}
