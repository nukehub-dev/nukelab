// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { test, expect, type Page } from '@playwright/test'
import type { EnvironmentManifest, ServerProvenance } from '../src/types/server-provenance'

const ids = {
  owner: '7b200e55-0589-4c32-9d0c-854df57512be',
  server: 'ea59bd9b-b36a-49ce-8f38-9ac12eeed4c2',
  launch: '8360357c-64b0-4ee3-9ab2-9201fb37727a',
  revision: 'c34bd6fa-702d-4202-a827-29ab8ad185db',
  plan: '096e57ab-90ad-4949-9ed1-733d609e8fb7',
  queue: '31f1016b-9e92-48ce-9e08-5bd1a12cd9f0',
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
const image = {
  requested_reference: 'approved:latest',
  local_id: 'sha256:' + 'a'.repeat(64),
  repository_digests: ['local/image@sha256:' + 'b'.repeat(64)],
  os: 'linux',
  architecture: 'amd64',
  registry_verified: false,
  verified_reference: null,
}
const manifest: EnvironmentManifest = {
  schema_version: 'nukelab.environment/v1',
  revision_id: ids.revision,
  revision_fingerprint: 'c'.repeat(64),
  template_label: 'Approved runtime',
  runtime: image,
  toolchain: null,
  toolchain_mounts: [],
  environment_variable_names: ['API_KEY'],
  environment_values: 'manual_input_required',
  resources: { cpu: 1, memory_mib: 1024, disk_mib: 2048, gpu_count: 0 },
  volume_requirements: [{ purpose: 'home', mount_path: '/home/old-name', mode: 'read_write' }],
  portability: 'local_only',
  limitations: [
    'Mutable volume data requires a separate verified backup.',
    'Local image artifacts must remain available on the original engine.',
  ],
}
const provenance: ServerProvenance = {
  state: 'recorded',
  launch_id: ids.launch,
  generation: 2,
  captured_at: '2026-11-15T12:00:00',
  manifest,
  actual_runtime: image,
  actual_toolchain: null,
  can_recreate: true,
  recreation_reason_code: null,
}
const plan = {
  id: ids.plan,
  name: 'Current approved plan',
  slug: 'current',
  cpu_limit: 1,
  memory_limit: '1g',
  disk_limit: '2g',
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
const server = {
  id: ids.server,
  user_id: ids.owner,
  username: owner.username,
  name: 'original-server',
  status: 'running',
  container_id: 'verified-runtime',
  plan_id: ids.plan,
  allocated_cpu: 1,
  allocated_memory: '1g',
  allocated_disk: '2g',
  created_at: '2026-11-15T12:00:00',
}

async function fixture(
  page: Page,
  options: {
    available?: boolean
    unrecorded?: boolean
    queued?: boolean
    denied?: boolean
    delayed?: boolean
    readonly?: boolean
    sharedVolume?: boolean
  } = {}
) {
  const actor = { ...owner, role: options.readonly ? 'guest' : 'user' }
  const state = {
    reads: 0,
    validations: 0,
    submissions: [] as Record<string, unknown>[],
    release: (() => {}) as () => void,
  }
  const hold = new Promise<void>((resolve) => {
    state.release = resolve
  })
  await page.addInitScript((actor) => {
    localStorage.setItem('nukelab-token', 'isolated-browser-token')
    localStorage.setItem('nukelab-auth', JSON.stringify({ state: { user: actor }, version: 0 }))
  }, actor)
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace(/^\/api/, '')
    const done = (json: unknown, status = 200) => route.fulfill({ json, status })
    if (path === '/users/me/profile') return done(actor)
    if (path === '/health') return done({ status: 'healthy' })
    if (path === '/servers/provenance-capabilities')
      return options.available === false
        ? done({ detail: 'Not found' }, 404)
        : done({ enabled: true })
    if (path === `/servers/${ids.server}/provenance`) {
      state.reads++
      return done(
        options.unrecorded
          ? {
              ...provenance,
              state: 'unrecorded',
              manifest: null,
              launch_id: null,
              generation: null,
              captured_at: null,
              actual_runtime: null,
              can_recreate: false,
              recreation_reason_code: 'unrecorded',
            }
          : provenance
      )
    }
    if (path === `/servers/${ids.server}/environment-manifest`) return done(manifest)
    if (path === '/servers/recreate/validate') {
      state.validations++
      if (options.denied) return done({ detail: { code: 'revision_unavailable' } }, 409)
      return done({
        manifest,
        environment_label: 'Current approved environment',
        volume_requirements: [
          { purpose: 'home', mount_path: '/home/researcher', mode: 'read_write' },
          ...(options.sharedVolume
            ? [{ purpose: 'data', mount_path: '/data', mode: 'read_only' }]
            : []),
        ],
      })
    }
    if (path === '/servers/recreate') {
      state.submissions.push(request.postDataJSON())
      if (options.delayed) await hold
      if (options.queued)
        return done(
          {
            queued: true,
            queue_id: ids.queue,
            queue_position: 1,
            message: 'Waiting for available capacity.',
            request: {
              name: 'recreated',
              plan_id: ids.plan,
              environment_id: ids.revision,
              resources: { cpu: 1, memory_mib: 1024, disk_mib: 2048, gpu_count: 0 },
            },
          },
          202
        )
      return done({ ...server, id: '8bb16274-df26-4df2-9b74-7ef660cb7de3', name: 'recreated' })
    }
    if (path === '/servers/') return done({ servers: [server] })
    if (path.startsWith('/schedules/servers/')) return done({ schedules: [] })
    if (path.includes('/metrics')) return done({ metrics: [], count: 0 })
    if (path === '/plans/')
      return done({
        success: true,
        data: { items: [plan], total: 1, page: 1, limit: 100, pages: 1 },
      })
    if (path === '/environments/')
      return done({ success: true, data: { items: [], total: 0, page: 1, limit: 100, pages: 0 } })
    if (path === '/volumes/')
      return done({
        volumes: options.sharedVolume
          ? [
              {
                id: '816438e9-f6c5-4975-aee7-e0b17af3cfd9',
                owner_id: '3c5868d0-ddc7-4c8d-a8f2-7db4aaad8643',
                name: 'public-reference',
                display_name: 'Public reference data',
                visibility: 'public',
                status: 'active',
                size_bytes: 1024,
                max_size_bytes: 1024 ** 3,
                server_count: 1,
              },
            ]
          : [],
      })
    if (path === '/notifications/unread-count') return done({ unread_count: 0 })
    if (path === '/notifications/')
      return done({ notifications: [], unread_count: 0, total: 0, page: 1, page_size: 20 })
    if (path === '/server-queue/capabilities') return done({ enabled: true })
    if (path === '/server-queue') return done({ items: [], total: 0, page: 1, page_size: 25 })
    if (path === `/server-queue/${ids.queue}`)
      return done({
        id: ids.queue,
        status: 'pending',
        position: 1,
        can_cancel: true,
        message: 'Waiting for available capacity.',
        request: {
          name: 'recreated',
          plan_id: ids.plan,
          environment_id: ids.revision,
          resources: { cpu: 1, memory_mib: 1024, disk_mib: 2048, gpu_count: 0 },
        },
        requested_at: '2026-11-15T12:00:00',
        expires_at: null,
        started_at: null,
        server_id: null,
        reason_code: 'capacity_wait',
      })
    return done({})
  })
  return state
}

async function configure(page: Page) {
  await page.getByTestId('recreate-name').fill('recreated')
  await page.getByTestId('recreate-plan-trigger').click()
  await page.getByTestId(`recreate-plan-${ids.plan}`).click()
  await page.getByTestId('recreate-volume-0-trigger').click()
  await page.getByRole('button', { name: 'Create a fresh private volume', exact: true }).click()
  await page.getByTestId('recreate-volume-size-0').fill('1')
}

test('last verified identity remains local-only and export excludes credential values', async ({
  page,
}) => {
  await fixture(page)
  await page.goto(`/servers/${ids.server}`)
  await expect(page.getByText('Last verified launch', { exact: false })).toBeVisible()
  await expect(page.getByText('Local-only environment', { exact: true })).toBeVisible()
  await expect(page.getByText('Local identity, registry not verified')).toBeVisible()
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export environment', exact: true }).click()
  const download = await downloaded
  expect(download.suggestedFilename()).toBe(`nukelab-environment-${ids.launch}.json`)
  const stream = await download.createReadStream()
  let contents = ''
  for await (const chunk of stream!) contents += chunk.toString()
  expect(JSON.parse(contents)).toEqual(manifest)
  expect(contents).not.toContain('private-token-value')
})

test('unrecorded history is explicit and does not offer export or recreation', async ({ page }) => {
  await fixture(page, { unrecorded: true })
  await page.goto(`/servers/${ids.server}`)
  await expect(
    page.getByRole('heading', { name: 'Environment history not recorded' })
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'Export environment', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Recreate environment', exact: true })).toHaveCount(
    0
  )
})

test('unsupported deployment hides feature controls and never reads provenance', async ({
  page,
}) => {
  const state = await fixture(page, { available: false })
  await page.goto(`/servers/${ids.server}`)
  await expect(page.getByRole('heading', { name: 'original-server', exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Environment details' })).toHaveCount(0)
  await page.goto('/servers')
  await expect(page.getByRole('button', { name: 'Import environment', exact: true })).toHaveCount(0)
  expect(state.reads).toBe(0)
})

test('source recreation requires deliberate volumes and handles queued acceptance', async ({
  page,
}) => {
  const state = await fixture(page, { queued: true })
  await page.goto(`/servers/${ids.server}`)
  await page.getByRole('button', { name: 'Recreate environment', exact: true }).click()
  await expect(page.getByTestId('recreate-volume-0-trigger')).toHaveText(
    'Choose a volume deliberately'
  )
  await configure(page)
  await page.getByTestId('recreate-submit').click()
  await expect(page).toHaveURL(/tab=queue/)
  expect(state.submissions).toEqual([
    {
      source_launch_id: ids.launch,
      name: 'recreated',
      plan_id: ids.plan,
      volume_mounts: [
        {
          volume_id: '',
          mount_path: '/home/researcher',
          mode: 'read_write',
          max_size_bytes: 1073741824,
        },
      ],
    },
  ])
})

test('import validates before accepting current plan and explicit data bindings', async ({
  page,
}) => {
  const state = await fixture(page, { queued: true })
  await page.goto('/servers')
  await page.getByRole('button', { name: 'Import environment', exact: true }).click()
  await page.getByTestId('environment-import-json').fill(JSON.stringify(manifest))
  await page.getByRole('button', { name: 'Validate environment', exact: true }).click()
  await expect(page.getByText('Current approved environment', { exact: true })).toBeVisible()
  await configure(page)
  await page.getByTestId('recreate-submit').click()
  await expect(page).toHaveURL(/tab=queue/)
  expect(state.validations).toBe(1)
  expect(state.submissions[0]).toMatchObject({
    manifest,
    volume_mounts: [{ volume_id: '', mount_path: '/home/researcher', mode: 'read_write' }],
  })
})

test('unavailable revision preserves imported JSON and explains the rejection', async ({
  page,
}) => {
  await fixture(page, { denied: true })
  await page.goto('/servers')
  await page.getByRole('button', { name: 'Import environment', exact: true }).click()
  await page.getByTestId('environment-import-json').fill(JSON.stringify(manifest))
  await page.getByRole('button', { name: 'Validate environment', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('unavailable or has been revoked')
  await expect(page.getByTestId('environment-import-json')).toHaveValue(JSON.stringify(manifest))
  await expect(page.getByTestId('recreate-submit')).toBeDisabled()
})

test('unsupported manifest versions are rejected without sending a validation request', async ({
  page,
}) => {
  const state = await fixture(page)
  await page.goto('/servers')
  await page.getByRole('button', { name: 'Import environment', exact: true }).click()
  await page
    .getByTestId('environment-import-json')
    .fill('{"schema_version":"nukelab.environment/v2"}')
  await page.getByRole('button', { name: 'Validate environment', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('not supported')
  expect(state.validations).toBe(0)
})

test('read-only owner can inspect and export but cannot recreate or import', async ({ page }) => {
  await fixture(page, { readonly: true })
  await page.goto(`/servers/${ids.server}`)
  await expect(page.getByRole('button', { name: 'Export environment', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Recreate environment', exact: true })).toHaveCount(
    0
  )
  await page.goto('/servers')
  await expect(page.getByRole('button', { name: 'Import environment', exact: true })).toHaveCount(0)
})

test('late recreation acceptance cannot navigate or toast for another account', async ({
  page,
}) => {
  const state = await fixture(page, { delayed: true, queued: true })
  await page.goto(`/servers/${ids.server}`)
  await page.getByRole('button', { name: 'Recreate environment', exact: true }).click()
  await configure(page)
  await page.getByTestId('recreate-submit').click()
  await expect.poll(() => state.submissions.length).toBe(1)
  await page.evaluate(async () => {
    const modulePath = '/src/stores/auth-store.ts'
    const { useAuthStore } = await import(modulePath)
    useAuthStore.getState().setUser({
      ...useAuthStore.getState().user,
      id: '32a928ae-779d-48c8-a013-1daae6868132',
      username: 'another-researcher',
    })
  })
  state.release()
  await expect(
    page.getByRole('heading', { name: 'Recreate environment', exact: true })
  ).toHaveCount(0)
  await expect(page).not.toHaveURL(/tab=queue/)
  await expect(page.getByText('Request queued', { exact: true })).toHaveCount(0)
})

test('recreation can explicitly bind an accessible shared read-only dataset', async ({ page }) => {
  const state = await fixture(page, { queued: true, sharedVolume: true })
  await page.goto(`/servers/${ids.server}`)
  await page.getByRole('button', { name: 'Recreate environment', exact: true }).click()
  await configure(page)
  await page.getByTestId('recreate-volume-1-trigger').click()
  await page.getByRole('button', { name: 'Public reference data', exact: false }).click()
  await page.getByTestId('recreate-submit').click()
  await expect(page).toHaveURL(/tab=queue/)
  expect(state.submissions[0]).toMatchObject({
    volume_mounts: [
      { volume_id: '', mount_path: '/home/researcher', mode: 'read_write' },
      { volume_id: '816438e9-f6c5-4975-aee7-e0b17af3cfd9', mount_path: '/data', mode: 'read_only' },
    ],
  })
})
