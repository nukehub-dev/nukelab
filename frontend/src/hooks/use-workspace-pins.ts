// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useCallback, useMemo } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useCurrentUser } from './use-current-user'

export function useWorkspacePins() {
  const { data: user } = useCurrentUser()
  const queryClient = useQueryClient()

  const pinnedIds = useMemo(() => {
    const prefs = user?.preferences
    if (prefs && Array.isArray(prefs.pinned_workspace_ids)) {
      return prefs.pinned_workspace_ids as string[]
    }
    return [] as string[]
  }, [user?.preferences])

  const updatePinsMutation = useMutation({
    mutationFn: async (newIds: string[]) => {
      return api.put('/preferences/', { pinned_workspace_ids: newIds })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['me'] })
    },
  })

  const isPinned = useCallback(
    (workspaceId: string) => pinnedIds.includes(workspaceId),
    [pinnedIds]
  )

  const pinWorkspace = useCallback(
    (workspaceId: string) => {
      if (pinnedIds.includes(workspaceId)) return
      const newIds = [...pinnedIds, workspaceId]
      updatePinsMutation.mutate(newIds)
    },
    [pinnedIds, updatePinsMutation]
  )

  const unpinWorkspace = useCallback(
    (workspaceId: string) => {
      const newIds = pinnedIds.filter((id) => id !== workspaceId)
      updatePinsMutation.mutate(newIds)
    },
    [pinnedIds, updatePinsMutation]
  )

  const togglePin = useCallback(
    (workspaceId: string) => {
      if (pinnedIds.includes(workspaceId)) {
        unpinWorkspace(workspaceId)
      } else {
        pinWorkspace(workspaceId)
      }
    },
    [pinnedIds, pinWorkspace, unpinWorkspace]
  )

  const sortByPinned = useCallback(
    <T extends { id: string }>(items: T[]): T[] => {
      return [...items].sort((a, b) => {
        const aPinned = pinnedIds.includes(a.id) ? 1 : 0
        const bPinned = pinnedIds.includes(b.id) ? 1 : 0
        if (aPinned !== bPinned) return bPinned - aPinned
        return 0
      })
    },
    [pinnedIds]
  )

  return {
    pinnedIds,
    isPinned,
    pinWorkspace,
    unpinWorkspace,
    togglePin,
    sortByPinned,
    isPending: updatePinsMutation.isPending,
  }
}
