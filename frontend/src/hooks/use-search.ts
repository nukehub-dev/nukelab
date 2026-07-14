// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { SearchResults, SearchScope } from '../types/api'

/**
 * Global search across servers, volumes, workspaces, environments, and users.
 * With a scope, the backend returns only that group (`group` param, limit 10).
 */
export function useSearch(query: string, scope?: SearchScope | null) {
  return useQuery({
    queryKey: ['search', scope ?? null, query],
    queryFn: () => {
      const groupParam = scope ? `&group=${scope}&limit=10` : '&limit=5'
      return api.get<SearchResults>(`/search/?q=${encodeURIComponent(query)}${groupParam}`)
    },
    enabled: query.trim().length >= 2,
  })
}
