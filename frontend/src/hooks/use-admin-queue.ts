// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery } from '@tanstack/react-query'
import { buildAdminQueueQuery, fetchAdminQueue, adminQueueAccess } from '../lib/admin-queue'
import { useAuthStore } from '../stores/auth-store'
import type { AdminQueueFilters, AdminQueuePage } from '../types/admin-queue'

export const adminQueueKeys = {
  all: ['admin-queue'] as const,
  lists: () => [...adminQueueKeys.all, 'list'] as const,
  list: (filters: AdminQueueFilters = {}) =>
    [...adminQueueKeys.all, 'list', buildAdminQueueQuery(filters)] as const,
}

/**
 * Read-only admin queue query. There is deliberately no admin cancel, retry,
 * or reconcile mutation here: starting work resolves through operation
 * recovery, and cancellation stays owner-only while a request is pending.
 */
export function useAdminQueue(filters: AdminQueueFilters = {}) {
  const canRead = useAuthStore(
    (state) => adminQueueAccess((permissions) => state.hasAllPermissions(permissions)).canRead
  )

  return useQuery<AdminQueuePage>({
    queryKey: adminQueueKeys.list(filters),
    queryFn: () => fetchAdminQueue(filters),
    enabled: canRead,
    retry: false,
  })
}
