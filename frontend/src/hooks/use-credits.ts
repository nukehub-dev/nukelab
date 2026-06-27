import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useToast } from '../stores/toast-store'
import type {
  CreditSummary,
  CreditHistoryResponse,
  CreditTransaction,
  LowBalanceUser,
} from '../types/api'

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return 'An unexpected error occurred'
}

interface CreditHistoryParams {
  transaction_type?: string
  from_date?: string
  to_date?: string
  page?: number
  limit?: number
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

export function useCreditSummary(userId: string) {
  return useQuery({
    queryKey: ['credits', 'summary', userId],
    queryFn: async () => {
      const response = await api.get<{
        user_id: string
        balance: number
        daily_allowance: number
        summary: CreditSummary
      }>(`/credits/users/${userId}`)
      return response
    },
    enabled: !!userId,
  })
}

export function useMyCreditSummary() {
  return useQuery({
    queryKey: ['credits', 'my-summary'],
    queryFn: async () => {
      const response = await api.get<{
        user_id: string
        balance: number
        daily_allowance: number
        summary: CreditSummary
      }>('/credits/')
      return response
    },
  })
}

export function useMyCreditHistory(params: CreditHistoryParams = {}) {
  return useQuery({
    queryKey: ['credits', 'my-history', params],
    queryFn: async () => {
      const searchParams = new URLSearchParams()
      if (params.transaction_type) searchParams.set('transaction_type', params.transaction_type)
      if (params.from_date) searchParams.set('from_date', params.from_date)
      if (params.to_date) searchParams.set('to_date', params.to_date)
      if (params.page) searchParams.set('page', String(params.page))
      if (params.limit) searchParams.set('limit', String(params.limit))
      if (params.sort_by) searchParams.set('sort_by', params.sort_by)
      if (params.sort_order) searchParams.set('sort_order', params.sort_order)

      const queryString = searchParams.toString()
      const response = await api.get<CreditHistoryResponse>(
        `/credits/history${queryString ? `?${queryString}` : ''}`
      )
      return response
    },
  })
}

export function useCreditHistory(userId: string, params: CreditHistoryParams = {}) {
  return useQuery({
    queryKey: ['credits', 'history', userId, params],
    queryFn: async () => {
      const searchParams = new URLSearchParams()
      if (params.transaction_type) searchParams.set('transaction_type', params.transaction_type)
      if (params.from_date) searchParams.set('from_date', params.from_date)
      if (params.to_date) searchParams.set('to_date', params.to_date)
      if (params.page) searchParams.set('page', String(params.page))
      if (params.limit) searchParams.set('limit', String(params.limit))
      if (params.sort_by) searchParams.set('sort_by', params.sort_by)
      if (params.sort_order) searchParams.set('sort_order', params.sort_order)

      const queryString = searchParams.toString()
      const response = await api.get<CreditHistoryResponse>(
        `/credits/users/${userId}/history?${queryString}`
      )
      return response
    },
    enabled: !!userId,
  })
}

interface LowBalanceParams {
  threshold?: number
  page?: number
  limit?: number
}

export function useLowBalanceUsers(params: LowBalanceParams = {}) {
  const { threshold = 100, page = 1, limit = 50 } = params
  return useQuery({
    queryKey: ['credits', 'low-balance', threshold, page, limit],
    queryFn: async () => {
      const response = await api.get<{
        threshold: number
        count: number
        users: LowBalanceUser[]
        pagination: { page: number; limit: number; total: number; total_pages: number }
      }>(`/credits/low-balance?threshold=${threshold}&page=${page}&limit=${limit}`)
      return response
    },
  })
}

interface GrantCreditsData {
  userId: string
  amount: number
  reason: string
}

interface DeductCreditsData {
  userId: string
  amount: number
  reason: string
}

export function useCreditActions() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  const grantCredits = useMutation({
    mutationFn: ({ userId, amount, reason }: GrantCreditsData) =>
      api.post<{ message: string; transaction: CreditTransaction }>(
        `/credits/users/${userId}/grant`,
        { amount, reason }
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['credits'] })
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['credits', 'summary', variables.userId] })
      queryClient.invalidateQueries({ queryKey: ['credits', 'history', variables.userId] })
      success('Credits granted', `Granted ${variables.amount} credits to user`)
    },
    onError: (err) => {
      showError('Failed to grant credits', getErrorMessage(err))
    },
  })

  const deductCredits = useMutation({
    mutationFn: ({ userId, amount, reason }: DeductCreditsData) =>
      api.post<{ message: string; transaction: CreditTransaction }>(
        `/credits/users/${userId}/deduct`,
        { amount, reason }
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['credits'] })
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['credits', 'summary', variables.userId] })
      queryClient.invalidateQueries({ queryKey: ['credits', 'history', variables.userId] })
      success('Credits deducted', `Deducted ${variables.amount} credits from user`)
    },
    onError: (err) => {
      showError('Failed to deduct credits', getErrorMessage(err))
    },
  })

  const updateUserDailyAllowance = useMutation({
    mutationFn: ({ userId, amount }: { userId: string; amount: number }) =>
      api.put<{ message: string; user: { daily_allowance: number } }>(
        `/credits/users/${userId}/daily-allowance`,
        { amount }
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['credits'] })
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['credits', 'summary', variables.userId] })
      success('Daily allowance updated', `Set to ${variables.amount.toLocaleString()} NUKE / day`)
    },
    onError: (err) => {
      showError('Failed to update daily allowance', getErrorMessage(err))
    },
  })

  return {
    grantCredits,
    deductCredits,
    updateUserDailyAllowance,
  }
}

interface BulkResult {
  user_id: string
  error?: string
  granted_amount?: number
  new_balance?: number
  capped?: boolean
  daily_allowance?: number
}

interface BulkResponse {
  message: string
  results: { success: BulkResult[]; failed: BulkResult[] }
}

interface BulkGrantData {
  userIds: string[]
  amount: number
  reason: string
}

interface BulkAllowanceData {
  userIds: string[]
  amount: number
}

export function useBulkCreditActions() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  const bulkGrantCredits = useMutation({
    mutationFn: ({ userIds, amount, reason }: BulkGrantData) =>
      api.post<BulkResponse>('/admin/credits/grant-bulk', {
        user_ids: userIds,
        amount,
        reason,
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['credits'] })
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      const ok = data.results.success.length
      const fail = data.results.failed.length
      if (fail > 0) {
        showError('Bulk grant partially failed', `${ok} succeeded, ${fail} failed — see results`)
      } else {
        success('Bulk grant complete', data.message)
      }
    },
    onError: (err) => {
      showError('Failed to bulk grant credits', getErrorMessage(err))
    },
  })

  const bulkSetAllowance = useMutation({
    mutationFn: ({ userIds, amount }: BulkAllowanceData) =>
      api.post<BulkResponse>('/admin/credits/bulk-allowance', {
        user_ids: userIds,
        amount,
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['credits'] })
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      const ok = data.results.success.length
      const fail = data.results.failed.length
      if (fail > 0) {
        showError(
          'Bulk allowance partially failed',
          `${ok} succeeded, ${fail} failed — see results`
        )
      } else {
        success('Bulk allowance update complete', data.message)
      }
    },
    onError: (err) => {
      showError('Failed to bulk update allowance', getErrorMessage(err))
    },
  })

  return { bulkGrantCredits, bulkSetAllowance }
}

interface AllowanceOverrideData {
  userId: string
  amount: number
  until: string // ISO 8601
}

export function useAllowanceOverride() {
  const queryClient = useQueryClient()
  const { success, error: showError } = useToast()

  const setOverride = useMutation({
    mutationFn: ({ userId, amount, until }: AllowanceOverrideData) =>
      api.put<{ message: string; user: { daily_allowance_override: number } }>(
        `/credits/users/${userId}/allowance-override`,
        { amount, until }
      ),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['credits'] })
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['credits', 'summary', variables.userId] })
      success(
        'Override set',
        `${variables.amount.toLocaleString()} NUKE/day until ${new Date(variables.until).toLocaleString()}`
      )
    },
    onError: (err) => {
      showError('Failed to set override', getErrorMessage(err))
    },
  })

  const clearOverride = useMutation({
    mutationFn: (userId: string) =>
      api.delete<{ message: string; user: { daily_allowance_override: number } }>(
        `/credits/users/${userId}/allowance-override`
      ),
    onSuccess: (_data, userId) => {
      queryClient.invalidateQueries({ queryKey: ['credits'] })
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['credits', 'summary', userId] })
      success('Override cleared', 'Reverted to base daily allowance')
    },
    onError: (err) => {
      showError('Failed to clear override', getErrorMessage(err))
    },
  })

  return { setOverride, clearOverride }
}
