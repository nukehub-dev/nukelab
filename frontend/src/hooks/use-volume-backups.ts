// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, queryClient } from '../lib/api'
import { recoveryIsActive, recoveryPollInterval } from '../lib/volume-backup'
import { PERMISSIONS, useAuthStore } from '../stores/auth-store'
import type {
  BackupEligibility,
  CreateBackupRequest,
  RecoveryCapability,
  RestoreBackupRequest,
  VolumeBackup,
  VolumeBackupPage,
  VolumeRestore,
  VolumeRestorePage,
} from '../types/volume-backup'

export const backupKeys = {
  owner: (owner: string | undefined) => ['volume-backups', owner] as const,
  capabilities: (owner: string | undefined) => ['volume-backups', owner, 'capabilities'] as const,
  eligibility: (owner: string | undefined, volume: string | undefined) =>
    ['volume-backups', owner, 'eligibility', volume] as const,
  list: (owner: string | undefined, page: number, volume?: string) =>
    ['volume-backups', owner, 'list', page, volume] as const,
  restores: (owner: string | undefined, page: number, backup?: string) =>
    ['volume-backups', owner, 'restores', page, backup] as const,
}

useAuthStore.subscribe((state, previous) => {
  if (state.user?.id !== previous.user?.id) {
    const filters = { queryKey: backupKeys.owner(previous.user?.id) }
    void queryClient.cancelQueries(filters)
    queryClient.removeQueries(filters)
  }
})

function hidden() {
  return typeof document !== 'undefined' && document.hidden
}
function unavailable(error: unknown) {
  return error instanceof ApiError && [403, 404].includes(error.status)
}
function current(owner: string | undefined) {
  if (!owner || useAuthStore.getState().user?.id !== owner)
    throw new Error('Account changed. Reopen backup history.')
}

export function useRecoveryCapabilities() {
  const owner = useAuthStore((state) => state.user?.id)
  const canRead = useAuthStore((state) => state.hasPermission(PERMISSIONS.VOLUMES_READ_OWN))
  return useQuery({
    queryKey: backupKeys.capabilities(owner),
    queryFn: async () => {
      try {
        return await api.get<RecoveryCapability>('/volume-backups/capabilities')
      } catch (error) {
        if (error instanceof ApiError && [403, 404].includes(error.status))
          return {
            enabled: false,
            reason_code: 'unsupported',
            message: 'Volume recovery is unavailable on this deployment.',
          }
        throw error
      }
    },
    enabled: !!owner && canRead,
    retry: false,
    staleTime: 30_000,
  })
}

export function useBackupEligibility(volume: string | undefined, enabled: boolean) {
  const owner = useAuthStore((state) => state.user?.id)
  return useQuery({
    queryKey: backupKeys.eligibility(owner, volume),
    queryFn: () => api.get<BackupEligibility>(`/volumes/${volume}/backup-eligibility`),
    enabled: !!owner && !!volume && enabled,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: (query) => (unavailable(query.state.error) || hidden() ? false : 10_000),
  })
}

export function useVolumeBackups(page: number, volume: string | undefined, enabled: boolean) {
  const owner = useAuthStore((state) => state.user?.id)
  return useQuery({
    queryKey: backupKeys.list(owner, page, volume),
    queryFn: () =>
      api.get<VolumeBackupPage>(
        `/volume-backups?page=${page}&page_size=10${volume ? `&volume_id=${encodeURIComponent(volume)}` : ''}`
      ),
    enabled: !!owner && enabled,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: (query) =>
      unavailable(query.state.error)
        ? false
        : recoveryPollInterval(
            !query.state.data ||
              query.state.data.items.some((item) => recoveryIsActive(item.status)),
            query.state.fetchFailureCount,
            hidden()
          ),
  })
}

export function useVolumeRestores(page: number, enabled: boolean, backup?: string) {
  const owner = useAuthStore((state) => state.user?.id)
  const client = useQueryClient()
  return useQuery({
    queryKey: backupKeys.restores(owner, page, backup),
    queryFn: async () => {
      const result = await api.get<VolumeRestorePage>(
        `/volume-restores?page=${page}&page_size=10${backup ? `&backup_id=${encodeURIComponent(backup)}` : ''}`
      )
      if (
        useAuthStore.getState().user?.id === owner &&
        result.items.some((item) => item.status === 'completed')
      )
        void client.invalidateQueries({ queryKey: ['volumes'] })
      return result
    },
    enabled: !!owner && enabled,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: (query) =>
      unavailable(query.state.error)
        ? false
        : recoveryPollInterval(
            !query.state.data ||
              query.state.data.items.some((item) => recoveryIsActive(item.status)),
            query.state.fetchFailureCount,
            hidden()
          ),
  })
}

export function useRecoveryActions() {
  const owner = useAuthStore((state) => state.user?.id)
  const client = useQueryClient()
  const refresh = () => {
    if (useAuthStore.getState().user?.id === owner) {
      void client.invalidateQueries({ queryKey: backupKeys.owner(owner) })
      void client.invalidateQueries({ queryKey: ['volumes'] })
    }
  }
  const create = useMutation({
    mutationFn: ({ volume, body }: { volume: string; body: CreateBackupRequest }) => {
      current(owner)
      return api.post<VolumeBackup>(`/volumes/${volume}/backups`, body)
    },
    onSettled: refresh,
  })
  const restore = useMutation({
    mutationFn: ({ backup, body }: { backup: string; body: RestoreBackupRequest }) => {
      current(owner)
      return api.post<VolumeRestore>(`/volume-backups/${backup}/restore`, body)
    },
    onSettled: refresh,
  })
  const remove = useMutation({
    mutationFn: (backup: string) => {
      current(owner)
      return api.delete<VolumeBackup>(`/volume-backups/${backup}`)
    },
    onSettled: refresh,
  })
  return { create, restore, remove }
}
