// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useMemo, useRef, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { AlertTriangle, Info, Plus, RefreshCw, Terminal } from 'lucide-react'
import { ResourcePageLayout } from '../components/layout/resource-page-layout'
import { Button } from '../components/ui/button'
import {
  JobsCapabilityLoadingState,
  JobsCards,
  JobsDisabledState,
  JobsEmptyState,
  JobsErrorState,
  JobsLoadingState,
  JobsLoadMore,
  JobsTable,
} from '../components/jobs/job-list'
import { NewJobDialog } from '../components/jobs/new-job-dialog'
import { parseJobListSearch, jobErrorMessage, JOB_LIST_FILTERS } from '../lib/batch-job'
import { useJobCapabilities, useJobs } from '../hooks/use-jobs'
import { PERMISSIONS, useAuthStore } from '../stores/auth-store'
import { usePageGuard } from '../hooks/use-page-guard'
import { cn } from '../lib/utils'
import type { JobListFilter } from '../types/batch-job'

export const Route = createFileRoute('/jobs/')({
  component: JobsPage,
  validateSearch: parseJobListSearch,
})

const filterLabels: Record<JobListFilter, string> = {
  active: 'Active',
  history: 'History',
  all: 'All',
}

function JobsPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.JOBS_READ_OWN })
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  const filter = search.state ?? 'all'
  const [newJobOpen, setNewJobOpen] = useState(false)
  const [newJobSession, setNewJobSession] = useState(0)
  const ownerId = useAuthStore((state) => state.user?.id)
  const previousOwner = useRef(ownerId)
  const openNewJob = () => {
    setNewJobSession((session) => session + 1)
    setNewJobOpen(true)
  }

  useEffect(() => {
    if (previousOwner.current === ownerId) return
    previousOwner.current = ownerId
    // Close and discard a draft when the authorized account changes.
    setNewJobOpen(false)
    setNewJobSession((session) => session + 1)
  }, [ownerId])

  const canWrite = useAuthStore((state) => state.hasPermission(PERMISSIONS.JOBS_WRITE_OWN))
  const capabilities = useJobCapabilities()
  const jobsEnabled = capabilities.data?.enabled === true
  const canSubmit = jobsEnabled && capabilities.data?.can_submit === true && canWrite
  const jobs = useJobs(filter, jobsEnabled)

  const items = useMemo(() => {
    const seen = new Set<string>()
    const result = []
    for (const page of jobs.data?.pages ?? []) {
      for (const item of page.items) {
        if (seen.has(item.id)) continue
        seen.add(item.id)
        result.push(item)
      }
    }
    return result
  }, [jobs.data])

  if (!allowed) return null

  const retryCapabilities = () => void capabilities.refetch()

  return (
    <ResourcePageLayout
      title="Jobs"
      subtitle="Run one noninteractive command in an approved environment and review its result."
      icon={Terminal}
    >
      {capabilities.isPending && <JobsCapabilityLoadingState />}

      {capabilities.isError && (
        <JobsErrorState error={capabilities.error} retry={retryCapabilities} />
      )}

      {capabilities.data && !capabilities.data.enabled && (
        <JobsDisabledState reasonCode={capabilities.data.reason_code} />
      )}

      {jobsEnabled && capabilities.data && (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div
              role="group"
              aria-label="Job status filter"
              className="flex w-fit items-center gap-0.5 rounded-lg border border-input/50 bg-input/80 p-0.5"
            >
              {JOB_LIST_FILTERS.map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={filter === value}
                  onClick={() => void navigate({ search: { state: value } })}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-xs font-medium transition-all',
                    filter === value
                      ? 'bg-background text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  {filterLabels[value]}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                aria-label="Refresh jobs"
                disabled={jobs.isFetching}
                onClick={() => void jobs.refetch()}
              >
                <RefreshCw
                  className={cn('h-3.5 w-3.5', jobs.isFetching && 'animate-spin')}
                  aria-hidden="true"
                />
                Refresh
              </Button>
              <Button data-testid="new-job" disabled={!canSubmit} onClick={openNewJob}>
                <Plus className="h-4 w-4" aria-hidden="true" />
                New job
              </Button>
            </div>
          </div>

          {!canSubmit && (
            <div
              role="status"
              className="flex items-start gap-2 rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-muted-foreground"
            >
              <AlertTriangle
                className="mt-0.5 h-4 w-4 shrink-0 text-amber-400"
                aria-hidden="true"
              />
              <span>
                {!canWrite
                  ? 'You can review existing jobs but do not have permission to submit new ones.'
                  : jobErrorMessage(
                      capabilities.data.reason_code,
                      'New job submission is currently disabled. Authorized job history remains available.'
                    )}
              </span>
            </div>
          )}

          <div className="flex items-start gap-2 rounded-xl border border-primary/15 bg-primary/5 p-3 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
            <p>
              Jobs run offline with one owned private volume mounted at{' '}
              <code className="font-mono">/work</code>. Active jobs refresh automatically; queued
              time is not billed.
            </p>
          </div>

          {jobs.isError && (
            <JobsErrorState error={jobs.error} retry={() => void jobs.refetch()} compact />
          )}

          {jobs.isPending && <JobsLoadingState />}

          {jobs.data && items.length === 0 && (
            <JobsEmptyState
              filter={filter}
              canSubmit={canSubmit}
              onNewJob={openNewJob}
              onShowAll={() => void navigate({ search: { state: 'all' } })}
            />
          )}

          {items.length > 0 && (
            <>
              <JobsTable items={items} />
              <JobsCards items={items} />
              <JobsLoadMore
                hasNextPage={jobs.hasNextPage}
                loading={jobs.isFetchingNextPage}
                onLoadMore={() => void jobs.fetchNextPage()}
              />
            </>
          )}

          <NewJobDialog
            key={`${ownerId ?? 'signed-out'}:${newJobSession}`}
            open={newJobOpen}
            onOpenChange={setNewJobOpen}
            capabilities={capabilities.data}
          />
        </div>
      )}
    </ResourcePageLayout>
  )
}
