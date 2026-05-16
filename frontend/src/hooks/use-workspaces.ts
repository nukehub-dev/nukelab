import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface Workspace {
  id: string;
  name: string;
  description?: string;
  owner_id: string;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
  member_count: number;
  volume_count: number;
  has_pending_invitation?: boolean;
}

export interface WorkspaceMember {
  workspace_id: string;
  user_id: string;
  role: 'read_only' | 'read_write' | 'admin';
  joined_at?: string;
  username?: string;
  email?: string;
}

export interface WorkspaceVolume {
  workspace_id: string;
  volume_id: string;
  role: 'read_only' | 'read_write';
  added_at?: string;
  added_by?: string;
  volume?: {
    id: string;
    name: string;
    display_name: string;
    size_bytes: number;
    status: string;
  };
}

export interface WorkspaceInvitation {
  id: string;
  workspace_id: string;
  user_id: string;
  invited_by?: string;
  role: 'read_only' | 'read_write' | 'admin';
  status: 'pending' | 'accepted' | 'rejected';
  created_at?: string;
  updated_at?: string;
  username?: string;
  display_name?: string;
  avatar_url?: string;
  inviter_username?: string;
  inviter_display_name?: string;
  inviter_avatar_url?: string;
}

export interface WorkspaceWithMembers extends Workspace {
  members: WorkspaceMember[];
  volumes: WorkspaceVolume[];
  invitations: WorkspaceInvitation[];
  my_invitation: WorkspaceInvitation | null;
}

export function useWorkspaces() {
  return useQuery({
    queryKey: ['workspaces'],
    queryFn: async () => {
      const response = await api.get<{ workspaces: Workspace[] }>('/workspaces/');
      return response.workspaces;
    },
  });
}

export function useWorkspace(workspaceId: string) {
  return useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: async () => {
      const response = await api.get<WorkspaceWithMembers>(`/workspaces/${workspaceId}`);
      return response;
    },
    enabled: !!workspaceId,
  });
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: { name: string; description?: string }) => {
      const response = await api.post<Workspace>('/workspaces/', data);
      return response;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
}

export function useUpdateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ workspaceId, data }: { workspaceId: string; data: Partial<Workspace> }) => {
      const response = await api.put<Workspace>(`/workspaces/${workspaceId}`, data);
      return response;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] });
    },
  });
}

export function useDeleteWorkspace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (workspaceId: string) => {
      await api.delete(`/workspaces/${workspaceId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
}

export function useAddWorkspaceMember() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ workspaceId, userId, role }: { workspaceId: string; userId: string; role: string }) => {
      const response = await api.post<WorkspaceMember>(`/workspaces/${workspaceId}/members`, {
        user_id: userId,
        role,
      });
      return response;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] });
    },
  });
}

export function useRemoveWorkspaceMember() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ workspaceId, userId }: { workspaceId: string; userId: string }) => {
      await api.delete(`/workspaces/${workspaceId}/members/${userId}`);
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] });
    },
  });
}

export function useUpdateMemberRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ workspaceId, userId, role }: { workspaceId: string; userId: string; role: string }) => {
      const response = await api.put<WorkspaceMember>(`/workspaces/${workspaceId}/members/${userId}`, { role });
      return response;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] });
    },
  });
}

export function useAddWorkspaceVolume() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ workspaceId, volumeId, role }: { workspaceId: string; volumeId: string; role: string }) => {
      const response = await api.post<WorkspaceVolume>(`/workspaces/${workspaceId}/volumes`, {
        volume_id: volumeId,
        role,
      });
      return response;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] });
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
}

export function useRemoveWorkspaceVolume() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ workspaceId, volumeId }: { workspaceId: string; volumeId: string }) => {
      await api.delete(`/workspaces/${workspaceId}/volumes/${volumeId}`);
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] });
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
}

export function useInviteWorkspaceMember() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ workspaceId, userId, role }: { workspaceId: string; userId: string; role: string }) => {
      const response = await api.post<WorkspaceInvitation>(`/workspaces/${workspaceId}/invitations`, {
        user_id: userId,
        role,
      });
      return response;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] });
    },
  });
}

export function useAcceptInvitation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ workspaceId, invitationId }: { workspaceId: string; invitationId: string }) => {
      const response = await api.post<WorkspaceMember>(`/workspaces/${workspaceId}/invitations/${invitationId}/accept`, {});
      return response;
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] });
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
}

export function useRejectInvitation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ workspaceId, invitationId }: { workspaceId: string; invitationId: string }) => {
      await api.post(`/workspaces/${workspaceId}/invitations/${invitationId}/reject`, {});
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] });
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
}

export function useCancelInvitation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ workspaceId, invitationId }: { workspaceId: string; invitationId: string }) => {
      await api.delete(`/workspaces/${workspaceId}/invitations/${invitationId}`);
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] });
    },
  });
}
