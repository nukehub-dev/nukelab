// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useToast } from '../stores/toast-store'
import type {
  CreditRequest,
  CreditRequestListResponse,
  CreditRequestMessage,
  CreditRequestStats,
} from '../types/api'

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return 'An unexpected error occurred'
}

interface CreditRequestListParams {
  status?: string
  page?: number
  limit?: number
  sort?: 'newest' | 'oldest'
}

function buildQueryString(params: CreditRequestListParams): string {
  const searchParams = new URLSearchParams()
  if (params.status) searchParams.set('status', params.status)
  if (params.page) searchParams.set('page', String(params.page))
  if (params.limit) searchParams.set('limit', String(params.limit))
  if (params.sort) searchParams.set('sort', params.sort)
  const queryString = searchParams.toString()
  return queryString ? `?${queryString}` : ''
}

export function useMyCreditRequests(params: CreditRequestListParams = {}) {
  return useQuery({
    queryKey: ['credit-requests', 'mine', params],
    queryFn: async () => {
      const response = await api.get<CreditRequestListResponse>(
        `/credit-requests/${buildQueryString(params)}`
      )
      return response
    },
  })
}

export function useAllCreditRequests(params: CreditRequestListParams = {}) {
  return useQuery({
    queryKey: ['credit-requests', 'all', params],
    queryFn: async () => {
      const response = await api.get<CreditRequestListResponse>(
        `/credit-requests/all${buildQueryString(params)}`
      )
      return response
    },
  })
}

export function usePendingCreditRequestCount() {
  return useQuery({
    queryKey: ['credit-requests', 'pending-count'],
    queryFn: async () => {
      const response = await api.get<{ pending: number }>('/credit-requests/pending-count')
      return response
    },
  })
}

export function useCreditRequestStats() {
  return useQuery({
    queryKey: ['credit-requests', 'stats'],
    queryFn: async () => {
      const response = await api.get<CreditRequestStats>('/credit-requests/stats')
      return response
    },
  })
}

export function useCreditRequestMessages(requestId: string | undefined) {
  return useQuery({
    queryKey: ['credit-requests', 'messages', requestId],
    queryFn: async () => {
      const response = await api.get<{ messages: CreditRequestMessage[] }>(
        `/credit-requests/${requestId}/messages`
      )
      return response
    },
    enabled: !!requestId,
  })
}

export function useAddCreditRequestMessage() {
  const queryClient = useQueryClient()
  const { error: showError } = useToast()

  return useMutation({
    mutationFn: ({
      requestId,
      body,
      internal,
    }: {
      requestId: string
      body: string
      internal?: boolean
    }) =>
      api.post<{ message: CreditRequestMessage }>(`/credit-requests/${requestId}/messages`, {
        body,
        internal,
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['credit-requests'] })
      queryClient.invalidateQueries({
        queryKey: ['credit-requests', 'messages', variables.requestId],
      })
    },
    onError: (err) => {
      showError('Failed to send message', getErrorMessage(err))
    },
  })
}

interface BulkReviewResult {
  request_id: string
  error?: string
}

interface BulkReviewResponse {
  message: string
  results: { success: BulkReviewResult[]; failed: BulkReviewResult[] }
}

interface BulkReviewData {
  requestIds: string[]
  action: 'approve' | 'reject'
  note?: string
}

export function useBulkReviewCreditRequests() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  return useMutation({
    mutationFn: ({ requestIds, action, note }: BulkReviewData) =>
      api.post<BulkReviewResponse>('/credit-requests/bulk-review', {
        request_ids: requestIds,
        action,
        note,
      }),
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['credit-requests'] })
      queryClient.invalidateQueries({ queryKey: ['credits'] })
      const ok = data.results.success.length
      const fail = data.results.failed.length
      if (fail > 0) {
        showError(
          `Bulk ${variables.action} partially failed`,
          `${ok} succeeded, ${fail} failed — see results`
        )
      } else {
        success(`Bulk ${variables.action} complete`, data.message)
      }
    },
    onError: (err) => {
      showError('Failed to bulk review requests', getErrorMessage(err))
    },
  })
}

export function useCancelCreditRequest() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  return useMutation({
    mutationFn: (requestId: string) =>
      api.post<{ message: string; request: CreditRequest }>(
        `/credit-requests/${requestId}/cancel`,
        {}
      ),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['credit-requests'] })
      success('Request cancelled', data.message)
    },
    onError: (err) => {
      showError('Failed to cancel request', getErrorMessage(err))
    },
  })
}

export function useCreateCreditRequest() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  return useMutation({
    mutationFn: (data: { amount: number; reason: string; request_type?: 'top_up' | 'allowance' }) =>
      api.post<{ message: string; request: CreditRequest }>('/credit-requests/', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credit-requests'] })
      success('Credit request submitted', 'Your request is pending admin review')
    },
    onError: (err) => {
      // Surfaces the duplicate-pending 400 detail ("You already have a pending credit request")
      showError('Failed to submit credit request', getErrorMessage(err))
    },
  })
}

interface ReviewRequestData {
  requestId: string
  amount?: number
  note?: string
}

export function useReviewCreditRequest() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  const approveRequest = useMutation({
    mutationFn: ({ requestId, amount, note }: ReviewRequestData) =>
      api.post<{ message: string; request: CreditRequest }>(
        `/credit-requests/${requestId}/approve`,
        { amount, note }
      ),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['credit-requests'] })
      queryClient.invalidateQueries({ queryKey: ['credits'] })
      success('Request approved', data.message)
    },
    onError: (err) => {
      showError('Failed to approve request', getErrorMessage(err))
    },
  })

  const rejectRequest = useMutation({
    mutationFn: ({ requestId, note }: ReviewRequestData) =>
      api.post<{ message: string; request: CreditRequest }>(
        `/credit-requests/${requestId}/reject`,
        { note }
      ),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['credit-requests'] })
      queryClient.invalidateQueries({ queryKey: ['credits'] })
      success('Request rejected', data.message)
    },
    onError: (err) => {
      showError('Failed to reject request', getErrorMessage(err))
    },
  })

  return { approveRequest, rejectRequest }
}
