// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { test, expect, type Page } from '@playwright/test'
import type { Environment, Plan } from '../src/types/api'

const admin = {
  id: '5f584904-6a94-4602-8144-66f215924271',
  username: 'admin',
  email: 'admin@example.test',
  first_name: 'Ada',
  last_name: 'Admin',
  display_name: 'Ada Admin',
  avatar_url: '',
  role: 'admin',
  permissions: ['admin:access', 'plan:read', 'plan:create', 'environment:read'],
  nuke_balance: 0,
  daily_allowance: 0,
  profile: {},
  preferences: { timezone: 'UTC' },
  profile_visibility: 'private',
  oauth_provider: null,
  is_active: true,
  is_verified: true,
  last_login: null,
  created_at: '2026-11-15T12:00:00',
  updated_at: null,
  login_count: 1,
  daily_allowance_override: null,
  daily_allowance_override_until: null,
  has_active_allowance_override: false,
  credit_requests_blocked: false,
  credit_requests_blocked_until: null,
  has_active_credit_request_block: false,
}

function plan(overrides: Partial<Plan> & Pick<Plan, 'id' | 'name' | 'slug'>): Plan {
  return {
    description: undefined,
    category: 'cpu',
    cpu_limit: 2,
    memory_limit: '4g',
    disk_limit: '20g',
    gpu_limit: 0,
    max_servers_per_user: 4,
    cost_per_hour: 1,
    cooldown_seconds: 0,
    is_public: false,
    visible_to_roles: [],
    is_active: true,
    priority: 0,
    created_at: '2026-11-15T12:00:00',
    ...overrides,
  }
}

function environment(
  overrides: Partial<Environment> & Pick<Environment, 'id' | 'name' | 'slug'>
): Environment {
  return {
    image: 'workspace:latest',
    is_active: true,
    is_public: true,
    created_at: '2026-11-15T12:00:00',
    ...overrides,
  }
}

async function mockSetup(
  page: Page,
  options: { plans?: Plan[]; environments?: Environment[] } = {}
) {
  const state = {
    plans: options.plans ?? [
      plan({ id: 'plan-small', name: 'Small', slug: 'small', visible_to_roles: ['user'] }),
      plan({ id: 'plan-xlarge', name: 'XLarge', slug: 'xlarge', cpu_limit: 16, cost_per_hour: 8 }),
      plan({
        id: 'plan-legacy',
        name: 'Legacy',
        slug: 'legacy',
        is_public: true,
        is_active: false,
      }),
    ],
    environments: options.environments ?? [
      environment({ id: 'env-public', name: 'Workspace', slug: 'workspace' }),
      environment({
        id: 'env-private',
        name: 'Private GPU',
        slug: 'private-gpu',
        is_public: false,
      }),
    ],
    updates: [] as Array<{ planId: string; data: Record<string, unknown> }>,
  }

  await page.addInitScript((user) => {
    localStorage.setItem('nukelab-token', 'isolated-browser-token')
    localStorage.setItem('nukelab-auth', JSON.stringify({ state: { user }, version: 0 }))
  }, admin)

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api/, '')

    if (path === '/users/me/profile') return route.fulfill({ json: admin })
    if (path === '/plans/' && request.method() === 'GET') {
      return route.fulfill({
        json: {
          success: true,
          data: {
            items: state.plans,
            total: state.plans.length,
            page: 1,
            limit: 100,
            pages: 1,
          },
        },
      })
    }
    if (path === '/environments/' && request.method() === 'GET') {
      return route.fulfill({
        json: {
          success: true,
          data: {
            items: state.environments,
            total: state.environments.length,
            page: 1,
            limit: 100,
            pages: 1,
          },
        },
      })
    }
    if (path.startsWith('/plans/') && request.method() === 'PUT') {
      const planId = path.split('/').pop()!
      const data = request.postDataJSON() as Record<string, unknown>
      state.updates.push({ planId, data })
      state.plans = state.plans.map((item) => (item.id === planId ? { ...item, ...data } : item))
      const updated = state.plans.find((item) => item.id === planId)
      return route.fulfill({ json: { success: true, data: updated } })
    }
    if (path === '/notifications/unread-count') return route.fulfill({ json: { unread_count: 0 } })
    if (path === '/notifications/') {
      return route.fulfill({
        json: { notifications: [], unread_count: 0, total: 0, page: 1, page_size: 20 },
      })
    }

    return route.fulfill({ json: {} })
  })

  return state
}

test('ready setup groups user-visible catalog and publishes a private plan', async ({ page }) => {
  const state = await mockSetup(page)

  await page.goto('/admin/setup')
  await expect(
    page.getByRole('heading', { name: 'NukeLab is ready for first launches' })
  ).toBeVisible()
  await expect(page.getByText('2 of 2 prerequisites')).toBeVisible()
  await expect(page.getByText('User-visible environments', { exact: true })).toBeVisible()
  await expect(page.getByText('Workspace', { exact: true })).toBeVisible()
  await expect(page.getByText('User-visible plans', { exact: true })).toBeVisible()
  await expect(page.getByText('XLarge', { exact: true })).toBeVisible()
  await expect(page.getByText('Needs attention', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: /Launch test server/ })).toHaveAttribute(
    'href',
    '/servers?deploy=true'
  )

  const attentionRow = page
    .locator('div')
    .filter({ has: page.getByText('XLarge', { exact: true }) })
    .filter({ has: page.getByRole('button', { name: 'Make available to users' }) })
    .last()
  await attentionRow.getByRole('button', { name: 'Make available to users' }).click()

  await expect(page.getByText('Needs attention', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Make available to users' })).toHaveCount(0)
  expect(state.updates).toEqual([
    { planId: 'plan-xlarge', data: { visible_to_roles: ['user'], is_active: true } },
  ])
})

test('incomplete setup points to the first blocking catalog task', async ({ page }) => {
  await mockSetup(page, { plans: [], environments: [] })

  await page.goto('/admin/setup')
  await expect(page.getByRole('heading', { name: 'Finish setting up NukeLab' })).toBeVisible()
  await expect(page.getByText('0 of 2 prerequisites')).toBeVisible()
  await expect(page.getByText('No public environment', { exact: true })).toBeVisible()
  await expect(page.getByText('No plan available to users', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('No environments exist yet', { exact: true })).toBeVisible()
  await expect(page.getByText('No plans exist yet', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: /Publish an environment/ })).toHaveAttribute(
    'href',
    '/admin/environments'
  )
})
