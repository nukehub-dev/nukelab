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

export interface AdminVolume {
  id: string
  name: string
  display_name: string
  owner_id: string
  owner?: {
    id: string
    username: string
    display_name: string
  }
  visibility: string
  size_bytes: number
  max_size_bytes: number | null
  status: string
  server_count: number
  description?: string | null
  created_at?: string
  updated_at?: string
  is_home_volume?: boolean
}

export interface AdminVolumeListResponse {
  volumes: AdminVolume[]
  pagination: {
    page: number
    limit: number
    total: number
    total_pages: number
  }
}

export interface AdminVolumeDetailResponse {
  volume: AdminVolume
}

interface AdminVolumesQueryParams {
  search?: string
  status?: string
  visibility?: string
  owner_id?: string
  page?: number
  limit?: number
  sort_by?: string
  sort_order?: string
}

export function useAdminVolumes(params: AdminVolumesQueryParams = {}) {
  return useQuery({
    queryKey: ['admin-volumes', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams()
      if (params.search) searchParams.set('search', params.search)
      if (params.status) searchParams.set('status', params.status)
      if (params.visibility) searchParams.set('visibility', params.visibility)
      if (params.owner_id) searchParams.set('owner_id', params.owner_id)
      if (params.page) searchParams.set('page', String(params.page))
      if (params.limit) searchParams.set('limit', String(params.limit))
      if (params.sort_by) searchParams.set('sort_by', params.sort_by)
      if (params.sort_order) searchParams.set('sort_order', params.sort_order)

      const queryString = searchParams.toString()
      return api.get<AdminVolumeListResponse>(
        `/admin/volumes${queryString ? `?${queryString}` : ''}`
      )
    },
  })
}

export function useAdminVolume(volumeId: string | null) {
  return useQuery({
    queryKey: ['admin-volume', volumeId],
    queryFn: async () => {
      if (!volumeId) throw new Error('Volume ID required')
      return api.get<AdminVolumeDetailResponse>(`/admin/volumes/${volumeId}`)
    },
    enabled: !!volumeId,
  })
}

interface UpdateVolumeData {
  volumeId: string
  display_name?: string
  description?: string
  visibility?: string
  status?: string
  max_size_bytes?: number
}

export interface BulkVolumeActionRequest {
  action: 'delete' | 'archive' | 'activate'
  volume_ids: string[]
}

export interface BulkVolumeActionResponse {
  message: string
  action: string
  results: {
    success: string[]
    failed: Array<{ volume_id: string; error: string }>
  }
}

export interface RefreshSizesResponse {
  message: string
  refreshed: number
  failed: Array<{ volume_id: string; error: string }>
}

export function useAdminVolumeActions() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  const updateVolume = useMutation({
    mutationFn: ({ volumeId, ...data }: UpdateVolumeData) =>
      api.put<{ success: boolean; volume: AdminVolume; message: string }>(
        `/admin/volumes/${volumeId}`,
        data
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['admin-volumes'] })
      queryClient.invalidateQueries({ queryKey: ['admin-volume', variables.volumeId] })
      success('Volume updated', 'Volume has been updated successfully')
    },
    onError: (err) => {
      showError('Failed to update volume', getErrorMessage(err))
    },
  })

  const deleteVolume = useMutation({
    mutationFn: (volumeId: string) =>
      api.delete<{ success: boolean; message: string }>(`/admin/volumes/${volumeId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-volumes'] })
      success('Volume deleted', 'Volume has been deleted successfully')
    },
    onError: (err) => {
      showError('Failed to delete volume', getErrorMessage(err))
    },
  })

  const bulkAction = useMutation({
    mutationFn: (data: BulkVolumeActionRequest) =>
      api.post<BulkVolumeActionResponse>('/admin/volumes/bulk-action', data),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['admin-volumes'] })
      if (data.results.failed.length > 0) {
        showError(
          `${data.results.failed.length} volume(s) failed`,
          data.results.failed
            .slice(0, 3)
            .map((f) => f.error)
            .join('; ')
        )
      }
      if (data.results.success.length > 0) {
        success('Bulk action completed', `${data.results.success.length} volume(s) processed`)
      }
    },
    onError: (err) => {
      showError('Bulk action failed', getErrorMessage(err))
    },
  })

  const refreshVolumeSize = useMutation({
    mutationFn: (volumeId: string) =>
      api.post<{ volume_id: string; size_bytes: number | null }>(
        `/volumes/${volumeId}/refresh-size`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-volumes'] })
      success('Size refreshed', 'Volume size has been recalculated')
    },
    onError: (err) => {
      showError('Failed to refresh size', getErrorMessage(err))
    },
  })

  const refreshAllSizes = useMutation({
    mutationFn: () => api.post<RefreshSizesResponse>('/admin/volumes/refresh-sizes', {}),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['admin-volumes'] })
      if (data.failed.length > 0) {
        showError(
          `${data.failed.length} volume(s) failed`,
          data.failed
            .slice(0, 3)
            .map((f) => f.error)
            .join('; ')
        )
      }
      if (data.refreshed > 0) {
        success('Sizes refreshed', `${data.refreshed} volume(s) recalculated`)
      }
    },
    onError: (err) => {
      showError('Failed to refresh sizes', getErrorMessage(err))
    },
  })

  return { updateVolume, deleteVolume, bulkAction, refreshVolumeSize, refreshAllSizes }
}
