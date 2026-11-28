// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { test, expect, type Page } from '@playwright/test'
import type { Environment, Plan, Server } from '../src/types/api'
import type { Volume } from '../src/hooks/use-volumes'
import type { ServerQueueEntry } from '../src/types/server-queue'

const ids = {
  owner: '0a5f4a0e-3f1f-4d0b-9f5f-0d7d4a1c2b10',
  planSmall: '1a5f4a0e-3f1f-4d0b-9f5f-0d7d4a1c2b11',
  planMedium: '2a5f4a0e-3f1f-4d0b-9f5f-0d7d4a1c2b12',
  environment: '3a5f4a0e-3f1f-4d0b-9f5f-0d7d4a1c2b13',
  environmentOther: '4a5f4a0e-3f1f-4d0b-9f5f-0d7d4a1c2b14',
  volume: '5a5f4a0e-3f1f-4d0b-9f5f-0d7d4a1c2b15',
  queue: '6a5f4a0e-3f1f-4d0b-9f5f-0d7d4a1c2b16',
}

type CatalogPlan = Plan & { is_starter?: boolean }
type CatalogEnvironment = Environment & { is_starter?: boolean }

function makePlan(overrides: Partial<CatalogPlan> = {}): CatalogPlan {
  return {
    id: ids.planSmall,
    name: 'Small',
    slug: 'small',
    category: 'cpu',
    cpu_limit: 2,
    memory_limit: '4g',
    disk_limit: '20g',
    gpu_limit: 0,
    max_servers_per_user: 3,
    cost_per_hour: 3,
    cooldown_seconds: 0,
    is_public: true,
    visible_to_roles: ['user'],
    allow_servers: true,
    allow_batch_jobs: true,
    is_active: true,
    priority: 0,
    created_at: '2026-11-15T12:00:00',
    ...overrides,
  }
}

function makeEnvironment(overrides: Partial<CatalogEnvironment> = {}): CatalogEnvironment {
  return {
    id: ids.environment,
    name: 'Workspace',
    slug: 'workspace',
    image: 'workspace:latest',
    is_active: true,
    is_public: true,
    created_at: '2026-11-15T12:00:00',
    ...overrides,
  }
}

function makeVolume(): Volume {
  return {
    id: ids.volume,
    name: 'analysis-data',
    display_name: 'analysis-data',
    owner_id: ids.owner,
    visibility: 'private',
    size_bytes: 2 * 1024 ** 3,
    max_size_bytes: 10 * 1024 ** 3,
    status: 'active',
    server_count: 0,
    created_at: '2026-11-15T12:00:00',
    updated_at: '2026-11-15T12:00:00',
  }
}

function makeQueueEntry(
  name: string,
  plan: CatalogPlan,
  environment: CatalogEnvironment
): ServerQueueEntry {
  return {
    id: ids.queue,
    status: 'pending',
    position: 1,
    reason_code: 'capacity_wait',
    message: 'Waiting for available capacity.',
    requested_at: '2026-11-15T12:00:00',
    expires_at: '2026-11-15T13:00:00',
    started_at: null,
    server_id: null,
    can_cancel: true,
    request: {
      name,
      plan_id: plan.id,
      environment_id: environment.id,
      resources: {
        cpu: plan.cpu_limit,
        memory_mib: 4096,
        disk_mib: 20480,
        gpu_count: plan.gpu_limit,
      },
    },
  }
}

interface GuidedLaunchOptions {
  plans?: CatalogPlan[]
  environments?: CatalogEnvironment[]
  volumes?: Volume[]
  savedPlan?: string
  savedEnvironment?: string
  queued?: boolean
  failPlans?: boolean
  catalogDelayMs?: number
  existingServers?: Server[]
}

async function mockGuidedLaunch(page: Page, options: GuidedLaunchOptions = {}) {
  const state = {
    plans: options.plans ?? [makePlan()],
    environments: options.environments ?? [makeEnvironment()],
    volumes: options.volumes ?? [makeVolume()],
    servers: options.existingServers ?? [],
    queueEntry: null as ServerQueueEntry | null,
    submitted: null as Record<string, unknown> | null,
    createCount: 0,
  }
  const owner = {
    id: ids.owner,
    username: 'newresearcher',
    email: 'newresearcher@example.test',
    first_name: 'New',
    last_name: 'Researcher',
    display_name: 'New Researcher',
    avatar_url: '',
    role: 'user',
    permissions: [
      'servers:read_own',
      'servers:write_own',
      'volumes:read_own',
      'volumes:write_own',
      'workspaces:read_own',
    ],
    nuke_balance: 100,
    daily_allowance: 10,
    profile: {},
    preferences: {
      timezone: 'UTC',
      ...(options.savedPlan !== undefined ? { default_plan: options.savedPlan } : {}),
      ...(options.savedEnvironment !== undefined
        ? { default_environment: options.savedEnvironment }
        : {}),
    },
    profile_visibility: 'private',
    is_active: true,
    is_verified: true,
    login_count: 1,
    created_at: '2026-11-15T12:00:00',
  }

  await page.addInitScript((user) => {
    localStorage.setItem('nukelab-token', 'isolated-browser-token')
    localStorage.setItem('nukelab-auth', JSON.stringify({ state: { user }, version: 0 }))
  }, owner)

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^\/api/, '')
    const fulfill = (json: unknown, status = 200) => route.fulfill({ status, json })

    if (path === '/users/me/profile') return fulfill(owner)
    if (path === '/health') return fulfill({ status: 'healthy' })
    if (path === '/dashboard/') {
      return fulfill({
        my_servers: {
          total: state.servers.length,
          running: state.servers.filter((server) => server.status === 'running').length,
          stopped: 0,
          pending: 0,
        },
        my_nukes: {
          balance: 100,
          daily_allowance: 10,
          hourly_cost: 0,
          estimated_hours_left: 10,
        },
        recent_activity: [],
      })
    }
    if (path === '/plans/' && request.method() === 'GET') {
      if (options.failPlans) return fulfill({ detail: 'Catalog unavailable' }, 500)
      if (options.catalogDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.catalogDelayMs))
      }
      return fulfill({
        success: true,
        data: {
          items: state.plans,
          total: state.plans.length,
          page: 1,
          limit: 100,
          pages: 1,
        },
      })
    }
    if (path === '/environments/' && request.method() === 'GET') {
      if (options.catalogDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.catalogDelayMs))
      }
      return fulfill({
        success: true,
        data: {
          items: state.environments,
          total: state.environments.length,
          page: 1,
          limit: 100,
          pages: 1,
        },
      })
    }
    if (path === '/volumes/' && request.method() === 'GET') {
      return fulfill({ volumes: state.volumes })
    }
    if (path === '/servers/' && request.method() === 'POST') {
      state.submitted = request.postDataJSON() as Record<string, unknown>
      state.createCount++
      const submitted = state.submitted
      const plan = state.plans.find((item) => item.id === submitted.plan_id) ?? state.plans[0]
      const environment =
        state.environments.find((item) => item.id === submitted.environment_id) ??
        state.environments[0]
      const name = String(submitted.name)
      if (options.queued) {
        state.queueEntry = makeQueueEntry(name, plan, environment)
        return fulfill(
          {
            queued: true,
            queue_id: ids.queue,
            queue_position: 1,
            message: state.queueEntry.message,
            request: state.queueEntry.request,
          },
          202
        )
      }
      const server: Server = {
        id: '1c5f4a0e-3f1f-4d0b-9f5f-0d7d4a1c2b17',
        name,
        status: 'running',
        external_url: `https://servers.example.test/user/${owner.username}/${name}`,
        username: owner.username,
        user_id: owner.id,
        plan_id: plan.id,
        environment_id: environment.id,
        created_at: '2026-11-15T12:00:00',
      }
      state.servers = [server]
      return fulfill(server)
    }
    if (path === '/servers/' && request.method() === 'GET') {
      return fulfill({ servers: state.servers })
    }
    if (path === '/servers/provenance-capabilities') return fulfill({ enabled: false })
    if (path === '/server-queue/capabilities') return fulfill({ enabled: true })
    if (path === '/server-queue' && request.method() === 'GET') {
      const items = state.queueEntry ? [state.queueEntry] : []
      return fulfill({
        items,
        total: items.length,
        page: 1,
        page_size: 25,
      })
    }
    if (path === `/server-queue/${ids.queue}`) return fulfill(state.queueEntry)
    if (path === '/notifications/unread-count') return fulfill({ unread_count: 0 })
    if (path === '/notifications/') {
      return fulfill({ notifications: [], unread_count: 0, total: 0, page: 1, page_size: 20 })
    }
    return fulfill({})
  })

  return state
}

async function openDashboardDialog(page: Page) {
  await page.goto('/')
  await expect(
    page.getByRole('heading', { name: 'Create your first simulation server' })
  ).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('link', { name: /Review your first server/ })).toHaveAttribute(
    'href',
    '/servers?deploy=true'
  )
  await page.goto('/servers?deploy=true')
  await expect(page.getByRole('heading', { name: 'Deploy New Server' })).toBeVisible({
    timeout: 15_000,
  })
}

test('unambiguous catalog is preselected on the dashboard, reviewed and launched', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const state = await mockGuidedLaunch(page)

  await page.goto('/')
  await expect(
    page.getByRole('heading', { name: 'Create your first simulation server' })
  ).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('Small · 2 CPU · 4 GB RAM · 20 GB disk')).toBeVisible()
  await expect(page.getByText('Workspace', { exact: true })).toBeVisible()
  await expect(page.getByText('3 NUKE/hour while running')).toBeVisible()
  await expect(page.getByText('Private volume, created or reused when you launch')).toBeVisible()

  await expect(page.getByRole('link', { name: /Review your first server/ })).toHaveAttribute(
    'href',
    '/servers?deploy=true'
  )
  await page.goto('/servers?deploy=true')
  const dialogHeading = page.getByRole('heading', { name: 'Deploy New Server' })
  await expect(dialogHeading).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('deploy-server-plan')).toContainText('Small')
  await expect(page.getByTestId('deploy-server-environment')).toContainText('Workspace')

  const review = page.getByTestId('deploy-review')
  await expect(review).toContainText('2 vCPU')
  await expect(review).toContainText('4 GB')
  await expect(review).toContainText('20 GB')
  await expect(review).toContainText('3 NUKE/hour while running')
  await expect(review).toContainText('Create a new private volume')
  await expect(review).toContainText('/home/newresearcher')
  await expect(review).toContainText('Final eligibility and capacity are confirmed when you submit')

  await page.getByTestId('deploy-volume-0-trigger').click()
  await page.getByTestId(`deploy-volume-0-${ids.volume}`).click()
  await expect(review).toContainText('Reuse analysis-data')
  await expect(review).toContainText('10 GB capacity, 2 GB used')

  await page.getByTestId('deploy-server-name').fill('guided-workspace')
  await page.getByTestId('deploy-server-submit').click()

  await expect(dialogHeading).toHaveCount(0)
  await expect(
    page.getByText('guided-workspace', { exact: true }).filter({ visible: true }).first()
  ).toBeVisible()
  await expect(
    page
      .getByRole('button', { name: /^Open( Server)?$/ })
      .filter({ visible: true })
      .first()
  ).toBeVisible()
  expect(state.submitted).toMatchObject({
    name: 'guided-workspace',
    plan_id: ids.planSmall,
    environment_id: ids.environment,
    volume_mounts: [
      {
        volume_id: ids.volume,
        mount_path: '/home/newresearcher',
        mode: 'read_write',
      },
    ],
  })
})

test('job-only plans are hidden from server deployment', async ({ page }) => {
  const jobOnly = makePlan({
    id: ids.planMedium,
    name: 'Jobs Only',
    slug: 'jobs-only',
    allow_servers: false,
    allow_batch_jobs: true,
  })
  await mockGuidedLaunch(page, { plans: [makePlan(), jobOnly] })
  await openDashboardDialog(page)

  await page.getByTestId('deploy-server-plan-trigger').click()
  await expect(page.getByTestId(`deploy-server-plan-${ids.planMedium}`)).toHaveCount(0)
  await expect(page.getByTestId(`deploy-server-plan-${ids.planSmall}`)).toBeVisible()
})

test('long plan names wrap in the plan menu without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const longPlan = makePlan({
    id: ids.planSmall,
    name: 'Jobs E2E Capacity Filler '.repeat(3).trim(),
    slug: 'long-plan',
  })
  await mockGuidedLaunch(page, { plans: [longPlan] })
  await openDashboardDialog(page)

  await page.getByTestId('deploy-server-plan-trigger').click()
  const option = page.getByTestId(`deploy-server-plan-${ids.planSmall}`)
  await expect(option).toBeVisible()
  const overflow = await option.evaluate((element) => element.scrollWidth - element.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})

test('a marked starter is preselected and remains editable', async ({ page }) => {
  const starterPlan = makePlan({
    id: ids.planSmall,
    name: 'Starter',
    slug: 'starter',
    is_starter: true,
  })
  const otherPlan = makePlan({
    id: ids.planMedium,
    name: 'Medium',
    slug: 'medium',
    cpu_limit: 4,
    memory_limit: '8g',
    disk_limit: '50g',
    cost_per_hour: 5,
  })
  const starterEnvironment = makeEnvironment({ id: ids.environment, is_starter: true })
  const otherEnvironment = makeEnvironment({
    id: ids.environmentOther,
    name: 'Python 3.13',
    slug: 'python',
  })
  await mockGuidedLaunch(page, {
    plans: [starterPlan, otherPlan],
    environments: [starterEnvironment, otherEnvironment],
  })

  await openDashboardDialog(page)
  await expect(page.getByTestId('deploy-server-plan')).toContainText('Starter')
  await expect(page.getByTestId('deploy-server-environment')).toContainText('Workspace')

  await page.getByTestId('deploy-server-plan-trigger').click()
  await page.getByTestId(`deploy-server-plan-${ids.planMedium}`).click()
  await page.getByTestId('deploy-server-environment-trigger').click()
  await page.getByTestId(`deploy-server-environment-${ids.environmentOther}`).click()

  await expect(page.getByTestId('deploy-server-plan')).toContainText('Medium')
  await expect(page.getByTestId('deploy-server-environment')).toContainText('Python 3.13')
  const review = page.getByTestId('deploy-review')
  await expect(review).toContainText('4 vCPU')
  await expect(review).toContainText('8 GB')
  await expect(review).toContainText('50 GB')
  await expect(review).toContainText('5 NUKE/hour while running')
})

test('an ambiguous catalog asks for an explicit plan and environment', async ({ page }) => {
  const plans = [
    makePlan({ id: ids.planSmall, name: 'Small', slug: 'small' }),
    makePlan({
      id: ids.planMedium,
      name: 'Medium',
      slug: 'medium',
      cpu_limit: 4,
      memory_limit: '8g',
      disk_limit: '50g',
      cost_per_hour: 5,
    }),
  ]
  const environments = [
    makeEnvironment({ id: ids.environment, name: 'Workspace', slug: 'workspace' }),
    makeEnvironment({ id: ids.environmentOther, name: 'Python 3.13', slug: 'python' }),
  ]
  await mockGuidedLaunch(page, { plans, environments })

  await page.goto('/')
  await expect(page.getByText('2 eligible plans — choose one when you launch')).toBeVisible({
    timeout: 15_000,
  })
  await page.goto('/servers?deploy=true')
  await expect(page.getByRole('heading', { name: 'Deploy New Server' })).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByTestId('deploy-server-plan-trigger')).toContainText('Select a plan...')
  await expect(page.getByTestId('deploy-server-environment-trigger')).toContainText(
    'Select an environment...'
  )
  await page.getByTestId('deploy-server-name').fill('chosen-workspace')
  await expect(page.getByTestId('deploy-server-submit')).toBeDisabled()

  await page.getByTestId('deploy-server-plan-trigger').click()
  await page.getByTestId(`deploy-server-plan-${ids.planMedium}`).click()
  await page.getByTestId('deploy-server-environment-trigger').click()
  await page.getByTestId(`deploy-server-environment-${ids.environmentOther}`).click()

  await expect(page.getByTestId('deploy-server-submit')).toBeEnabled()
  await expect(page.getByTestId('deploy-review')).toContainText('4 vCPU')
  await expect(page.getByTestId('deploy-review')).toContainText('50 GB')
})

test('a stale saved plan is reported and requires an explicit current choice', async ({ page }) => {
  const plans = [
    makePlan({ id: ids.planSmall, name: 'Small', slug: 'small' }),
    makePlan({ id: ids.planMedium, name: 'Medium', slug: 'medium' }),
  ]
  await mockGuidedLaunch(page, {
    plans,
    savedPlan: 'retired-plan',
    savedEnvironment: 'workspace',
  })

  await page.goto('/')
  await expect(page.getByText(/Your saved default plan is no longer available/)).toBeVisible()
  await page.goto('/servers?deploy=true')
  await expect(page.getByRole('heading', { name: 'Deploy New Server' })).toBeVisible({
    timeout: 15_000,
  })

  await expect(page.getByTestId('deploy-saved-default-unavailable')).toContainText(
    'Your saved default plan is no longer available'
  )
  await expect(page.getByTestId('deploy-server-plan-trigger')).toContainText('Select a plan...')
  await expect(page.getByTestId('deploy-server-environment')).toContainText('Workspace')
  await page.getByTestId('deploy-server-name').fill('recover-workspace')
  await expect(page.getByTestId('deploy-server-submit')).toBeDisabled()

  await page.getByTestId('deploy-server-plan-trigger').click()
  await page.getByTestId(`deploy-server-plan-${ids.planSmall}`).click()
  await expect(page.getByTestId('deploy-server-submit')).toBeEnabled()
})

test('missing catalog keeps the prerequisite state and disables launch', async ({ page }) => {
  await mockGuidedLaunch(page, { plans: [], environments: [] })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'NukeLab setup is not complete' })).toBeVisible()
  await expect(page.getByText('No active plans are available.')).toHaveCount(0)
  await expect(page.getByRole('link', { name: /Review your first server/ })).toHaveCount(0)

  await page.goto('/servers?deploy=true')
  await expect(page.getByRole('heading', { name: 'Deploy New Server' })).toBeVisible()
  await expect(page.getByTestId('deploy-prerequisites')).toBeVisible()
  await expect(page.getByTestId('deploy-server-submit')).toBeDisabled()
})

test('catalog query failure is shown as an unavailable catalog, not missing setup', async ({
  page,
}) => {
  await mockGuidedLaunch(page, { failPlans: true })

  await page.goto('/')
  await expect(
    page.getByRole('heading', { name: 'Deployment catalog could not be loaded' })
  ).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('heading', { name: 'Finish setting up NukeLab' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /Open setup checklist/ })).toHaveCount(0)
})

test('queued acceptance navigates to the existing waiting request view', async ({ page }) => {
  const state = await mockGuidedLaunch(page, { queued: true })

  await openDashboardDialog(page)
  await page.getByTestId('deploy-server-name').fill('waiting-workspace')
  await page.getByTestId('deploy-server-submit').click()

  await expect(page).toHaveURL(new RegExp(`tab=queue&request=${ids.queue}`))
  const dialog = page.getByRole('dialog', { name: 'Server request' })
  await expect(dialog.getByText('waiting-workspace', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Waiting for available capacity.')).toBeVisible()
  expect(state.createCount).toBe(1)
  expect(state.submitted).toMatchObject({
    name: 'waiting-workspace',
    plan_id: ids.planSmall,
    environment_id: ids.environment,
  })
})

test('deploy deep link opens once before the catalog settles and strips the flag', async ({
  page,
}) => {
  await mockGuidedLaunch(page, { catalogDelayMs: 800 })

  await page.goto('/servers?deploy=true')
  await expect(page.getByRole('heading', { name: 'Deploy New Server' })).toBeVisible()
  await expect(page).not.toHaveURL(/deploy=true/)

  await expect(page.getByTestId('deploy-server-plan')).toContainText('Small')
  await expect(page.getByTestId('deploy-server-environment')).toContainText('Workspace')

  await page.keyboard.press('Escape')
  await expect(page.getByRole('heading', { name: 'Deploy New Server' })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'My Servers' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Deploy New Server' })).toHaveCount(0)
})

test('mobile launch keeps the review and primary action reachable', async ({ page }) => {
  await mockGuidedLaunch(page)

  for (const width of [390, 360]) {
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/servers?deploy=true')
    await expect(page.getByRole('heading', { name: 'Deploy New Server' })).toBeVisible({
      timeout: 15_000,
    })
    await expect(page.getByTestId('deploy-server-plan')).toContainText('Small')
    await page.getByTestId('deploy-server-name').fill(`mobile-${width}`)

    const submit = page.getByTestId('deploy-server-submit')
    await submit.scrollIntoViewIfNeeded()
    await expect(submit).toBeInViewport()
    await expect(submit).toBeEnabled()
    await expect(page.getByTestId('deploy-review')).toContainText('2 vCPU')

    const overflow = await page.evaluate(() => {
      const root = document.documentElement
      return root.scrollWidth - window.innerWidth
    })
    expect(overflow).toBeLessThanOrEqual(1)
  }
})
