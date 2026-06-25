import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'

export interface Volume {
  id: string
  name: string
  display_name: string
  owner_id: string
  visibility: string
  size_bytes: number
  max_size_bytes?: number | null
  status: string
  server_count: number
  description?: string | null
  is_home_volume?: boolean
  created_at: string
  updated_at: string
  workspace_count?: number
}

export interface VolumeFileItem {
  name: string
  type: 'file' | 'directory'
  size: number | null
  modified: number
}

export interface VolumeFilesResponse {
  type: 'directory' | 'file'
  path: string
  items: VolumeFileItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface VolumeFilesParams {
  path?: string
  search?: string
  sort_by?: 'name' | 'size' | 'modified'
  sort_order?: 'asc' | 'desc'
  page?: number
  page_size?: number
}

export function useVolumes() {
  return useQuery({
    queryKey: ['volumes'],
    queryFn: async () => {
      const response = await api.get<{ volumes: Volume[] }>('/volumes/')
      return response.volumes
    },
  })
}

export function useCreateVolume() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (data: {
      display_name: string
      description?: string
      max_size_bytes?: number
    }) => {
      const response = await api.post<Volume>('/volumes/', data)
      return response
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['volumes'] })
    },
  })
}

export function useDeleteVolume() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (volumeId: string) => {
      await api.delete(`/volumes/${volumeId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['volumes'] })
    },
  })
}

export function useVolumeFiles(volumeId: string | null, params: VolumeFilesParams = {}) {
  return useQuery({
    queryKey: ['volume-files', volumeId, params],
    queryFn: async () => {
      if (!volumeId) return null
      const queryParams = new URLSearchParams()
      if (params.path) queryParams.append('path', params.path)
      if (params.search) queryParams.append('search', params.search)
      if (params.sort_by) queryParams.append('sort_by', params.sort_by)
      if (params.sort_order) queryParams.append('sort_order', params.sort_order)
      if (params.page) queryParams.append('page', params.page.toString())
      if (params.page_size) queryParams.append('page_size', params.page_size.toString())

      const response = await api.get<VolumeFilesResponse>(
        `/volumes/${volumeId}/files?${queryParams.toString()}`
      )
      return response
    },
    enabled: !!volumeId,
  })
}

export function useUpdateVolume() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ volumeId, data }: { volumeId: string; data: Partial<Volume> }) => {
      const response = await api.put<Volume>(`/volumes/${volumeId}`, data)
      return response
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['volumes'] })
    },
  })
}

export function useDeleteVolumeFile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ volumeId, path }: { volumeId: string; path: string }) => {
      await api.delete(`/volumes/${volumeId}/files?path=${encodeURIComponent(path)}`)
    },
    onSuccess: (_, variables) => {
      // Invalidate all file listings for this volume
      queryClient.invalidateQueries({ queryKey: ['volume-files', variables.volumeId] })
    },
  })
}
