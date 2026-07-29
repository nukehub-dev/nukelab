// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

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

export function useSystemMaxBalance() {
  return useQuery({
    queryKey: ['system-max-balance'],
    queryFn: async () => {
      return api.get<{ max_balance: number }>('/admin/credits/max-balance')
    },
  })
}

export function useUpdateSystemMaxBalance() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  return useMutation({
    mutationFn: async (amount: number) => {
      return api.put<{ message: string }>('/admin/credits/max-balance', { amount })
    },
    onSuccess: (_data, amount) => {
      queryClient.invalidateQueries({ queryKey: ['system-max-balance'] })
      queryClient.invalidateQueries({ queryKey: ['system-config'] })
      const label = amount === 0 ? 'unlimited' : `${amount.toLocaleString()} NUKE`
      success('Max balance updated', `Credit cap set to ${label}`)
    },
    onError: (err) => {
      showError(
        'Failed to update max balance',
        err instanceof Error ? err.message : 'Unknown error'
      )
    },
  })
}

export function useSystemInitialBalance() {
  return useQuery({
    queryKey: ['system-initial-balance'],
    queryFn: async () => {
      return api.get<{ initial_balance: number }>('/admin/credits/initial-balance')
    },
  })
}

export function useUpdateSystemInitialBalance() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  return useMutation({
    mutationFn: async (amount: number) => {
      return api.put<{ message: string }>('/admin/credits/initial-balance', { amount })
    },
    onSuccess: (_data, amount) => {
      queryClient.invalidateQueries({ queryKey: ['system-initial-balance'] })
      queryClient.invalidateQueries({ queryKey: ['system-config'] })
      success('Signup balance updated', `New users start with ${amount.toLocaleString()} NUKE`)
    },
    onError: (err) => {
      showError(
        'Failed to update signup balance',
        err instanceof Error ? err.message : 'Unknown error'
      )
    },
  })
}

export function useSystemAllowanceLoginWindow() {
  return useQuery({
    queryKey: ['system-allowance-login-window'],
    queryFn: async () => {
      return api.get<{ login_window_hours: number }>('/admin/credits/allowance-login-window')
    },
  })
}

export function useUpdateSystemAllowanceLoginWindow() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  return useMutation({
    mutationFn: async (hours: number) => {
      return api.put<{ message: string }>('/admin/credits/allowance-login-window', { hours })
    },
    onSuccess: (_data, hours) => {
      queryClient.invalidateQueries({ queryKey: ['system-allowance-login-window'] })
      queryClient.invalidateQueries({ queryKey: ['system-config'] })
      success(
        'Login window updated',
        `Daily allowance requires a login within ${hours.toLocaleString()} hours`
      )
    },
    onError: (err) => {
      showError(
        'Failed to update login window',
        err instanceof Error ? err.message : 'Unknown error'
      )
    },
  })
}
