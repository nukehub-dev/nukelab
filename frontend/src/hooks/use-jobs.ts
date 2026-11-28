// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from '@tanstack/react-query'
import { api, ApiError, queryClient } from '../lib/api'
import {
  canCancelJob,
  disabledJobCapabilities,
  isJobActive,
  jobPollInterval,
} from '../lib/batch-job'
import { PERMISSIONS, useAuthStore } from '../stores/auth-store'
import type {
  CreateJobRequest,
  EligibleJobRevisionList,
  JobCapabilities,
  JobDetail,
  JobListFilter,
  JobLogs,
  JobPage,
} from '../types/batch-job'

export const jobKeys = {
  owner: (ownerId: string | undefined) => ['batch-jobs', ownerId] as const,
  capabilities: (ownerId: string | undefined) => ['batch-jobs', ownerId, 'capabilities'] as const,
  eligibleRevisions: (ownerId: string | undefined) =>
    ['batch-jobs', ownerId, 'eligible-revisions'] as const,
  lists: (ownerId: string | undefined) => ['batch-jobs', ownerId, 'list'] as const,
  list: (ownerId: string | undefined, filter: JobListFilter) =>
    ['batch-jobs', ownerId, 'list', filter] as const,
  detail: (ownerId: string | undefined, id: string | undefined) =>
    ['batch-jobs', ownerId, 'detail', id] as const,
  logs: (ownerId: string | undefined, id: string | undefined) =>
    ['batch-jobs', ownerId, 'logs', id] as const,
}

// The subscription outlives route mounts, including logout while another page is open.
useAuthStore.subscribe((state, previous) => {
  if (state.user?.id !== previous.user?.id) {
    const filters = { queryKey: jobKeys.owner(previous.user?.id) }
    void queryClient.cancelQueries(filters)
    queryClient.removeQueries(filters)
  }
})

function hidden() {
  return typeof document !== 'undefined' && document.hidden
}

function unavailable(error: unknown) {
  return error instanceof ApiError && [403, 404, 503].includes(error.status)
}

function useCanReadJobs() {
  return useAuthStore((state) => state.hasPermission(PERMISSIONS.JOBS_READ_OWN))
}

function useCanWriteJobs() {
  return useAuthStore((state) => state.hasPermission(PERMISSIONS.JOBS_WRITE_OWN))
}

export function useJobCapabilities() {
  const ownerId = useAuthStore((state) => state.user?.id)
  const canRead = useCanReadJobs()
  return useQuery<JobCapabilities>({
    queryKey: jobKeys.capabilities(ownerId),
    queryFn: async () => {
      try {
        return await api.get<JobCapabilities>('/jobs/capabilities')
      } catch (error) {
        if (unavailable(error)) {
          return disabledJobCapabilities(
            error instanceof ApiError && error.status === 403
              ? 'permission_denied'
              : 'feature_disabled'
          )
        }
        throw error
      }
    },
    enabled: !!ownerId && canRead,
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  })
}

export function useEligibleJobRevisions(enabled: boolean) {
  const ownerId = useAuthStore((state) => state.user?.id)
  const canWrite = useCanWriteJobs()
  return useQuery<EligibleJobRevisionList>({
    queryKey: jobKeys.eligibleRevisions(ownerId),
    queryFn: () => api.get<EligibleJobRevisionList>('/jobs/eligible-revisions'),
    enabled: !!ownerId && canWrite && enabled,
    retry: false,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  })
}

export function useJobs(filter: JobListFilter, enabled: boolean) {
  const ownerId = useAuthStore((state) => state.user?.id)
  return useInfiniteQuery<
    JobPage,
    Error,
    InfiniteData<JobPage, string | null>,
    readonly unknown[],
    string | null
  >({
    queryKey: jobKeys.list(ownerId, filter),
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ state: filter, limit: '25' })
      if (pageParam) params.set('cursor', pageParam)
      return api.get<JobPage>(`/jobs?${params.toString()}`)
    },
    initialPageParam: null,
    getNextPageParam: (lastPage) => lastPage.next_cursor || undefined,
    enabled: !!ownerId && enabled,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      if (unavailable(query.state.error)) return false
      const pages = query.state.data?.pages ?? []
      const active = pages.some((page) => page.items.some((item) => isJobActive(item.state)))
      return jobPollInterval(active, query.state.fetchFailureCount, hidden())
    },
  })
}

export function useJobDetail(id: string | undefined, enabled: boolean) {
  const ownerId = useAuthStore((state) => state.user?.id)
  return useQuery<JobDetail>({
    queryKey: jobKeys.detail(ownerId, id),
    queryFn: () => api.get<JobDetail>(`/jobs/${id}`),
    enabled: !!ownerId && !!id && enabled,
    retry: false,
    refetchOnWindowFocus: true,
    refetchInterval: (query) => {
      if (unavailable(query.state.error)) return false
      return jobPollInterval(
        !query.state.data || isJobActive(query.state.data.state),
        query.state.fetchFailureCount,
        hidden()
      )
    },
  })
}

/** Logs stay optional so the detail payload remains bounded. */
export function useJobLogs(id: string | undefined, enabled: boolean) {
  const ownerId = useAuthStore((state) => state.user?.id)
  return useQuery<JobLogs>({
    queryKey: jobKeys.logs(ownerId, id),
    queryFn: () => api.get<JobLogs>(`/jobs/${id}/logs`),
    enabled: !!ownerId && !!id && enabled,
    retry: false,
    staleTime: 10_000,
    refetchOnWindowFocus: true,
  })
}

interface CreateJobVariables {
  request: CreateJobRequest
  idempotencyKey: string
}

export function useCreateJob() {
  const ownerId = useAuthStore((state) => state.user?.id)
  const client = useQueryClient()
  return useMutation<JobDetail, Error, CreateJobVariables, { ownerId?: string }>({
    mutationFn: (variables) => {
      if (useAuthStore.getState().user?.id !== ownerId) {
        return Promise.reject(new Error('Account changed. Refresh the page.'))
      }
      return api.post<JobDetail>('/jobs', variables.request, {
        headers: { 'Idempotency-Key': variables.idempotencyKey },
      })
    },
    onMutate: () => ({ ownerId: useAuthStore.getState().user?.id }),
    onSuccess: (job, _variables, context) => {
      if (!context?.ownerId || useAuthStore.getState().user?.id !== context.ownerId) return
      client.setQueryData(jobKeys.detail(context.ownerId, job.id), job)
      void client.invalidateQueries({ queryKey: jobKeys.lists(context.ownerId) })
    },
  })
}

export function useCancelJob() {
  const ownerId = useAuthStore((state) => state.user?.id)
  const client = useQueryClient()
  return useMutation<JobDetail, Error, JobDetail, { ownerId?: string }>({
    mutationFn: (job) => {
      if (useAuthStore.getState().user?.id !== ownerId) {
        return Promise.reject(new Error('Account changed. Refresh the page.'))
      }
      if (!canCancelJob(job)) {
        return Promise.reject(new Error('This job can no longer be cancelled.'))
      }
      return api.post<JobDetail>(`/jobs/${job.id}/cancel`, {})
    },
    onMutate: () => ({ ownerId: useAuthStore.getState().user?.id }),
    onSuccess: (job, _submitted, context) => {
      if (!context?.ownerId || useAuthStore.getState().user?.id !== context.ownerId) return
      client.setQueryData(jobKeys.detail(context.ownerId, job.id), job)
    },
    onSettled: (_data, _error, job, context) => {
      if (!context?.ownerId || useAuthStore.getState().user?.id !== context.ownerId) return
      void client.invalidateQueries({ queryKey: jobKeys.detail(context.ownerId, job.id) })
      void client.invalidateQueries({ queryKey: jobKeys.lists(context.ownerId) })
    },
  })
}
