// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, queryClient } from '../lib/api'
import { PERMISSIONS, useAuthStore } from '../stores/auth-store'
import type { Plan, Server } from '../types/api'
import type { QueuedServerAcceptance } from '../types/server-queue'
import type {
  EnvironmentManifest,
  RecreationPreview,
  RecreationRequest,
  RecreationSource,
  ServerProvenance,
} from '../types/server-provenance'
import type { Volume } from './use-volumes'

export const provenanceKeys = {
  owner: (owner: string | undefined) => ['server-provenance', owner] as const,
  capabilities: (owner: string | undefined) =>
    ['server-provenance', owner, 'capabilities'] as const,
  detail: (owner: string | undefined, serverId: string) =>
    ['server-provenance', owner, 'detail', serverId] as const,
  plans: (owner: string | undefined) => ['server-provenance', owner, 'plans'] as const,
  volumes: (owner: string | undefined) => ['server-provenance', owner, 'volumes'] as const,
}

useAuthStore.subscribe((state, previous) => {
  if (state.user?.id !== previous.user?.id) {
    const filters = { queryKey: provenanceKeys.owner(previous.user?.id) }
    void queryClient.cancelQueries(filters)
    queryClient.removeQueries(filters)
  }
})

export function useProvenanceCapabilities() {
  const ownerId = useAuthStore((state) => state.user?.id)
  const canRead = useAuthStore((state) => state.hasPermission(PERMISSIONS.SERVERS_READ_OWN))
  return useQuery({
    queryKey: provenanceKeys.capabilities(ownerId),
    queryFn: async () => {
      try {
        return await api.get<{ enabled: boolean }>('/servers/provenance-capabilities')
      } catch (error) {
        if (error instanceof ApiError && [403, 404, 503].includes(error.status))
          return { enabled: false }
        throw error
      }
    },
    enabled: !!ownerId && canRead,
    staleTime: 60_000,
    retry: false,
  })
}

export function useServerProvenance(serverId: string, enabled: boolean) {
  const ownerId = useAuthStore((state) => state.user?.id)
  return useQuery({
    queryKey: provenanceKeys.detail(ownerId, serverId),
    queryFn: () => api.get<ServerProvenance>(`/servers/${serverId}/provenance`),
    enabled: !!ownerId && !!serverId && enabled,
    retry: false,
    refetchOnWindowFocus: true,
  })
}

export function useRecreationCatalog(enabled: boolean) {
  const ownerId = useAuthStore((state) => state.user?.id)
  const canReadVolumes = useAuthStore((state) => state.hasPermission(PERMISSIONS.VOLUMES_READ_OWN))
  const plans = useQuery({
    queryKey: provenanceKeys.plans(ownerId),
    queryFn: async () => {
      const result = await api.get<{ data: { items: Plan[] } }>('/plans/?is_active=true&limit=100')
      return result.data.items
    },
    enabled: !!ownerId && enabled,
    retry: false,
  })
  const volumes = useQuery({
    queryKey: provenanceKeys.volumes(ownerId),
    queryFn: async () =>
      (await api.get<{ volumes: Volume[] }>('/volumes/')).volumes.filter(
        (volume) => volume.status === 'active'
      ),
    enabled: !!ownerId && enabled && canReadVolumes,
    retry: false,
  })
  return { plans, volumes }
}

export function useValidateRecreation() {
  const ownerId = useAuthStore((state) => state.user?.id)
  return useMutation({
    mutationFn: (source: RecreationSource) => {
      if (!ownerId || useAuthStore.getState().user?.id !== ownerId)
        throw new Error('Account changed. Open the environment form again.')
      return api.post<RecreationPreview>('/servers/recreate/validate', source)
    },
  })
}

export function useRecreateServer() {
  const ownerId = useAuthStore((state) => state.user?.id)
  const client = useQueryClient()
  return useMutation({
    mutationFn: (request: RecreationRequest) => {
      if (!ownerId || useAuthStore.getState().user?.id !== ownerId)
        throw new Error('Account changed. Open the environment form again.')
      return api.post<Server | QueuedServerAcceptance>('/servers/recreate', request)
    },
    onMutate: () => ({ ownerId: useAuthStore.getState().user?.id }),
    onSuccess: (_result, _request, context) => {
      if (useAuthStore.getState().user?.id !== context.ownerId) return
      for (const queryKey of [
        ['servers'],
        ['dashboard'],
        ['volumes'],
        ['server-queue', context.ownerId],
        provenanceKeys.owner(context.ownerId),
      ]) {
        void client.invalidateQueries({ queryKey })
      }
    },
  })
}

export function fetchEnvironmentManifest(serverId: string, launchId: string) {
  return api.get<EnvironmentManifest>(
    `/servers/${serverId}/environment-manifest?launch_id=${encodeURIComponent(launchId)}`
  )
}
