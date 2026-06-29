// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { User } from '../types/api'
import { useAuthStore } from '../stores/auth-store'

interface UseCurrentUserOptions {
  enabled?: boolean
}

export function useCurrentUser(options: UseCurrentUserOptions = {}) {
  const { enabled = true } = options
  const setUser = useAuthStore((state) => state.setUser)

  return useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      const user = await api.get<User>('/users/me/profile')
      setUser(user)
      return user
    },
    enabled,
    staleTime: 0,
    retry: false,
  })
}
