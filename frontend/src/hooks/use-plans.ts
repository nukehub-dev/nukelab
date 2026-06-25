import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useToast } from '../stores/toast-store'
import type { Plan } from '../types/api'

interface PlansQueryParams {
  category?: string
  is_active?: boolean
  page?: number
  limit?: number
}

export function usePlans(params: PlansQueryParams = {}) {
  return useQuery({
    queryKey: ['plans', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams()
      if (params.category) searchParams.set('category', params.category)
      if (params.is_active !== undefined) searchParams.set('is_active', String(params.is_active))
      if (params.page) searchParams.set('page', String(params.page))
      if (params.limit) searchParams.set('limit', String(params.limit))

      const queryString = searchParams.toString()
      const response = await api.get<{
        success: boolean
        data: { items: Plan[]; total: number; page: number; limit: number; pages: number }
      }>(`/plans/?${queryString}`)

      return {
        data: response.data.items,
        pagination: {
          page: response.data.page,
          limit: response.data.limit,
          total: response.data.total,
          totalPages: response.data.pages,
        },
      }
    },
  })
}

interface CreatePlanData {
  name: string
  slug: string
  description?: string
  category?: string
  cpu_limit?: number
  memory_limit?: string
  disk_limit?: string
  gpu_limit?: number
  max_servers_per_user?: number
  cost_per_hour?: number
  cooldown_seconds?: number
  is_public?: boolean
  visible_to_roles?: string[]
  priority?: number
}

interface UpdatePlanData {
  name?: string
  description?: string
  category?: string
  cpu_limit?: number
  memory_limit?: string
  disk_limit?: string
  gpu_limit?: number
  max_servers_per_user?: number
  cost_per_hour?: number
  cooldown_seconds?: number
  is_public?: boolean
  visible_to_roles?: string[]
  priority?: number
  is_active?: boolean
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message
  }
  if (typeof error === 'string') {
    return error
  }
  return 'An unexpected error occurred'
}

export function usePlanActions() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  const createPlan = useMutation({
    mutationFn: (data: CreatePlanData) =>
      api.post<{ success: boolean; data: Plan }>('/plans/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] })
      success('Plan created', 'New plan has been created successfully')
    },
    onError: (err) => {
      showError('Failed to create plan', getErrorMessage(err))
    },
  })

  const updatePlan = useMutation({
    mutationFn: ({ planId, data }: { planId: string; data: UpdatePlanData }) =>
      api.put<{ success: boolean; data: Plan }>(`/plans/${planId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] })
      success('Plan updated', 'Plan has been updated successfully')
    },
    onError: (err) => {
      showError('Failed to update plan', getErrorMessage(err))
    },
  })

  const deletePlan = useMutation({
    mutationFn: (planId: string) => api.delete<{ success: boolean }>(`/plans/${planId}/permanent`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] })
      success('Plan deleted', 'Plan has been permanently deleted')
    },
    onError: (err) => {
      showError('Failed to delete plan', getErrorMessage(err))
    },
  })

  const activatePlan = useMutation({
    mutationFn: (planId: string) => api.post<{ success: boolean }>(`/plans/${planId}/activate`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] })
      success('Plan activated', 'Plan has been activated')
    },
    onError: (err) => {
      showError('Failed to activate plan', getErrorMessage(err))
    },
  })

  const deactivatePlan = useMutation({
    mutationFn: (planId: string) => api.delete<{ success: boolean }>(`/plans/${planId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plans'] })
      success('Plan deactivated', 'Plan has been deactivated')
    },
    onError: (err) => {
      showError('Failed to deactivate plan', getErrorMessage(err))
    },
  })

  return {
    createPlan,
    updatePlan,
    deletePlan,
    activatePlan,
    deactivatePlan,
  }
}

// ─── Plan Access Management ───

export interface PlanUserAccess {
  user_id: string
  plan_id: string
  granted_by?: string
  granted_at?: string
  expires_at?: string
  username?: string
  display_name?: string
  granted_by_username?: string
}

export interface PlanWorkspaceAccess {
  workspace_id: string
  plan_id: string
  granted_by?: string
  granted_at?: string
  expires_at?: string
  workspace_name?: string
  granted_by_username?: string
  owner_name?: string
  owner_username?: string
}

export function usePlanUsers(planId: string | undefined) {
  return useQuery({
    queryKey: ['plans', planId, 'users'],
    queryFn: async () => {
      const response = await api.get<{ success: boolean; data: PlanUserAccess[] }>(
        `/plans/${planId}/users`
      )
      return response.data
    },
    enabled: !!planId,
    staleTime: 0,
  })
}

export function usePlanWorkspaces(planId: string | undefined) {
  return useQuery({
    queryKey: ['plans', planId, 'workspaces'],
    queryFn: async () => {
      const response = await api.get<{ success: boolean; data: PlanWorkspaceAccess[] }>(
        `/plans/${planId}/workspaces`
      )
      return response.data
    },
    enabled: !!planId,
    staleTime: 0,
  })
}

export function usePlanAccessActions() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  const grantUserAccess = useMutation({
    mutationFn: ({ planId, userId }: { planId: string; userId: string }) =>
      api.post<{ success: boolean; data: PlanUserAccess }>(`/plans/${planId}/users/${userId}`, {}),
    onSuccess: async (result, { planId }) => {
      // Immediately update cache with returned data for instant UI feedback
      queryClient.setQueryData(['plans', planId, 'users'], (old: PlanUserAccess[] | undefined) => {
        if (!old) return [result.data]
        // Avoid duplicates
        if (old.some((u) => u.user_id === result.data.user_id)) return old
        return [...old, result.data]
      })
      // Then refetch to ensure consistency
      await queryClient.refetchQueries({ queryKey: ['plans', planId, 'users'], type: 'active' })
      success('Access granted', 'User has been granted access to this plan')
    },
    onError: (err) => {
      showError('Failed to grant access', getErrorMessage(err))
    },
  })

  const revokeUserAccess = useMutation({
    mutationFn: ({ planId, userId }: { planId: string; userId: string }) =>
      api.delete<{ success: boolean }>(`/plans/${planId}/users/${userId}`),
    onSuccess: async (_, { planId, userId }) => {
      // Immediately remove from cache
      queryClient.setQueryData(['plans', planId, 'users'], (old: PlanUserAccess[] | undefined) => {
        if (!old) return []
        return old.filter((u) => u.user_id !== userId)
      })
      await queryClient.refetchQueries({ queryKey: ['plans', planId, 'users'], type: 'active' })
      success('Access revoked', 'User access has been revoked')
    },
    onError: (err) => {
      showError('Failed to revoke access', getErrorMessage(err))
    },
  })

  const grantWorkspaceAccess = useMutation({
    mutationFn: ({ planId, workspaceId }: { planId: string; workspaceId: string }) =>
      api.post<{ success: boolean; data: PlanWorkspaceAccess }>(
        `/plans/${planId}/workspaces/${workspaceId}`,
        {}
      ),
    onSuccess: async (result, { planId }) => {
      queryClient.setQueryData(
        ['plans', planId, 'workspaces'],
        (old: PlanWorkspaceAccess[] | undefined) => {
          if (!old) return [result.data]
          if (old.some((w) => w.workspace_id === result.data.workspace_id)) return old
          return [...old, result.data]
        }
      )
      await queryClient.refetchQueries({
        queryKey: ['plans', planId, 'workspaces'],
        type: 'active',
      })
      success('Access granted', 'Workspace has been granted access to this plan')
    },
    onError: (err) => {
      showError('Failed to grant access', getErrorMessage(err))
    },
  })

  const revokeWorkspaceAccess = useMutation({
    mutationFn: ({ planId, workspaceId }: { planId: string; workspaceId: string }) =>
      api.delete<{ success: boolean }>(`/plans/${planId}/workspaces/${workspaceId}`),
    onSuccess: async (_, { planId, workspaceId }) => {
      queryClient.setQueryData(
        ['plans', planId, 'workspaces'],
        (old: PlanWorkspaceAccess[] | undefined) => {
          if (!old) return []
          return old.filter((w) => w.workspace_id !== workspaceId)
        }
      )
      await queryClient.refetchQueries({
        queryKey: ['plans', planId, 'workspaces'],
        type: 'active',
      })
      success('Access revoked', 'Workspace access has been revoked')
    },
    onError: (err) => {
      showError('Failed to revoke access', getErrorMessage(err))
    },
  })

  return {
    grantUserAccess,
    revokeUserAccess,
    grantWorkspaceAccess,
    revokeWorkspaceAccess,
  }
}
