// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { test, expect, type Page } from '@playwright/test'
import type { ServerQueueEntry } from '../src/types/server-queue'

const ids = {
  owner: '5f584904-6a94-4602-8144-66f215924270',
  plan: 'd6d2e4b3-4796-4335-9247-8ab76ce8e378',
  environment: '74e90887-4ee9-4f6f-a0d5-02c004477ea6',
  queue: '88136537-bd44-4522-8796-897d21d66a75',
}

const owner = {
  id: ids.owner,
  username: 'researcher',
  email: 'researcher@example.test',
  display_name: 'Researcher',
  avatar_url: '',
  role: 'user',
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
  cost_per_hour: 1,
  category: 'cpu',
  max_servers_per_user: 5,
  cooldown_seconds: 0,
  is_active: true,
  is_public: true,
  visible_to_roles: [],
  priority: 0,
  created_at: '2026-11-15T12:00:00',
}
const environment = {
  id: ids.environment,
  name: 'Approved runtime',
  slug: 'approved',
  image: 'approved:latest',
  is_active: true,
  is_public: true,
  created_at: '2026-11-15T12:00:00',
}

function pending(): ServerQueueEntry {
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
      name: 'preserved-simulation',
      plan_id: ids.plan,
      environment_id: ids.environment,
      resources: { cpu: 2, memory_mib: 4096, disk_mib: 20480, gpu_count: 0 },
    },
  }
}

async function mockQueue(
  page: Page,
  options: {
    available?: boolean
    existing?: boolean
    cancelRace?: boolean
    immediate?: boolean
    duplicate?: boolean
    readOnly?: boolean
  } = {}
) {
  const state = {
    entry: options.existing ? pending() : (null as ServerQueueEntry | null),
    submitted: null as Record<string, unknown> | null,
    createCount: 0,
    queueReads: 0,
    servers: [] as Record<string, unknown>[],
  }
  const currentOwner = { ...owner, role: options.readOnly ? 'guest' : 'user' }
  await page.addInitScript((owner) => {
    localStorage.setItem('nukelab-token', 'isolated-browser-token')
    localStorage.setItem('nukelab-auth', JSON.stringify({ state: { user: owner }, version: 0 }))
  }, currentOwner)
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace(/^\/api/, '')
    const fulfill = (json: unknown, status = 200) => route.fulfill({ status, json })
    if (path === '/users/me/profile') return fulfill(currentOwner)
    if (path === '/health') return fulfill({ status: 'healthy' })
    if (path === '/plans/')
      return fulfill({
        success: true,
        data: { items: [plan], total: 1, page: 1, limit: 100, pages: 1 },
      })
    if (path === '/environments/')
      return fulfill({
        success: true,
        data: { items: [environment], total: 1, page: 1, limit: 100, pages: 1 },
      })
    if (path === '/volumes/') return fulfill({ volumes: [] })
    if (path === '/notifications/unread-count') return fulfill({ unread_count: 0 })
    if (path === '/notifications/')
      return fulfill({ notifications: [], unread_count: 0, total: 0, page: 1, page_size: 20 })
    if (path === '/server-queue/capabilities')
      return options.available === false
        ? fulfill({ detail: 'Not found' }, 404)
        : fulfill({ enabled: true })
    if (path === '/servers/' && request.method() === 'POST') {
      state.submitted = request.postDataJSON()
      state.createCount++
      if (options.duplicate)
        return fulfill({ detail: { code: 'request_already_exists', queue_id: ids.queue } }, 409)
      if (options.immediate) {
        const server = {
          id: 'actual-server',
          name: state.submitted!.name,
          status: 'running',
          created_at: '2026-11-15T12:00:00',
          username: owner.username,
          user_id: owner.id,
          plan_id: ids.plan,
          environment_id: ids.environment,
        }
        state.servers = [server]
        return fulfill(server)
      }
      state.entry = pending()
      return fulfill(
        {
          queued: true,
          queue_id: ids.queue,
          queue_position: 1,
          message: state.entry.message,
          request: state.entry.request,
        },
        202
      )
    }
    if (path === '/servers/') return fulfill({ servers: state.servers })
    if (path === '/server-queue') {
      state.queueReads++
      return fulfill({
        items: state.entry ? [state.entry] : [],
        total: state.entry ? 1 : 0,
        page: 1,
        page_size: 25,
      })
    }
    if (path === `/server-queue/${ids.queue}/cancel`) {
      if (options.cancelRace) {
        state.entry = {
          ...state.entry!,
          status: 'starting',
          can_cancel: false,
          position: null,
          message: 'Launch in progress.',
        }
        return fulfill({ detail: { code: 'launch_in_progress' } }, 409)
      }
      state.entry = {
        ...state.entry!,
        status: 'cancelled',
        can_cancel: false,
        position: null,
        message: 'Request cancelled.',
      }
      return fulfill(state.entry)
    }
    if (path === `/server-queue/${ids.queue}`) return fulfill(state.entry)
    return fulfill({})
  })
  return state
}

async function deploy(page: Page) {
  await page.goto('/servers')
  await page.getByRole('button', { name: 'Deploy', exact: true }).first().click()
  await page.getByTestId('deploy-server-name').fill('preserved-simulation')
  await page.getByTestId('deploy-server-plan-trigger').click()
  await page.getByTestId(`deploy-server-plan-${ids.plan}`).click()
  await page.getByTestId('deploy-server-environment-trigger').click()
  await page.getByTestId(`deploy-server-environment-${ids.environment}`).click()
  await page.getByTestId('deploy-server-submit').click()
}

test('accepted waiting configuration survives refresh and pending cancellation', async ({
  page,
}) => {
  const state = await mockQueue(page)
  await deploy(page)
  await expect(page).toHaveURL(/tab=queue/)
  await expect(page.getByRole('heading', { name: 'Server request', exact: true })).toBeVisible()
  await expect(
    page.getByRole('dialog').getByText('preserved-simulation', { exact: true })
  ).toBeVisible()
  expect(state.submitted).toMatchObject({
    name: 'preserved-simulation',
    plan_id: ids.plan,
    environment_id: ids.environment,
    volume_mounts: [
      {
        volume_id: '',
        mount_path: '/home/researcher',
        mode: 'read_write',
        max_size_bytes: 10 * 1024 ** 3,
      },
    ],
  })
  expect(state.createCount).toBe(1)
  await page.reload()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('preserved-simulation', { exact: true })).toBeVisible()
  await expect(dialog.getByText('Priority position 1')).toBeVisible()
  await dialog.getByRole('button', { name: 'Cancel request', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Cancel waiting request?' })).toBeVisible()
  await page.getByRole('button', { name: 'Cancel request', exact: true }).last().click()
  await expect(dialog.getByText('Cancelled', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Cancel request', exact: true })).toHaveCount(0)
})

test('cancel claim race refreshes starting state without removing request', async ({ page }) => {
  await mockQueue(page, { existing: true, cancelRace: true })
  await page.goto(`/servers?tab=queue&request=${ids.queue}`)
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Cancel request', exact: true }).click()
  await page.getByRole('button', { name: 'Cancel request', exact: true }).last().click()
  await expect(dialog.getByText('Starting', { exact: true })).toBeVisible()
  await expect(page.getByText('Launch already in progress', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Cancel request', exact: true })).toHaveCount(0)
})

test('missing capability hides queue controls and does not query owner records', async ({
  page,
}) => {
  const state = await mockQueue(page, { available: false })
  await page.goto('/servers')
  await expect(page.getByRole('heading', { name: 'My Servers' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Server sections' })).toHaveCount(0)
  expect(state.queueReads).toBe(0)
})

test('immediate deployment remains a server and does not navigate to waiting', async ({ page }) => {
  const state = await mockQueue(page, { immediate: true })
  await deploy(page)
  await expect(page.getByRole('heading', { name: 'Deploy New Server' })).toHaveCount(0)
  await expect(page).not.toHaveURL(/tab=queue/)
  await expect(
    page.getByText('preserved-simulation', { exact: true }).filter({ visible: true }).first()
  ).toBeVisible()
  expect(state.createCount).toBe(1)
})

test('duplicate request preserves the deployment form and opens the existing request', async ({
  page,
}) => {
  const state = await mockQueue(page, { existing: true, duplicate: true })
  await deploy(page)
  await expect(page.getByTestId('deploy-server-name')).toHaveValue('preserved-simulation')
  await expect(page.getByTestId('deploy-server-plan')).toContainText(plan.name)
  await expect(page.getByTestId('deploy-server-environment')).toContainText(environment.name)
  await page.getByRole('button', { name: 'View existing request', exact: true }).click()
  await expect(
    page
      .getByRole('dialog', { name: 'Server request' })
      .getByText('preserved-simulation', { exact: true })
  ).toBeVisible()
  expect(state.createCount).toBe(1)
})

test('read-only user can inspect a waiting request without cancellation controls', async ({
  page,
}) => {
  await mockQueue(page, { existing: true, readOnly: true })
  await page.goto(`/servers?tab=queue&request=${ids.queue}`)
  const dialog = page.getByRole('dialog', { name: 'Server request' })
  await expect(dialog.getByText('preserved-simulation', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel request', exact: true })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
})

test('@vite-only late deployment acceptance cannot publish an old-owner request after account change', async ({
  page,
}) => {
  await mockQueue(page)
  let release!: () => void
  let entered!: () => void
  const submitted = new Promise<void>((resolve) => {
    entered = resolve
  })
  const responseGate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/servers/', async (route) => {
    if (route.request().method() === 'POST') {
      entered()
      await responseGate
    }
    await route.fallback()
  })
  await deploy(page)
  await submitted
  await page.evaluate(async () => {
    const modulePath = '/src/stores/auth-store.ts'
    const { useAuthStore } = await import(modulePath)
    useAuthStore.getState().setUser({
      ...useAuthStore.getState().user,
      id: 'a7a609c0-6603-44cb-80a2-c51dc7312e81',
      username: 'another-researcher',
    })
  })
  release()
  await expect(page.getByTestId('deploy-server-submit')).toHaveText('Deploy')
  await expect(page).not.toHaveURL(/tab=queue/)
  await expect(page.getByText('Request queued', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Waiting server requests' })).toHaveCount(0)
})

test('completed request links the actual server identity after a server rename', async ({
  page,
}) => {
  const state = await mockQueue(page, { existing: true })
  state.entry = {
    ...pending(),
    status: 'started',
    can_cancel: false,
    position: null,
    server_id: 'actual-result-server',
    started_at: '2026-11-15T12:01:00',
    message: 'Server started.',
  }
  state.servers = [
    {
      id: 'actual-result-server',
      name: 'renamed-simulation',
      username: owner.username,
      user_id: owner.id,
      status: 'running',
      created_at: '2026-11-15T12:01:00',
    },
  ]
  await page.goto(`/servers?tab=queue&request=${ids.queue}`)
  const dialog = page.getByRole('dialog', { name: 'Server request' })
  await expect(dialog.getByRole('link', { name: 'View server' })).toHaveAttribute(
    'href',
    '/user/researcher/renamed-simulation'
  )
  await expect(dialog.getByRole('button', { name: 'Cancel request', exact: true })).toHaveCount(0)
  await expect(dialog.getByText('preserved-simulation', { exact: true })).toBeVisible()
})
