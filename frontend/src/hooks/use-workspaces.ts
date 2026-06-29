// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useToast } from '../stores/toast-store'
import type { WorkspaceActivity } from '../types/api'

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message
  }
  if (typeof error === 'string') {
    return error
  }
  return 'An unexpected error occurred'
}

export interface Workspace {
  id: string
  name: string
  description?: string
  owner_id: string
  owner_name?: string
  owner_username?: string
  is_active: boolean
  created_at?: string
  updated_at?: string
  member_count: number
  volume_count: number
  has_pending_invitation?: boolean
}

export interface WorkspaceMember {
  workspace_id: string
  user_id: string
  role: 'read_only' | 'read_write' | 'admin'
  joined_at?: string
  username?: string
  email?: string
}

export interface WorkspaceVolume {
  workspace_id: string
  volume_id: string
  role: 'read_only' | 'read_write'
  added_at?: string
  added_by?: string
  volume?: {
    id: string
    name: string
    display_name: string
    size_bytes: number
    max_size_bytes?: number | null
    status: string
    visibility?: string
    server_count?: number
    description?: string | null
    labels?: Record<string, string>
    created_at?: string
    updated_at?: string
    expires_at?: string
    last_mounted_at?: string | null
    owner?: {
      id: string
      username: string
      display_name: string
    }
  }
}

export interface WorkspaceInvitation {
  id: string
  workspace_id: string
  user_id: string
  invited_by?: string
  role: 'read_only' | 'read_write' | 'admin'
  status: 'pending' | 'accepted' | 'rejected'
  created_at?: string
  updated_at?: string
  expires_at?: string
  username?: string
  display_name?: string
  avatar_url?: string
  inviter_username?: string
  inviter_display_name?: string
  inviter_avatar_url?: string
}

export interface WorkspaceWithMembers extends Workspace {
  my_membership: WorkspaceMember | null
  invitation_count: number
  my_invitation: WorkspaceInvitation | null
}

export interface PaginatedWorkspaceMembers {
  members: WorkspaceMember[]
  pagination: {
    page: number
    limit: number
    total: number
    total_pages: number
  }
}

export interface PaginatedWorkspaceVolumes {
  volumes: WorkspaceVolume[]
  pagination: {
    page: number
    limit: number
    total: number
    total_pages: number
  }
}

export function useWorkspaces() {
  return useQuery({
    queryKey: ['workspaces'],
    queryFn: async () => {
      const response = await api.get<{ workspaces: Workspace[] }>('/workspaces/')
      return response.workspaces
    },
  })
}

export function useWorkspace(workspaceId: string) {
  return useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: async () => {
      const response = await api.get<WorkspaceWithMembers>(`/workspaces/${workspaceId}`)
      return response
    },
    enabled: !!workspaceId,
  })
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async (data: { name: string; description?: string }) => {
      const response = await api.post<Workspace>('/workspaces/', data)
      return response
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err) => {
      showError('Failed to create workspace', getErrorMessage(err))
    },
  })
}

export function useUpdateWorkspace() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({
      workspaceId,
      data,
    }: {
      workspaceId: string
      data: Partial<Workspace>
    }) => {
      const response = await api.put<Workspace>(`/workspaces/${workspaceId}`, data)
      return response
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
    },
    onError: (err) => {
      showError('Failed to update workspace', getErrorMessage(err))
    },
  })
}

export function useDeleteWorkspace() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async (workspaceId: string) => {
      await api.delete(`/workspaces/${workspaceId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err) => {
      showError('Failed to delete workspace', getErrorMessage(err))
    },
  })
}

export function useAddWorkspaceMember() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({
      workspaceId,
      userId,
      role,
    }: {
      workspaceId: string
      userId: string
      role: string
    }) => {
      const response = await api.post<WorkspaceMember>(`/workspaces/${workspaceId}/members`, {
        user_id: userId,
        role,
      })
      return response
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
    },
    onError: (err) => {
      showError('Failed to add member', getErrorMessage(err))
    },
  })
}

export function useRemoveWorkspaceMember() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({ workspaceId, userId }: { workspaceId: string; userId: string }) => {
      await api.delete(`/workspaces/${workspaceId}/members/${userId}`)
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
    },
    onError: (err) => {
      showError('Failed to remove member', getErrorMessage(err))
    },
  })
}

export function useUpdateMemberRole() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({
      workspaceId,
      userId,
      role,
    }: {
      workspaceId: string
      userId: string
      role: string
    }) => {
      const response = await api.put<WorkspaceMember>(
        `/workspaces/${workspaceId}/members/${userId}`,
        { role }
      )
      return response
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
    },
    onError: (err) => {
      showError('Failed to update member role', getErrorMessage(err))
    },
  })
}

export function useAddWorkspaceVolume() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({
      workspaceId,
      volumeId,
      role,
    }: {
      workspaceId: string
      volumeId: string
      role: string
    }) => {
      const response = await api.post<WorkspaceVolume>(`/workspaces/${workspaceId}/volumes`, {
        volume_id: volumeId,
        role,
      })
      return response
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err) => {
      showError('Failed to add volume', getErrorMessage(err))
    },
  })
}

export function useRemoveWorkspaceVolume() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({ workspaceId, volumeId }: { workspaceId: string; volumeId: string }) => {
      await api.delete(`/workspaces/${workspaceId}/volumes/${volumeId}`)
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err) => {
      showError('Failed to remove volume', getErrorMessage(err))
    },
  })
}

export function useUpdateVolumeRole() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({
      workspaceId,
      volumeId,
      role,
    }: {
      workspaceId: string
      volumeId: string
      role: string
    }) => {
      const response = await api.put<WorkspaceVolume>(
        `/workspaces/${workspaceId}/volumes/${volumeId}`,
        { role }
      )
      return response
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
    },
    onError: (err) => {
      showError('Failed to update volume access', getErrorMessage(err))
    },
  })
}

export function useInviteWorkspaceMember() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({
      workspaceId,
      userId,
      role,
    }: {
      workspaceId: string
      userId: string
      role: string
    }) => {
      const response = await api.post<WorkspaceInvitation>(
        `/workspaces/${workspaceId}/invitations`,
        {
          user_id: userId,
          role,
        }
      )
      return response
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
    },
    onError: (err) => {
      showError('Failed to send invitation', getErrorMessage(err))
    },
  })
}

export function useAcceptInvitation() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({
      workspaceId,
      invitationId,
    }: {
      workspaceId: string
      invitationId: string
    }) => {
      const response = await api.post<WorkspaceMember>(
        `/workspaces/${workspaceId}/invitations/${invitationId}/accept`,
        {}
      )
      return response
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err) => {
      showError('Failed to accept invitation', getErrorMessage(err))
    },
  })
}

export function useRejectInvitation() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({
      workspaceId,
      invitationId,
    }: {
      workspaceId: string
      invitationId: string
    }) => {
      await api.post(`/workspaces/${workspaceId}/invitations/${invitationId}/reject`, {})
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err) => {
      showError('Failed to decline invitation', getErrorMessage(err))
    },
  })
}

export function useCancelInvitation() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({
      workspaceId,
      invitationId,
    }: {
      workspaceId: string
      invitationId: string
    }) => {
      await api.delete(`/workspaces/${workspaceId}/invitations/${invitationId}`)
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
    },
    onError: (err) => {
      showError('Failed to cancel invitation', getErrorMessage(err))
    },
  })
}

export function useLeaveWorkspace() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async (workspaceId: string) => {
      await api.post(`/workspaces/${workspaceId}/leave`, {})
    },
    onSuccess: (_, workspaceId) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', workspaceId] })
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err) => {
      showError('Failed to leave workspace', getErrorMessage(err))
    },
  })
}

export function useTransferOwnership() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()
  return useMutation({
    mutationFn: async ({ workspaceId, userId }: { workspaceId: string; userId: string }) => {
      await api.post(`/workspaces/${workspaceId}/transfer`, { user_id: userId })
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', variables.workspaceId] })
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
    onError: (err) => {
      showError('Failed to transfer ownership', getErrorMessage(err))
    },
  })
}

export function useWorkspaceActivity(
  workspaceId: string,
  params: { page?: number; limit?: number } = {}
) {
  return useQuery({
    queryKey: ['workspace', workspaceId, 'activity', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams()
      if (params.page) searchParams.set('page', String(params.page))
      if (params.limit) searchParams.set('limit', String(params.limit))
      const queryString = searchParams.toString()
      const response = await api.get<{
        activity: WorkspaceActivity[]
        pagination: { page: number; limit: number; total: number; total_pages: number }
      }>(`/workspaces/${workspaceId}/activity?${queryString}`)
      return response
    },
    enabled: !!workspaceId,
  })
}

interface WorkspaceMembersQueryParams {
  page?: number
  limit?: number
  sort_by?: string
  sort_order?: string
  search?: string
  role?: string
}

export function useWorkspaceMembers(workspaceId: string, params: WorkspaceMembersQueryParams = {}) {
  return useQuery({
    queryKey: ['workspace', workspaceId, 'members', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams()
      if (params.page) searchParams.set('page', String(params.page))
      if (params.limit) searchParams.set('limit', String(params.limit))
      if (params.sort_by) searchParams.set('sort_by', params.sort_by)
      if (params.sort_order) searchParams.set('sort_order', params.sort_order)
      if (params.search) searchParams.set('search', params.search)
      if (params.role) searchParams.set('role', params.role)

      const queryString = searchParams.toString()
      const response = await api.get<PaginatedWorkspaceMembers>(
        `/workspaces/${workspaceId}/members?${queryString}`
      )
      return response
    },
    enabled: !!workspaceId,
  })
}

interface WorkspaceVolumesQueryParams {
  page?: number
  limit?: number
  sort_by?: string
  sort_order?: string
  search?: string
}

export function useWorkspaceVolumes(workspaceId: string, params: WorkspaceVolumesQueryParams = {}) {
  return useQuery({
    queryKey: ['workspace', workspaceId, 'volumes', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams()
      if (params.page) searchParams.set('page', String(params.page))
      if (params.limit) searchParams.set('limit', String(params.limit))
      if (params.sort_by) searchParams.set('sort_by', params.sort_by)
      if (params.sort_order) searchParams.set('sort_order', params.sort_order)
      if (params.search) searchParams.set('search', params.search)

      const queryString = searchParams.toString()
      const response = await api.get<PaginatedWorkspaceVolumes>(
        `/workspaces/${workspaceId}/volumes?${queryString}`
      )
      return response
    },
    enabled: !!workspaceId,
  })
}

export function useWorkspaceInvitations(workspaceId: string) {
  return useQuery({
    queryKey: ['workspace', workspaceId, 'invitations'],
    queryFn: async () => {
      const response = await api.get<{ invitations: WorkspaceInvitation[] }>(
        `/workspaces/${workspaceId}/invitations`
      )
      return response.invitations
    },
    enabled: !!workspaceId,
  })
}
