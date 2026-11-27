// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { test, expect, type Page } from '@playwright/test'
import type { AdminJobEntry, AdminJobSummary } from '../src/types/admin-jobs'

const ids = {
  owner: '5f584904-6a94-4602-8144-66f215924270',
  recovery: 'f4e3f70f-4bf4-4f2d-a66c-35b6790ff9df',
  succeeded: 'a7a609c0-6603-44cb-80a2-c51dc7312e81',
  running: 'b8f7a72f-75a1-49c3-bf83-1c3c7ad8f0a2',
  secondAdmin: 'c9a8b830-86b2-4ad4-8dae-2f7d2c8a1f3b',
}

const admin = {
  id: '5f584904-6a94-4602-8144-66f215924271',
  username: 'admin',
  email: 'admin@example.test',
  first_name: 'Ada',
  last_name: 'Admin',
  display_name: 'Ada Admin',
  avatar_url: '',
  role: 'admin',
  permissions: ['admin:access', 'operations:read_all'],
  nuke_balance: 0,
  daily_allowance: 0,
  login_count: 0,
  is_active: true,
  is_verified: true,
  preferences: { timezone: 'UTC' },
}

function job(
  overrides: Partial<AdminJobEntry> & Pick<AdminJobEntry, 'id' | 'state'>
): AdminJobEntry {
  return {
    reason_code: null,
    owner_id: ids.owner,
    owner_username: 'researcher',
    owner_display_name: 'Researcher',
    environment_name: 'Approved runtime',
    environment_display_label: 'Approved runtime — approved 2026-11-20',
    plan_name: 'Small research plan',
    volume_display_name: 'pilot-data',
    created_at: '2026-11-27T12:00:00',
    updated_at: '2026-11-27T12:01:00',
    finished_at: null,
    reservation_active: false,
    guard_active: false,
    heartbeat_age_seconds: 30,
    log_state: 'pending',
    cleanup_state: 'pending',
    cleanup_attempts: 0,
    can_reconcile: false,
    ...overrides,
  }
}

const defaultJobs: AdminJobEntry[] = [
  job({
    id: ids.recovery,
    state: 'recovery_required',
    reason_code: 'recovery_required',
    reservation_active: true,
    guard_active: true,
    heartbeat_age_seconds: 420,
    cleanup_attempts: 2,
  }),
  job({
    id: ids.running,
    state: 'running',
    reason_code: 'waiting_capacity',
    created_at: '2026-11-27T11:00:00',
  }),
  job({
    id: ids.succeeded,
    state: 'succeeded',
    finished_at: '2026-11-27T10:30:00',
    created_at: '2026-11-27T10:00:00',
    log_state: 'available',
  }),
]

function summaryOf(jobs: AdminJobEntry[]): AdminJobSummary {
  const summary: AdminJobSummary = {
    total: jobs.length,
    queued: 0,
    starting: 0,
    running: 0,
    cancelling: 0,
    recovery_required: 0,
    succeeded: 0,
    failed: 0,
    cancelled: 0,
    timed_out: 0,
    expired: 0,
  }
  for (const entry of jobs) {
    if (entry.state in summary) {
      summary[entry.state as keyof AdminJobSummary] += 1
    }
  }
  return summary
}

async function mockAdminJobs(
  page: Page,
  options: {
    user?: typeof admin
    jobs?: AdminJobEntry[]
    failFirst?: boolean
    extraFields?: boolean
    totalOverride?: number
    gateFirst?: boolean
  } = {}
) {
  const currentAdmin = options.user ?? admin
  const jobs = options.jobs ?? defaultJobs
  const state = {
    jobs,
    calls: [] as URL[],
    reads: 0,
    failuresLeft: options.failFirst ? 1 : 0,
    entered: Promise.resolve() as Promise<void>,
    release: () => {},
  }
  let gateEntered: (() => void) | null = null
  let gateReleased: Promise<void> | null = null
  if (options.gateFirst) {
    state.entered = new Promise<void>((resolve) => {
      gateEntered = resolve
    })
    gateReleased = new Promise<void>((resolve) => {
      state.release = resolve
    })
  }

  await page.addInitScript((user) => {
    localStorage.setItem('nukelab-token', 'isolated-browser-token')
    localStorage.setItem('nukelab-auth', JSON.stringify({ state: { user }, version: 0 }))
  }, currentAdmin)

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api/, '')
    const fulfill = (json: unknown, status = 200) => route.fulfill({ status, json })

    if (path === '/users/me/profile') return fulfill(currentAdmin)
    if (path === '/health') return fulfill({ status: 'healthy' })
    if (path === '/notifications/unread-count') return fulfill({ unread_count: 0 })
    if (path === '/notifications/')
      return fulfill({ notifications: [], unread_count: 0, total: 0, page: 1, page_size: 20 })

    if (path === '/admin/jobs') {
      state.reads++
      state.calls.push(url)
      if (state.failuresLeft > 0) {
        state.failuresLeft--
        return fulfill({ detail: { code: 'availability_unavailable' } }, 503)
      }
      if (gateEntered) {
        const enter = gateEntered
        gateEntered = null
        enter()
        await gateReleased
      }
      const stateFilter = url.searchParams.get('state')
      const limit = Number(url.searchParams.get('limit') ?? '50')
      const offset = Number(url.searchParams.get('offset') ?? '0')
      const active = ['queued', 'starting', 'running', 'cancelling', 'recovery_required']
      const filtered = state.jobs.filter((entry) => {
        if (stateFilter === 'active') return active.includes(entry.state)
        if (stateFilter === 'history') return !active.includes(entry.state)
        return true
      })
      const pageItems = filtered.slice(offset, offset + limit).map((entry) =>
        options.extraFields
          ? {
              ...entry,
              argv: ['python', '/work/secret.py', '--token=argv-secret'],
              logs: { text: 'log-secret output' },
              environment_values: { API_KEY: 'env-secret' },
            }
          : entry
      )
      const total = Math.max(filtered.length, options.totalOverride ?? filtered.length)
      return fulfill({
        items: pageItems,
        pagination: {
          limit,
          offset,
          total,
          has_more: offset + pageItems.length < total,
        },
        summary: summaryOf(state.jobs),
      })
    }

    return fulfill({})
  })

  return state
}

test('admin without operations read cannot open the jobs view', async ({ page }) => {
  const state = await mockAdminJobs(page, {
    user: { ...admin, permissions: ['admin:access'], role: 'support' },
  })

  await page.goto('/admin/jobs')
  await expect(page).toHaveURL(/\/admin$/)
  expect(state.reads).toBe(0)
})

test('regular user cannot open the jobs view', async ({ page }) => {
  const state = await mockAdminJobs(page, {
    user: { ...admin, permissions: [], role: 'user' },
  })

  await page.goto('/admin/jobs')
  await expect(page).toHaveURL(/\/$/)
  expect(state.reads).toBe(0)
})

test('empty state explains that no batch jobs are recorded', async ({ page }) => {
  await mockAdminJobs(page, { jobs: [] })

  await page.goto('/admin/jobs')
  await expect(page.getByRole('heading', { name: 'Batch Jobs' })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByText('No batch jobs recorded')).toBeVisible()
  await expect(page.getByText('Read-only operator visibility')).toBeVisible()
  await expect(page.getByText(/no manual release or reconcile action/)).toBeVisible()
})

test('load error offers a retry and then renders confirmed rows', async ({ page }) => {
  await mockAdminJobs(page, { failFirst: true })

  await page.goto('/admin/jobs')
  await expect(page.getByText('Could not load batch jobs')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByTestId(`table-row-${ids.recovery}`)).toBeVisible({ timeout: 15_000 })
})

test('state, age, and pagination filters are server-owned', async ({ page }) => {
  const state = await mockAdminJobs(page, { totalOverride: 41 })

  await page.goto('/admin/jobs')
  await expect(page.getByTestId(`table-row-${ids.recovery}`)).toBeVisible({ timeout: 15_000 })

  await page.getByTestId('admin-jobs-state-filter-trigger').click()
  await page.getByTestId('admin-jobs-state-history').click()
  await expect(page.getByTestId(`table-row-${ids.succeeded}`)).toBeVisible()
  await expect(page.getByTestId(`table-row-${ids.recovery}`)).toHaveCount(0)
  expect(state.calls.at(-1)?.searchParams.get('state')).toBe('history')

  await page.getByTestId('admin-jobs-age-filter-trigger').click()
  await page.getByTestId('admin-jobs-age-3d').click()
  await expect.poll(() => state.calls.at(-1)?.searchParams.get('age_min_seconds')).toBe('259200')

  // Reset the age filter and page through the server result set.
  await page.getByTestId('admin-jobs-age-filter-trigger').click()
  await page.getByTestId('admin-jobs-age-all').click()
  await page.getByTestId('admin-jobs-state-filter-trigger').click()
  await page.getByTestId('admin-jobs-state-all').click()
  await expect(page.getByTestId(`table-row-${ids.recovery}`)).toBeVisible()

  await page.locator('button', { hasText: /^2$/ }).first().click()
  await expect.poll(() => state.calls.at(-1)?.searchParams.get('offset')).toBe('20')
})

test('operator rows omit command, log, and environment content', async ({ page }) => {
  await mockAdminJobs(page, { extraFields: true })

  await page.goto('/admin/jobs')
  await expect(page.getByTestId(`table-row-${ids.recovery}`)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Operator verification required').first()).toBeVisible()
  await expect(page.getByText('Reservation held').first()).toBeVisible()
  await expect(page.getByText('Volume guard active').first()).toBeVisible()

  const text = await page.locator('body').innerText()
  for (const forbidden of [
    'argv-secret',
    'secret.py',
    'log-secret output',
    'env-secret',
    'API_KEY',
    '/var/lib/private/runtime',
  ]) {
    expect(text).not.toContain(forbidden)
  }
  await expect(page.getByRole('button', { name: /cancel|reconcile|view logs/i })).toHaveCount(0)
})

test('long owner/target labels wrap inside their column instead of overlapping protection', async ({
  page,
}) => {
  await mockAdminJobs(page)

  await page.goto('/admin/jobs')
  const row = page.getByTestId(`table-row-${ids.running}`)
  await expect(row).toBeVisible({ timeout: 15_000 })

  const environment = row.getByText(/^Environment Approved runtime/)
  await expect(environment).toHaveCSS('white-space', 'normal')

  const protectionCell = row.getByRole('cell').nth(3)
  const [environmentBox, protectionBox] = await Promise.all([
    environment.boundingBox(),
    protectionCell.boundingBox(),
  ])
  expect(environmentBox).not.toBeNull()
  expect(protectionBox).not.toBeNull()
  expect(environmentBox!.x + environmentBox!.width).toBeLessThanOrEqual(protectionBox!.x + 1)
})

test('@vite-only account switch and logout clear the previous operator cache', async ({ page }) => {
  const state = await mockAdminJobs(page, { gateFirst: true })
  await page.goto('/admin/jobs')
  await state.entered

  const cachedRows = (actorId: string) =>
    page.evaluate(async (id) => {
      const { queryClient } = await import('/src/lib/api.ts')
      return queryClient.getQueryCache().findAll({ queryKey: ['admin-jobs', id] }).length
    }, actorId)

  expect(await cachedRows(admin.id)).toBeGreaterThan(0)

  await page.evaluate(async (nextId) => {
    const { useAuthStore } = await import('/src/stores/auth-store.ts')
    const current = useAuthStore.getState().user
    if (!current) throw new Error('missing signed-in user')
    useAuthStore.getState().setUser({
      ...current,
      id: nextId,
      username: 'second-admin',
      email: 'second-admin@example.test',
    })
  }, ids.secondAdmin)

  state.release()

  // The late first-actor response must not repopulate the removed namespace,
  // and the new actor's query must load on its own key.
  await expect.poll(() => cachedRows(admin.id)).toBe(0)
  await expect(page.getByTestId(`table-row-${ids.recovery}`)).toBeVisible({ timeout: 15_000 })
  await expect.poll(() => cachedRows(ids.secondAdmin)).toBeGreaterThan(0)

  await page.evaluate(async () => {
    const { useAuthStore } = await import('/src/stores/auth-store.ts')
    useAuthStore.getState().setUser(null)
  })
  await expect.poll(() => cachedRows(ids.secondAdmin)).toBe(0)
})
