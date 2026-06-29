// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useToast } from '../stores/toast-store'
import type { ApiToken, ApiTokenWithValue, ApiTokenUsage } from '../types/api'

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message
  }
  if (typeof error === 'string') {
    return error
  }
  return 'An unexpected error occurred'
}

export function useTokens() {
  return useQuery({
    queryKey: ['tokens'],
    queryFn: async () => {
      const response = await api.get<ApiToken[]>('/tokens')
      return response
    },
  })
}

export function useTokenUsage(tokenId: string) {
  return useQuery({
    queryKey: ['tokens', tokenId, 'usage'],
    queryFn: async () => {
      const response = await api.get<ApiTokenUsage>(`/tokens/${tokenId}/usage`)
      return response
    },
    enabled: !!tokenId,
  })
}

interface CreateTokenData {
  name: string
  scopes: string[]
  expires_days: number
}

export function useTokenActions() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  const createToken = useMutation({
    mutationFn: (data: CreateTokenData) => api.post<ApiTokenWithValue>('/tokens', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tokens'] })
      success('Token created', 'Your new API token has been created successfully')
    },
    onError: (err) => {
      showError('Failed to create token', getErrorMessage(err))
    },
  })

  const regenerateToken = useMutation({
    mutationFn: (tokenId: string) =>
      api.post<ApiTokenWithValue>(`/tokens/${tokenId}/regenerate`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tokens'] })
      success('Token regenerated', 'Your API token has been regenerated successfully')
    },
    onError: (err) => {
      showError('Failed to regenerate token', getErrorMessage(err))
    },
  })

  const revokeToken = useMutation({
    mutationFn: (tokenId: string) => api.delete(`/tokens/${tokenId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tokens'] })
      success('Token revoked', 'The API token has been revoked')
    },
    onError: (err) => {
      showError('Failed to revoke token', getErrorMessage(err))
    },
  })

  const deleteToken = useMutation({
    mutationFn: (tokenId: string) => api.delete(`/tokens/${tokenId}/permanent`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tokens'] })
      success('Token deleted', 'The API token has been permanently deleted')
    },
    onError: (err) => {
      showError('Failed to delete token', getErrorMessage(err))
    },
  })

  return {
    createToken,
    regenerateToken,
    revokeToken,
    deleteToken,
  }
}
