// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useToast } from '../stores/toast-store'

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return 'An unexpected error occurred'
}

export interface QuotaLimits {
  max_cpu_total: number
  max_memory_total: string
  max_disk_total: string
  max_gpu_total: number
  max_servers_total: number
}

export interface QuotaUsage {
  cpu: number
  memory_mb: number
  disk_mb: number
  gpu: number
  servers: number
}

export interface UserQuota {
  user_id: string
  username: string
  display_name?: string
  email: string
  role: string
  limits: QuotaLimits
  usage: QuotaUsage
  quota_id: string | null
}

export interface MyQuota {
  id: string
  user_id: string
  role: string | null
  plan_id: string | null
  limits: QuotaLimits
  usage: QuotaUsage
}

export function useMyQuota() {
  return useQuery({
    queryKey: ['quota', 'me'],
    queryFn: async () => {
      const response = await api.get<{ success: boolean; data: MyQuota }>('/quotas/')
      return response.data
    },
  })
}

interface QuotasResponse {
  items: UserQuota[]
  total: number
  page: number
  limit: number
  pages: number
}

interface QuotasQueryParams {
  search?: string
  page?: number
  limit?: number
}

export function useQuotas(params: QuotasQueryParams = {}) {
  return useQuery({
    queryKey: ['quotas', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams()
      if (params.search) searchParams.set('search', params.search)
      if (params.page) searchParams.set('page', String(params.page))
      if (params.limit) searchParams.set('limit', String(params.limit))

      const queryString = searchParams.toString()
      const response = await api.get<{ success: boolean; data: QuotasResponse }>(
        `/quotas/all${queryString ? `?${queryString}` : ''}`
      )
      return response.data
    },
  })
}

interface UpdateQuotaData {
  userId: string
  limits: Partial<QuotaLimits>
}

export function useQuotaActions() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  const updateQuota = useMutation({
    mutationFn: ({ userId, limits }: UpdateQuotaData) =>
      api.put<{ success: boolean; data: { limits: QuotaLimits }; message: string }>(
        `/quotas/${userId}`,
        limits
      ),
    onSuccess: (_data, _variables) => {
      queryClient.invalidateQueries({ queryKey: ['quotas'] })
      success('Quota updated', `Resource limits updated for user`)
    },
    onError: (err) => {
      showError('Failed to update quota', getErrorMessage(err))
    },
  })

  return { updateQuota }
}

export function useSystemQuotaDefaults() {
  return useQuery({
    queryKey: ['system-quota-defaults'],
    queryFn: async () => {
      const response = await api.get<{ default_limits: QuotaLimits }>(
        '/admin/quotas/default-limits'
      )
      return response.default_limits
    },
  })
}

type UpdateSystemQuotaDefaultsData = QuotaLimits

export function useUpdateSystemQuotaDefaults() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  return useMutation({
    mutationFn: (limits: UpdateSystemQuotaDefaultsData) =>
      api.put<{ message: string; default_limits: QuotaLimits }>(
        '/admin/quotas/default-limits',
        limits
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['system-quota-defaults'] })
      queryClient.invalidateQueries({ queryKey: ['quotas'] })
      success('Default quotas updated', 'New users will receive these limits')
    },
    onError: (err) => {
      showError('Failed to update default quotas', getErrorMessage(err))
    },
  })
}
