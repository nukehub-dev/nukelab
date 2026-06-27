import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useToast } from '../stores/toast-store'

export interface SystemConfig {
  app_name: string
  app_env: string
  app_debug: boolean
  maintenance_mode: boolean
  maintenance_message: string
}

export function useSystemConfig() {
  return useQuery({
    queryKey: ['system-config'],
    queryFn: async () => {
      return api.get<SystemConfig>('/system/config')
    },
    enabled: true,
  })
}

export function useUpdateSystemConfig() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (payload: { maintenance_mode?: boolean; maintenance_message?: string }) => {
      return api.put<{ success: boolean; updates: Record<string, unknown> }>(
        '/system/config',
        payload
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['system-config'] })
      queryClient.invalidateQueries({ queryKey: ['health'] })
    },
  })
}

export function useToggleMaintenance() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ enabled, message }: { enabled: boolean; message?: string }) => {
      return api.post<{ success: boolean; maintenance_mode: boolean; message: string }>(
        `/system/maintenance?enabled=${enabled}${message ? `&message=${encodeURIComponent(message)}` : ''}`,
        {}
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['system-config'] })
      queryClient.invalidateQueries({ queryKey: ['health'] })
    },
  })
}

export function useSystemDailyAllowance() {
  return useQuery({
    queryKey: ['system-daily-allowance'],
    queryFn: async () => {
      return api.get<{ default_daily_allowance: number }>('/admin/credits/default-allowance')
    },
  })
}

export function useUpdateSystemDailyAllowance() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  return useMutation({
    mutationFn: async (amount: number) => {
      return api.put<{ message: string }>('/admin/credits/default-allowance', { amount })
    },
    onSuccess: (_data, amount) => {
      queryClient.invalidateQueries({ queryKey: ['system-daily-allowance'] })
      queryClient.invalidateQueries({ queryKey: ['system-config'] })
      success('System default updated', `Daily allowance set to ${amount.toLocaleString()} NUKE`)
    },
    onError: (err) => {
      showError(
        'Failed to update system default',
        err instanceof Error ? err.message : 'Unknown error'
      )
    },
  })
}
