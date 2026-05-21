import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import { useToast } from '../stores/toast-store';
import type { Workspace } from './use-workspaces';

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return 'An unexpected error occurred';
}

export interface AdminWorkspace extends Workspace {}

export interface AdminWorkspaceListResponse {
  workspaces: AdminWorkspace[];
  pagination: {
    page: number;
    limit: number;
    total: number;
    total_pages: number;
  };
}

export interface AdminWorkspaceDetailResponse {
  workspace: AdminWorkspace;
  members: Array<{
    workspace_id: string;
    user_id: string;
    role: string;
    joined_at?: string;
    username?: string;
    email?: string;
  }>;
  volumes: Array<{
    workspace_id: string;
    volume_id: string;
    role: string;
    added_at?: string;
    volume?: Record<string, unknown>;
  }>;
  invitations: Array<Record<string, unknown>>;
}

interface AdminWorkspacesQueryParams {
  search?: string;
  status?: string;
  owner_id?: string;
  page?: number;
  limit?: number;
  sort_by?: string;
  sort_order?: string;
}

export function useAdminWorkspaces(params: AdminWorkspacesQueryParams = {}) {
  return useQuery({
    queryKey: ['admin-workspaces', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams();
      if (params.search) searchParams.set('search', params.search);
      if (params.status) searchParams.set('status', params.status);
      if (params.owner_id) searchParams.set('owner_id', params.owner_id);
      if (params.page) searchParams.set('page', String(params.page));
      if (params.limit) searchParams.set('limit', String(params.limit));
      if (params.sort_by) searchParams.set('sort_by', params.sort_by);
      if (params.sort_order) searchParams.set('sort_order', params.sort_order);

      const queryString = searchParams.toString();
      return api.get<AdminWorkspaceListResponse>(
        `/admin/workspaces${queryString ? `?${queryString}` : ''}`
      );
    },
  });
}

export function useAdminWorkspace(workspaceId: string | null) {
  return useQuery({
    queryKey: ['admin-workspace', workspaceId],
    queryFn: async () => {
      if (!workspaceId) throw new Error('Workspace ID required');
      return api.get<AdminWorkspaceDetailResponse>(`/admin/workspaces/${workspaceId}`);
    },
    enabled: !!workspaceId,
  });
}

interface UpdateWorkspaceData {
  workspaceId: string;
  name?: string;
  description?: string;
  is_active?: boolean;
}

export function useAdminWorkspaceActions() {
  const queryClient = useQueryClient();
  const { success, error: showError } = useToast();

  const updateWorkspace = useMutation({
    mutationFn: ({ workspaceId, ...data }: UpdateWorkspaceData) =>
      api.put<{ success: boolean; workspace: AdminWorkspace; message: string }>(
        `/admin/workspaces/${workspaceId}`,
        data
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['admin-workspaces'] });
      queryClient.invalidateQueries({ queryKey: ['admin-workspace', variables.workspaceId] });
      success('Workspace updated', 'Workspace has been updated successfully');
    },
    onError: (err) => {
      showError('Failed to update workspace', getErrorMessage(err));
    },
  });

  const deleteWorkspace = useMutation({
    mutationFn: (workspaceId: string) =>
      api.delete<{ success: boolean; message: string }>(`/admin/workspaces/${workspaceId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-workspaces'] });
      success('Workspace deleted', 'Workspace has been deleted successfully');
    },
    onError: (err) => {
      showError('Failed to delete workspace', getErrorMessage(err));
    },
  });

  return { updateWorkspace, deleteWorkspace };
}
