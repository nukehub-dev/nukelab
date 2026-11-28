// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import {
  adminJobAccess,
  buildAdminJobsQuery,
  cancelAdminJob,
  fetchAdminJobs,
  reconcileAdminJob,
} from '../lib/admin-jobs'
import { queryClient } from '../lib/api'
import { useAuthStore } from '../stores/auth-store'
import type {
  AdminJobCancelResult,
  AdminJobFilters,
  AdminJobPage,
  AdminJobReconcileResult,
} from '../types/admin-jobs'

export const adminJobKeys = {
  all: ['admin-jobs'] as const,
  owner: (ownerId: string | undefined) => [...adminJobKeys.all, ownerId] as const,
  lists: (ownerId: string | undefined) => [...adminJobKeys.owner(ownerId), 'list'] as const,
  list: (ownerId: string | undefined, filters: AdminJobFilters = {}) =>
    [...adminJobKeys.owner(ownerId), 'list', buildAdminJobsQuery(filters)] as const,
}

// The subscription outlives route mounts, including logout while another page is open.
useAuthStore.subscribe((state, previous) => {
  if (state.user?.id !== previous.user?.id) {
    const filters = { queryKey: adminJobKeys.owner(previous.user?.id) }
    void queryClient.cancelQueries(filters)
    queryClient.removeQueries(filters)
  }
})

/** List rows refresh from the server after a proof-backed reconcile. */
export function invalidateAdminJobData(client: QueryClient): Promise<void> {
  return client.invalidateQueries({ queryKey: adminJobKeys.all })
}

/**
 * Read-only admin job list. Reconcile is a separate, proof-only mutation; the
 * list never applies an optimistic row update because only the server knows
 * whether runtime evidence supports a terminal transition.
 */
export function useAdminJobs(filters: AdminJobFilters = {}) {
  const ownerId = useAuthStore((state) => state.user?.id)
  const canRead = useAuthStore(
    (state) =>
      adminJobAccess(
        (permissions) => state.hasAllPermissions(permissions),
        (permissions) => state.hasAnyPermission(permissions)
      ).canRead
  )

  return useQuery<AdminJobPage>({
    queryKey: adminJobKeys.list(ownerId, filters),
    queryFn: () => fetchAdminJobs(filters),
    enabled: !!ownerId && canRead,
    retry: false,
  })
}

interface ReconcileJobVariables {
  id: string
  reason: string
}

export function useReconcileAdminJob() {
  const client = useQueryClient()

  return useMutation<AdminJobReconcileResult, Error, ReconcileJobVariables>({
    mutationFn: ({ id, reason }) => reconcileAdminJob(id, reason),
    onSuccess: () => invalidateAdminJobData(client),
  })
}

interface CancelJobVariables {
  id: string
  reason: string
}

/** Cancellation is server-owned; the list refreshes instead of patching locally. */
export function useCancelAdminJob() {
  const client = useQueryClient()

  return useMutation<AdminJobCancelResult, Error, CancelJobVariables>({
    mutationFn: ({ id, reason }) => cancelAdminJob(id, reason),
    onSuccess: () => invalidateAdminJobData(client),
  })
}
