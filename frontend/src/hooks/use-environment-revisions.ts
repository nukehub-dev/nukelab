// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchEnvironmentRevisions,
  revokeEnvironmentRevision,
  verifyEnvironmentArtifacts,
} from '../lib/environment-revisions'
import { PERMISSIONS, useAuthStore } from '../stores/auth-store'
import type {
  EnvironmentRevisionPage,
  RevokeEnvironmentRevisionResponse,
  VerifyEnvironmentArtifactsResponse,
} from '../types/environment-revisions'

export const environmentRevisionKeys = {
  all: ['environment-revisions'] as const,
  environment: (environmentId: string) => ['environment-revisions', environmentId] as const,
  list: (environmentId: string, limit: number, offset: number) =>
    ['environment-revisions', environmentId, 'list', { limit, offset }] as const,
}

interface EnvironmentRevisionsQuery {
  environmentId: string
  limit?: number
  offset?: number
  enabled?: boolean
}

export function useEnvironmentRevisions({
  environmentId,
  limit = 20,
  offset = 0,
  enabled = true,
}: EnvironmentRevisionsQuery) {
  const canRead = useAuthStore((state) =>
    state.hasAllPermissions([PERMISSIONS.ENVIRONMENT_READ, PERMISSIONS.ADMIN_ACCESS])
  )

  return useQuery<EnvironmentRevisionPage>({
    queryKey: environmentRevisionKeys.list(environmentId, limit, offset),
    queryFn: () => fetchEnvironmentRevisions(environmentId, { limit, offset }),
    enabled: enabled && canRead,
    retry: false,
  })
}

interface RevokeRevisionVariables {
  revisionId: string
  reason: string
  confirmLastRevision: boolean
}

export function useEnvironmentRevisionActions(environmentId: string) {
  const queryClient = useQueryClient()

  const verifyArtifacts = useMutation<VerifyEnvironmentArtifactsResponse, Error, string>({
    mutationFn: (reason) => verifyEnvironmentArtifacts(environmentId, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: environmentRevisionKeys.environment(environmentId),
      })
    },
  })

  const revokeRevision = useMutation<
    RevokeEnvironmentRevisionResponse,
    Error,
    RevokeRevisionVariables
  >({
    mutationFn: ({ revisionId, reason, confirmLastRevision }) =>
      revokeEnvironmentRevision(revisionId, { reason, confirmLastRevision }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: environmentRevisionKeys.environment(environmentId),
      })
    },
  })

  return { verifyArtifacts, revokeRevision }
}
