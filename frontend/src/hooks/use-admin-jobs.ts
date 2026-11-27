// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery } from '@tanstack/react-query'
import { queryClient } from '../lib/api'
import { adminJobAccess, buildAdminJobsQuery, fetchAdminJobs } from '../lib/admin-jobs'
import { useAuthStore } from '../stores/auth-store'
import type { AdminJobFilters, AdminJobPage } from '../types/admin-jobs'

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

/**
 * Read-only admin job query. There is deliberately no cancel, retry, or
 * reconcile mutation here: job recovery has no operator release path in this
 * release, and owner mutation stays in the owner Jobs surface.
 */
export function useAdminJobs(filters: AdminJobFilters = {}) {
  const ownerId = useAuthStore((state) => state.user?.id)
  const canRead = useAuthStore(
    (state) => adminJobAccess((permissions) => state.hasAllPermissions(permissions)).canRead
  )

  return useQuery<AdminJobPage>({
    queryKey: adminJobKeys.list(ownerId, filters),
    queryFn: () => fetchAdminJobs(filters),
    enabled: !!ownerId && canRead,
    retry: false,
  })
}
