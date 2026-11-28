// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { test, expect, type Page } from '@playwright/test'
import type {
  EligibleJobRevision,
  JobCapabilities,
  JobDetail,
  JobLogs,
  JobLogState,
  JobState,
  JobSummary,
} from '../src/types/batch-job'

const ids = {
  owner: '5f584904-6a94-4602-8144-66f215924270',
  revision: 'd6d2e4b3-4796-4335-9247-8ab76ce8e378',
  environment: '74e90887-4ee9-4f6f-a0d5-02c004477ea6',
  plan: '88136537-bd44-4522-8796-897d21d66a75',
  paidPlan: '99136537-bd44-4522-8796-897d21d66a76',
  volume: 'b7e48a5f-0e4d-45a8-93cb-1cbc67581e83',
  job: 'f4e3f70f-4bf4-4f2d-a66c-35b6790ff9df',
  foreign: 'a7a609c0-6603-44cb-80a2-c51dc7312e81',
}

const owner = {
  id: ids.owner,
  username: 'researcher',
  email: 'researcher@example.test',
  display_name: 'Researcher',
  avatar_url: '',
  role: 'user',
  permissions: ['jobs:read_own', 'jobs:write_own'],
  nuke_balance: 100,
  daily_allowance: 10,
  login_count: 0,
  is_active: true,
  is_verified: true,
  preferences: { timezone: 'UTC' },
}

const plan = {
  id: ids.plan,
  name: 'Small research plan',
  slug: 'small',
  cpu_limit: 2,
  memory_limit: '4g',
  disk_limit: '20g',
  gpu_limit: 0,
  cost_per_hour: 0,
  category: 'cpu',
  max_servers_per_user: 5,
  cooldown_seconds: 0,
  is_active: true,
  is_public: true,
  visible_to_roles: [],
  allow_servers: true,
  allow_batch_jobs: true,
  priority: 0,
  created_at: '2026-11-15T12:00:00',
}

const volume = {
  id: ids.volume,
  name: 'pilot-data',
  display_name: 'pilot-data',
  owner_id: ids.owner,
  visibility: 'private',
  size_bytes: 1024 * 1024 * 64,
  status: 'active',
  server_count: 0,
  created_at: '2026-11-15T12:00:00',
  updated_at: '2026-11-15T12:00:00',
}

const revision: EligibleJobRevision = {
  revision_id: ids.revision,
  environment_id: ids.environment,
  environment_name: 'Approved runtime',
  display_label: 'Approved runtime — 2026-11-20',
  fingerprint: 'sha256:abcdef',
  portable_fingerprint: null,
  image_reference: 'registry.example.test/approved@sha256:abcdef',
  supports_jobs: true,
  reason_code: null,
}

function capabilities(overrides: Partial<JobCapabilities> = {}): JobCapabilities {
  return {
    enabled: true,
    can_submit: true,
    billing_mode: 'zero_cost',
    secrets_enabled: false,
    storage_limits_enforced: true,
    storage_enforcement_required: false,
    reason_code: null,
    limits: {
      max_active_jobs: 1,
      max_queued_jobs: 3,
      default_runtime_seconds: 1800,
      max_runtime_seconds: 7200,
      queue_ttl_seconds: 86400,
      max_argv_items: 64,
      max_input_bytes: 16384,
      log_tail_bytes: 262144,
      log_retention_seconds: 604800,
    },
    ...overrides,
  }
}

function detail(
  state: JobState,
  options: {
    logs?: JobLogState
    canCancel?: boolean
    exitCode?: number | null
    result?: boolean
  } = {}
): JobDetail {
  const terminal = ['succeeded', 'failed', 'cancelled', 'timed_out', 'expired'].includes(state)
  const logState = options.logs ?? (terminal ? 'available' : 'pending')
  return {
    id: ids.job,
    name: 'preserved-checksum',
    state,
    reason_code: state === 'queued' ? 'waiting_capacity' : null,
    reason_message: state === 'queued' ? 'Waiting for capacity' : null,
    created_at: '2026-11-27T12:00:00',
    updated_at: '2026-11-27T12:01:00',
    queue_expires_at: terminal ? null : '2026-11-28T12:00:00',
    started_at: state === 'queued' ? null : '2026-11-27T12:01:00',
    finished_at: terminal ? '2026-11-27T12:02:00' : null,
    deadline_at: state === 'queued' ? null : '2026-11-27T12:31:00',
    can_cancel: options.canCancel ?? ['queued', 'starting', 'running'].includes(state),
    replayed: false,
    environment: {
      revision_id: ids.revision,
      environment_id: ids.environment,
      name: 'Approved runtime',
      display_label: revision.display_label,
      fingerprint: revision.fingerprint,
      image_reference: revision.image_reference,
    },
    plan: {
      id: ids.plan,
      name: plan.name,
      cpu: 2,
      memory_mib: 4096,
      disk_mib: 20480,
      gpu_count: 0,
      cost_per_hour: 0,
    },
    volume: { id: ids.volume, display_name: volume.display_name, available: true },
    argv: ['python', '/work/input.py', '--flag'],
    limits: { max_runtime_seconds: 1800 },
    result:
      options.result === false || !terminal
        ? null
        : {
            exit_code: options.exitCode === undefined ? 0 : options.exitCode,
            outcome_code:
              state === 'succeeded' ? 'succeeded' : state === 'timed_out' ? 'timed_out' : 'failed',
            started_at: '2026-11-27T12:01:00',
            finished_at: '2026-11-27T12:02:00',
            duration_seconds: 60,
            proof: 'observed',
          },
    logs: {
      state: logState,
      truncated: logState === 'truncated',
      size_bytes: logState === 'available' || logState === 'truncated' ? 2048 : 0,
      expires_at: logState === 'pending' ? null : '2026-12-04T12:00:00',
    },
    billing: {
      mode: 'zero_cost',
      charged: 0,
      authorized: 0,
      rate_per_hour: 0,
      state: 'none',
      unpaid: 0,
    },
  }
}

function summary(job: JobDetail): JobSummary {
  return {
    id: job.id,
    name: job.name,
    state: job.state,
    reason_code: job.reason_code,
    environment_name: job.environment.name,
    created_at: job.created_at,
    started_at: job.started_at,
    finished_at: job.finished_at,
    can_cancel: job.can_cancel,
  }
}

async function fillEligibleJob(page: Page) {
  const dialog = page.getByRole('dialog')
  await dialog.getByTestId('job-name').fill('preserved-checksum')
  await dialog.getByTestId('job-revision-trigger').click()
  await page.getByTestId(`job-revision-${ids.revision}`).click()
  await dialog.getByTestId('job-plan-trigger').click()
  await page.getByTestId(`job-plan-${ids.plan}`).click()
  await dialog.getByTestId('job-volume-trigger').click()
  await page.getByTestId(`job-volume-${ids.volume}`).click()
  await dialog.getByTestId('job-executable').fill('python')
  await dialog.getByTestId('job-args').fill('/work/input.py\n--flag')
  await expect(dialog.getByTestId('job-runtime-unit-minutes')).toHaveAttribute(
    'aria-pressed',
    'true'
  )
  await dialog.getByTestId('job-runtime').fill('10')
}

async function mockJobs(
  page: Page,
  options: {
    capability?: JobCapabilities
    job?: JobDetail | null
    logs?: JobLogs
    missing?: boolean
    list?: JobSummary[]
    plans?: Array<typeof plan>
    submitFailures?: number
    submitError?: { status: number; code: string }
    replayed?: boolean
  } = {}
) {
  const currentJob =
    options.job === undefined ? detail('queued') : options.job === null ? null : options.job
  const state = {
    capability: options.capability ?? capabilities(),
    job: currentJob,
    list: options.list ?? (currentJob ? [summary(currentJob)] : []),
    logs:
      options.logs ??
      ({
        state: 'available',
        text: 'checksum complete',
        truncated: false,
        size_bytes: 17,
        expires_at: '2026-12-04T12:00:00',
        encoding: 'utf-8',
      } satisfies JobLogs),
    creates: [] as Array<Record<string, unknown>>,
    idempotencyKeys: [] as Array<string | null>,
    cancels: 0,
    listReads: 0,
    detailReads: 0,
    logReads: 0,
  }

  await page.addInitScript((user) => {
    localStorage.setItem('nukelab-token', 'isolated-browser-token')
    localStorage.setItem('nukelab-auth', JSON.stringify({ state: { user }, version: 0 }))
  }, owner)

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace(/^\/api/, '')
    const method = request.method()
    const fulfill = (json: unknown, status = 200) => route.fulfill({ status, json })

    if (path === '/users/me/profile') return fulfill(owner)
    if (path === '/health') return fulfill({ status: 'healthy' })
    if (path === '/notifications/unread-count') return fulfill({ unread_count: 0 })
    if (path === '/notifications/')
      return fulfill({ notifications: [], unread_count: 0, total: 0, page: 1, page_size: 20 })
    if (path === '/plans/' && method === 'GET') {
      const plans = options.plans ?? [plan]
      return fulfill({
        success: true,
        data: { items: plans, total: plans.length, page: 1, limit: 100, pages: 1 },
      })
    }
    if (path === '/volumes/') return fulfill({ volumes: [volume] })
    if (path === '/jobs/capabilities') return fulfill(state.capability)
    if (path === '/jobs/eligible-revisions') return fulfill({ items: [revision] })
    if (path === '/jobs' && method === 'GET') {
      state.listReads++
      return fulfill({ items: state.list, next_cursor: null })
    }
    if (path === '/jobs' && method === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>
      state.creates.push(body)
      state.idempotencyKeys.push(request.headers()['idempotency-key'] ?? null)
      if (options.submitError) {
        return fulfill({ detail: { code: options.submitError.code } }, options.submitError.status)
      }
      if (state.creates.length <= (options.submitFailures ?? 0)) {
        return fulfill({ detail: { code: 'invalid_request' } }, 503)
      }
      const accepted = detail('queued')
      accepted.name = String(body.name)
      accepted.argv = body.argv as string[]
      accepted.limits = { max_runtime_seconds: Number(body.max_runtime_seconds) }
      accepted.replayed = options.replayed === true
      state.job = accepted
      state.list = [summary(accepted)]
      return fulfill(accepted, options.replayed ? 200 : 202)
    }
    if (path === `/jobs/${ids.job}` && method === 'GET') {
      state.detailReads++
      if (options.missing || !state.job) return fulfill({ detail: { code: 'job_not_found' } }, 404)
      return fulfill(state.job)
    }
    if (path === `/jobs/${ids.foreign}`) {
      return fulfill({ detail: { code: 'job_not_found' } }, 404)
    }
    if (path === `/jobs/${ids.job}/logs` && method === 'GET') {
      state.logReads++
      return fulfill(state.logs)
    }
    if (path === `/jobs/${ids.job}/cancel` && method === 'POST') {
      state.cancels++
      if (!state.job) return fulfill({ detail: { code: 'job_not_found' } }, 404)
      state.job = {
        ...state.job,
        state: state.job.state === 'queued' ? 'cancelled' : 'cancelling',
        can_cancel: false,
        reason_code: null,
        reason_message:
          state.job.state === 'queued'
            ? 'Job cancelled before admission.'
            : 'Waiting for the runtime to confirm termination.',
      }
      state.list = [summary(state.job)]
      return fulfill(state.job)
    }
    return fulfill({})
  })

  return state
}

test('disabled feature explains availability and does not query job records', async ({ page }) => {
  const state = await mockJobs(page, {
    capability: capabilities({
      enabled: false,
      can_submit: false,
      reason_code: 'feature_disabled',
    }),
  })

  await page.goto('/jobs')
  await expect(page.getByRole('heading', { name: 'Jobs', exact: true })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByRole('heading', { name: 'Batch jobs are not available' })).toBeVisible()
  await expect(page.getByText(/Batch job submission is disabled on this deployment/)).toBeVisible()
  await expect(page.getByTestId('new-job')).toHaveCount(0)
  expect(state.listReads).toBe(0)
})

test('submission-disabled rollout keeps authorized history readable', async ({ page }) => {
  const state = await mockJobs(page, {
    capability: capabilities({
      enabled: true,
      can_submit: false,
      reason_code: 'feature_disabled',
    }),
    job: detail('succeeded'),
  })

  await page.goto('/jobs')
  await expect(page.getByRole('heading', { name: 'Jobs', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'preserved-checksum' }).first()).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByTestId('new-job')).toBeDisabled()
  await expect(page.getByText(/Batch job submission is disabled on this deployment/)).toBeVisible()
  expect(state.listReads).toBeGreaterThan(0)
})

test('eligible selections submit once with an idempotency key and open the detail', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const state = await mockJobs(page)
  await page.goto('/jobs')
  await expect(page.getByRole('table', { name: 'Your batch jobs' })).toBeVisible({
    timeout: 15_000,
  })

  await page.getByTestId('new-job').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'New job' })).toBeVisible({ timeout: 15_000 })
  await fillEligibleJob(page)
  await dialog.getByTestId('job-submit').click()

  await expect(page).toHaveURL(new RegExp(`/jobs/${ids.job}$`))
  await expect(page.getByRole('heading', { name: 'preserved-checksum' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Queued' })).toBeVisible()
  await expect(page.getByText('Waiting for capacity')).toBeVisible()
  await expect(page.getByText('Approved runtime — 2026-11-20')).toBeVisible()
  await expect(page.getByRole('list', { name: 'Job command arguments' })).toContainText(
    '/work/input.py'
  )

  expect(state.creates).toHaveLength(1)
  expect(state.creates[0]).toMatchObject({
    name: 'preserved-checksum',
    revision_id: ids.revision,
    plan_id: ids.plan,
    volume_id: ids.volume,
    argv: ['python', '/work/input.py', '--flag'],
    max_runtime_seconds: 600,
  })
  expect(state.idempotencyKeys[0]).toMatch(/^[\x21-\x7e]{1,128}$/)
})

test('paid plans quote a rounded hold, note refunds, and surface insufficient credits', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const state = await mockJobs(page, {
    capability: capabilities({ billing_mode: 'paid' }),
    plans: [{ ...plan, cost_per_hour: 10 }],
    submitError: { status: 402, code: 'insufficient_credits' },
  })
  await page.goto('/jobs')
  await page.getByTestId('new-job').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'New job' })).toBeVisible({ timeout: 15_000 })
  await fillEligibleJob(page)
  await dialog.getByTestId('job-runtime').fill('15')

  await expect(dialog.getByTestId('job-plan-trigger')).toContainText('Small research plan')
  await expect(dialog.getByTestId('job-maximum-hold')).toHaveText('3 NUKE')
  await expect(dialog.getByTestId('job-hold-refund-note')).toContainText(
    'Unused credits are refunded after the terminal result'
  )

  await dialog.getByTestId('job-submit').click()
  await expect(
    dialog.getByText(
      'Not enough NUKE credits for the maximum runtime. Reduce the runtime or add credits.'
    )
  ).toBeVisible()
  await expect(page).toHaveURL(/\/jobs$/)
  expect(state.creates).toHaveLength(1)
  expect(state.creates[0]).toMatchObject({ max_runtime_seconds: 900 })
})

test('maximum runtime accepts seconds, minutes, and hours', async ({ page }) => {
  await mockJobs(page)
  await page.goto('/jobs')
  await page.getByTestId('new-job').click()
  const dialog = page.getByRole('dialog')

  await expect(dialog.getByTestId('job-runtime')).toHaveValue('30')
  await expect(dialog.getByTestId('job-runtime-unit-minutes')).toHaveAttribute(
    'aria-pressed',
    'true'
  )
  await dialog.getByTestId('job-runtime-unit-hours').click()
  await expect(dialog.getByTestId('job-runtime')).toHaveValue('0.5')

  await dialog.getByTestId('job-runtime-unit-seconds').click()
  await expect(dialog.getByTestId('job-runtime')).toHaveValue('1800')

  await dialog.getByTestId('job-runtime').fill('59')
  await dialog.getByTestId('job-submit').click()
  await expect(dialog.getByText('Use at least 1 minute (60 seconds).')).toBeVisible()
  await dialog.getByTestId('job-runtime').fill('600')
  await expect(dialog.getByText('Use at least 1 minute (60 seconds).')).toHaveCount(0)
})

test('server-only plans are not offered for batch jobs', async ({ page }) => {
  const serverOnlyPlan = {
    ...plan,
    id: ids.paidPlan,
    name: 'Server Only CPU',
    slug: 'server-only-cpu',
    allow_servers: true,
    allow_batch_jobs: false,
  }
  await mockJobs(page, { plans: [plan, serverOnlyPlan] })
  await page.goto('/jobs')
  await page.getByTestId('new-job').click()
  const dialog = page.getByRole('dialog')

  await dialog.getByTestId('job-plan-trigger').click()
  await expect(page.getByTestId(`job-plan-${ids.paidPlan}`)).toHaveCount(0)
  await expect(page.getByTestId(`job-plan-${ids.plan}`)).toBeVisible()
})

test('zero-cost mode lists paid CPU plans as disabled and explains why', async ({ page }) => {
  const paidPlan = {
    ...plan,
    id: ids.paidPlan,
    name: 'Jobs E2E Paid CPU',
    slug: 'jobs-e2e-paid',
    cost_per_hour: 60,
  }
  await mockJobs(page, { plans: [plan, paidPlan] })
  await page.goto('/jobs')
  await page.getByTestId('new-job').click()
  const dialog = page.getByRole('dialog')

  await expect(
    dialog.getByText('1 paid CPU plan listed but disabled because paid batch jobs are off.')
  ).toBeVisible()
  await dialog.getByTestId('job-plan-trigger').click()
  const paidOption = page.getByTestId(`job-plan-${ids.paidPlan}`)
  await expect(paidOption).toBeDisabled()
  await expect(paidOption).toContainText('Paid plan — paid batch jobs are disabled')

  await page.getByTestId(`job-plan-${ids.plan}`).click()
  await expect(dialog.getByTestId('job-plan-trigger')).toContainText('Small research plan')
})

test('paid detail reports the rate, authorized hold, charge and refund', async ({ page }) => {
  const paidJob = detail('succeeded')
  paidJob.plan = { ...paidJob.plan, cost_per_hour: 10 }
  paidJob.billing = {
    mode: 'paid',
    charged: 4,
    authorized: 5,
    rate_per_hour: 10,
    state: 'settled',
    unpaid: 0,
  }
  await mockJobs(page, {
    capability: capabilities({ billing_mode: 'paid' }),
    job: paidJob,
  })

  await page.goto(`/jobs/${ids.job}`)
  await expect(page.getByText('4 NUKE charged, 1 NUKE refunded').first()).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByText('10 NUKE/hr')).toBeVisible()
  await expect(page.getByText('5 NUKE', { exact: true })).toBeVisible()
})

test('held paid jobs show the authorized hold until settlement', async ({ page }) => {
  const heldJob = detail('running')
  heldJob.billing = {
    mode: 'paid',
    charged: 0,
    authorized: 6,
    rate_per_hour: 10,
    state: 'held',
    unpaid: 0,
  }
  await mockJobs(page, {
    capability: capabilities({ billing_mode: 'paid' }),
    job: heldJob,
  })

  await page.goto(`/jobs/${ids.job}`)
  await expect(page.getByText('6 NUKE held').first()).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('6 NUKE', { exact: true })).toBeVisible()
})

test('safe retries keep the idempotency key while a material edit rotates it', async ({ page }) => {
  const state = await mockJobs(page, { submitFailures: 2 })
  await page.goto('/jobs')
  await page.getByTestId('new-job').click()
  await fillEligibleJob(page)
  const dialog = page.getByRole('dialog')

  await dialog.getByTestId('job-submit').click()
  await expect(page.getByText('Review the request fields and try again.')).toBeVisible()
  await expect(dialog.getByTestId('job-name')).toHaveValue('preserved-checksum')
  await dialog.getByTestId('job-submit').click()
  await expect(page.getByText('Review the request fields and try again.')).toBeVisible()
  expect(state.idempotencyKeys).toHaveLength(2)
  expect(state.idempotencyKeys[1]).toBe(state.idempotencyKeys[0])

  await dialog.getByTestId('job-args').fill('/work/input.py\n--rotated')
  await dialog.getByTestId('job-submit').click()
  await expect(page).toHaveURL(new RegExp(`/jobs/${ids.job}$`))
  expect(state.idempotencyKeys).toHaveLength(3)
  expect(state.idempotencyKeys[2]).not.toBe(state.idempotencyKeys[0])
})

test('a replayed submission opens the same existing job', async ({ page }) => {
  await mockJobs(page, { replayed: true })
  await page.goto('/jobs')
  await page.getByTestId('new-job').click()
  await fillEligibleJob(page)
  await page.getByTestId('job-submit').click()
  await expect(page).toHaveURL(new RegExp(`/jobs/${ids.job}$`))
  await expect(page.getByText('Existing job opened', { exact: true })).toBeVisible()
})

test('foreign or deleted deep links show indistinguishable missing behavior', async ({ page }) => {
  await mockJobs(page, { missing: true })
  await page.goto(`/jobs/${ids.foreign}`)
  await expect(page.getByRole('heading', { name: 'Job unavailable' })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByText(/does not exist or is not available/)).toBeVisible()
  await expect(page.getByRole('link', { name: 'Back to jobs' })).toHaveAttribute('href', '/jobs')
})

test('cancel uses the authoritative response and shows pending-stop copy', async ({ page }) => {
  const state = await mockJobs(page, { job: detail('running') })
  await page.goto(`/jobs/${ids.job}`)
  await expect(page.getByRole('heading', { name: 'Running' })).toBeVisible({ timeout: 15_000 })

  await page.getByRole('button', { name: 'Cancel job' }).click()
  await expect(page.getByRole('heading', { name: 'Stop running job?' })).toBeVisible()
  await page.getByRole('button', { name: 'Cancel job' }).last().click()

  await expect(page.getByRole('heading', { name: 'Cancelling' })).toBeVisible()
  await expect(page.getByText(/Stop requested. The runtime must confirm termination/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel job' })).toHaveCount(0)
  expect(state.cancels).toBe(1)
})

test('pending and truncated logs are labelled and rendered as plain text', async ({ page }) => {
  const state = await mockJobs(page, {
    job: detail('succeeded', { logs: 'truncated' }),
    logs: {
      state: 'truncated',
      text: '<script>alert(1)</script>\nline two',
      truncated: true,
      size_bytes: 4096,
      expires_at: '2026-12-04T12:00:00',
      encoding: 'utf-8',
    },
  })
  await page.goto(`/jobs/${ids.job}`)
  await expect(page.getByText('Truncated', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/Only the last/)).toBeVisible()

  await page.getByRole('button', { name: 'Show logs' }).click()
  const output = page.getByRole('region', { name: 'Job output logs' })
  await expect(output).toBeVisible()
  await expect(output).toContainText('<script>alert(1)</script>')
  await expect(output).toContainText('line two')
  expect(state.logReads).toBe(1)
})

test('expired logs state explains retention without offering an empty view', async ({ page }) => {
  await mockJobs(page, {
    job: detail('succeeded', { logs: 'expired' }),
    logs: {
      state: 'expired',
      text: null,
      truncated: false,
      size_bytes: 0,
      expires_at: '2026-12-04T12:00:00',
      encoding: 'utf-8',
    },
  })
  await page.goto(`/jobs/${ids.job}`)
  await expect(page.getByText('Expired', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/log retention window has passed/).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Show logs' })).toHaveCount(0)
})

test('pending and unavailable log states remain explicit', async ({ page }) => {
  await mockJobs(page, { job: detail('queued') })
  await page.goto(`/jobs/${ids.job}`)
  await expect(page.getByText('Pending', { exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/Logs will be collected when the runtime starts/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Show logs' })).toHaveCount(0)

  await page.unroute('**/api/**')
  await mockJobs(page, {
    job: detail('succeeded', { logs: 'unavailable' }),
    logs: {
      state: 'unavailable',
      text: null,
      truncated: false,
      size_bytes: 0,
      expires_at: null,
      encoding: 'utf-8',
    },
  })
  await page.goto(`/jobs/${ids.job}`)
  await expect(page.getByText('Unavailable', { exact: true })).toBeVisible()
  await expect(page.getByText(/Logs could not be captured for this job/).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Show logs' })).toHaveCount(0)
})

test('mobile menu exposes Jobs and the list renders mobile cards', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockJobs(page, { job: detail('succeeded') })
  await page.goto('/jobs')
  await expect(page.getByRole('link', { name: /Open job/ }).first()).toBeVisible({
    timeout: 15_000,
  })

  await page.locator('nav.fixed.bottom-4 button').first().click()
  await expect(page.getByRole('link', { name: 'Jobs', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Servers', exact: true }).last()).toBeVisible()

  await page.setViewportSize({ width: 360, height: 800 })
  await page.goto(`/jobs/${ids.job}`)
  await expect(page.getByRole('heading', { name: 'preserved-checksum' })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByRole('link', { name: /Open output volume/ })).toBeVisible()
})
