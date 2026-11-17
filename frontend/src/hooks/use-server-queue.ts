// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, queryClient } from '../lib/api'
import { canCancelQueuedRequest, isQueueActive, queuePollInterval } from '../lib/server-queue'
import { useAuthStore, PERMISSIONS } from '../stores/auth-store'
import type { ServerQueueEntry, ServerQueuePage } from '../types/server-queue'

export const queueKeys = {
  owner: (ownerId: string | undefined) => ['server-queue', ownerId] as const,
  capabilities: (ownerId: string | undefined) => ['server-queue', ownerId, 'capabilities'] as const,
  list: (ownerId: string | undefined, page: number) =>
    ['server-queue', ownerId, 'list', page] as const,
  detail: (ownerId: string | undefined, id: string | undefined) =>
    ['server-queue', ownerId, 'detail', id] as const,
}

// The subscription outlives route mounts, including logout while another page is open.
useAuthStore.subscribe((state, previous) => {
  if (state.user?.id !== previous.user?.id) {
    const filters = { queryKey: queueKeys.owner(previous.user?.id) }
    void queryClient.cancelQueries(filters)
    queryClient.removeQueries(filters)
  }
})

function hidden() {
  return typeof document !== 'undefined' && document.hidden
}

function unavailable(error: unknown) {
  return error instanceof ApiError && [403, 404, 503].includes(error.status)
}

export function useQueueCapabilities() {
  const ownerId = useAuthStore((state) => state.user?.id)
  const canRead = useAuthStore((state) => state.hasPermission(PERMISSIONS.SERVERS_READ_OWN))
  return useQuery({
    queryKey: queueKeys.capabilities(ownerId),
    queryFn: async () => {
      try {
        return await api.get<{ enabled: boolean }>('/server-queue/capabilities')
      } catch (error) {
        if (unavailable(error)) return { enabled: false }
        throw error
      }
    },
    enabled: !!ownerId && canRead,
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  })
}

function useRefreshLaunchedServers(
  entries: ServerQueueEntry[] | undefined,
  selected?: ServerQueueEntry
) {
  const client = useQueryClient()
  useEffect(() => {
    if (
      entries?.some((entry) => entry.status === 'started' && entry.server_id) ||
      (selected?.status === 'started' && selected.server_id)
    ) {
      for (const queryKey of [['servers'], ['dashboard'], ['quota'], ['usage'], ['volumes']]) {
        void client.invalidateQueries({ queryKey })
      }
    }
  }, [entries, selected, client])
}

export function useServerQueue(page: number, enabled: boolean) {
  const ownerId = useAuthStore((state) => state.user?.id)
  const query = useQuery({
    queryKey: queueKeys.list(ownerId, page),
    queryFn: () => api.get<ServerQueuePage>(`/server-queue?page=${page}&page_size=25`),
    enabled: !!ownerId && enabled,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: (query) =>
      unavailable(query.state.error)
        ? false
        : queuePollInterval(
            !query.state.data || query.state.data.items.some(isQueueActive),
            query.state.fetchFailureCount,
            hidden()
          ),
  })
  useRefreshLaunchedServers(query.data?.items)
  return query
}

export function useServerQueueEntry(id: string | undefined, enabled: boolean) {
  const ownerId = useAuthStore((state) => state.user?.id)
  const query = useQuery({
    queryKey: queueKeys.detail(ownerId, id),
    queryFn: () => api.get<ServerQueueEntry>(`/server-queue/${id}`),
    enabled: !!ownerId && !!id && enabled,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: (query) =>
      unavailable(query.state.error)
        ? false
        : queuePollInterval(
            !query.state.data || isQueueActive(query.state.data),
            query.state.fetchFailureCount,
            hidden()
          ),
  })
  useRefreshLaunchedServers(undefined, query.data)
  return query
}

export function useCancelServerQueue() {
  const ownerId = useAuthStore((state) => state.user?.id)
  const client = useQueryClient()
  return useMutation({
    mutationFn: (entry: ServerQueueEntry) => {
      if (useAuthStore.getState().user?.id !== ownerId)
        throw new Error('Account changed. Refresh the request.')
      if (!canCancelQueuedRequest(entry)) throw new Error('Launch is already in progress.')
      return api.post<ServerQueueEntry>(`/server-queue/${entry.id}/cancel`, {})
    },
    onMutate: () => ({ ownerId: useAuthStore.getState().user?.id }),
    onSuccess: (entry, _submitted, context) => {
      if (useAuthStore.getState().user?.id === context.ownerId) {
        client.setQueryData(queueKeys.detail(context.ownerId, entry.id), entry)
      }
    },
    onSettled: (_data, _error, _entry, context) => {
      if (context) return client.invalidateQueries({ queryKey: queueKeys.owner(context.ownerId) })
    },
  })
}
