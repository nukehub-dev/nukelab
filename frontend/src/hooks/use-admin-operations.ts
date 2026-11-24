// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import {
  buildAdminOperationQuery,
  fetchAdminOperation,
  fetchAdminOperations,
  reconcileAdminOperation,
} from '../lib/admin-operations'
import { PERMISSIONS, useAuthStore } from '../stores/auth-store'
import type {
  AdminOperation,
  AdminOperationFilters,
  AdminOperationKind,
  AdminOperationPage,
  AdminOperationReconcileResult,
} from '../types/admin-operations'

export const adminOperationKeys = {
  all: ['admin-operations'] as const,
  lists: () => [...adminOperationKeys.all, 'list'] as const,
  list: (filters: AdminOperationFilters = {}) =>
    [...adminOperationKeys.all, 'list', buildAdminOperationQuery(filters)] as const,
  detail: (kind: AdminOperationKind, id: string) =>
    [...adminOperationKeys.all, 'detail', kind, id] as const,
}

/** List and detail evidence both move together after a proof-backed reconcile. */
export function invalidateAdminOperationData(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: adminOperationKeys.all })
}

export function useAdminOperations(filters: AdminOperationFilters = {}) {
  const canRead = useAuthStore((state) =>
    state.hasAllPermissions([PERMISSIONS.OPERATIONS_READ_ALL, PERMISSIONS.ADMIN_ACCESS])
  )

  return useQuery<AdminOperationPage>({
    queryKey: adminOperationKeys.list(filters),
    queryFn: () => fetchAdminOperations(filters),
    enabled: canRead,
    retry: false,
  })
}

export function useAdminOperation(kind: AdminOperationKind, id: string | null) {
  const canRead = useAuthStore((state) =>
    state.hasAllPermissions([PERMISSIONS.OPERATIONS_READ_ALL, PERMISSIONS.ADMIN_ACCESS])
  )

  return useQuery<AdminOperation>({
    queryKey: adminOperationKeys.detail(kind, id ?? ''),
    queryFn: () => fetchAdminOperation(kind, id ?? ''),
    enabled: canRead && Boolean(id),
    retry: false,
  })
}

interface ReconcileOperationVariables {
  kind: AdminOperationKind
  id: string
  reason: string
}

export function useReconcileAdminOperation() {
  const queryClient = useQueryClient()

  return useMutation<AdminOperationReconcileResult, Error, ReconcileOperationVariables>({
    mutationFn: ({ kind, id, reason }) => reconcileAdminOperation(kind, id, reason),
    onSettled: () => invalidateAdminOperationData(queryClient),
  })
}
