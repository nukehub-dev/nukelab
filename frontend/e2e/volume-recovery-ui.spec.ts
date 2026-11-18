// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { test, expect, type Page } from '@playwright/test'
import type { VolumeBackup, VolumeRestore } from '../src/types/volume-backup'

const ids = {
  owner: 'c5766856-9063-4a3c-878c-04b024cbeacf',
  volume: '060a31e7-2d49-4674-b0f5-357351de8ac5',
  backup: 'd9f0d63c-2152-48e3-ab8d-31c71904b3ca',
  restore: 'a7d5cfa9-c4a2-468d-b025-7d7d9821ae66',
  destination: '04095c4d-8b3d-4997-8a26-451a45ff32cd',
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
function backup(): VolumeBackup {
  return {
    id: ids.backup,
    source_volume_id: ids.volume,
    source_display_name: 'Private data',
    status: 'completed',
    reason_code: null,
    message: 'Backup verified.',
    description: null,
    created_at: '2026-11-17T12:00:00',
    completed_at: '2026-11-17T12:01:00',
    expires_at: '2026-12-17T12:00:00',
    compressed_bytes: 200,
    logical_bytes: 1024,
    member_count: 2,
    can_restore: true,
    can_delete: true,
  }
}
async function fixture(
  page: Page,
  options: {
    supported?: boolean
    disabled?: boolean
    busy?: boolean
    readonly?: boolean
    sourceDeleted?: boolean
    deleteConflict?: boolean
    volumeStatus?: string
    delayedCreate?: boolean
  } = {}
) {
  const actor = { ...owner, ...(options.readonly ? { permissions: ['volumes:read_own'] } : {}) }
  const state = {
    backups: [backup()],
    restores: [] as VolumeRestore[],
    creates: [] as Record<string, unknown>[],
    restoreRequests: [] as Record<string, unknown>[],
    deletes: 0,
    reads: 0,
    stops: 0,
    release: () => {},
  }
  if (options.sourceDeleted) state.backups[0].source_volume_id = null
  const hold = new Promise<void>((resolve) => {
    state.release = resolve
  })
  await page.addInitScript((actor) => {
    localStorage.setItem('nukelab-token', 'recovery-browser-token')
    localStorage.setItem('nukelab-auth', JSON.stringify({ state: { user: actor }, version: 0 }))
  }, actor)
  await page.route('**/api/**', async (route) => {
    const req = route.request()
    const path = new URL(req.url()).pathname.replace(/^\/api/, '')
    const done = (json: unknown, status = 200) => route.fulfill({ json, status })
    if (path === '/users/me/profile') return done(actor)
    if (path === '/health') return done({ status: 'healthy' })
    if (path === '/volumes/')
      return done({
        volumes: options.sourceDeleted
          ? []
          : [
              {
                id: ids.volume,
                name: 'private-data',
                display_name: 'Private data',
                owner_id: ids.owner,
                visibility: 'private',
                size_bytes: 1024,
                max_size_bytes: 1024 ** 3,
                status: options.volumeStatus || 'active',
                server_count: options.volumeStatus ? 0 : 1,
                created_at: '2026-11-17T12:00:00',
                updated_at: '2026-11-17T12:00:00',
              },
            ],
      })
    if (path === '/volume-backups/capabilities')
      return options.supported === false
        ? done({ detail: 'Not found' }, 404)
        : done({
            enabled: !options.disabled,
            reason_code: options.disabled ? 'backup_storage_unavailable' : null,
            message: options.disabled
              ? 'Backup storage is unavailable.'
              : 'Private offline recovery is available.',
          })
    if (path === `/volumes/${ids.volume}/backup-eligibility`)
      return done({
        eligible: !options.busy,
        reason_code: options.busy ? 'volume_busy' : null,
        message: options.busy
          ? 'This volume is currently in use.'
          : 'This private volume is offline.',
      })
    if (path === `/volumes/${ids.volume}/backups` && req.method() === 'POST') {
      state.creates.push(req.postDataJSON())
      if (options.delayedCreate) await hold
      const pending = {
        ...backup(),
        id: '373501eb-5e7f-491c-9638-1668ac017719',
        status: 'pending' as const,
        message: 'Preparing backup.',
        can_restore: false,
        can_delete: false,
      }
      state.backups.unshift(pending)
      return done(pending, 202)
    }
    if (path === '/volume-backups') {
      state.reads++
      return done({ items: state.backups, total: state.backups.length, page: 1, page_size: 10 })
    }
    if (path === '/volume-restores')
      return done({ items: state.restores, total: state.restores.length, page: 1, page_size: 10 })
    if (path === `/volume-backups/${ids.backup}/restore`) {
      const body = req.postDataJSON()
      state.restoreRequests.push(body)
      const pending: VolumeRestore = {
        id: ids.restore,
        backup_id: ids.backup,
        status: 'pending',
        reason_code: null,
        message: 'Checking backup and preparing destination.',
        destination_volume_id: ids.destination,
        destination_display_name: String(body.display_name),
        created_at: '2026-11-17T13:00:00',
        completed_at: null,
      }
      state.restores.unshift(pending)
      return done(pending, 202)
    }
    if (path === `/volume-backups/${ids.backup}` && req.method() === 'DELETE') {
      state.deletes++
      if (options.deleteConflict) {
        state.backups[0].can_delete = false
        return done({ detail: { code: 'backup_pinned' } }, 409)
      }
      state.backups[0] = {
        ...state.backups[0],
        status: 'deleting',
        can_restore: false,
        can_delete: false,
        message: 'Deletion is in progress.',
      }
      return done(state.backups[0], 202)
    }
    if (path.endsWith('/stop')) {
      state.stops++
      return done({})
    }
    if (path === '/notifications/unread-count') return done({ unread_count: 0 })
    if (path === '/notifications/')
      return done({ notifications: [], unread_count: 0, total: 0, page: 1, page_size: 20 })
    return done({})
  })
  return state
}

async function openHistory(page: Page) {
  await page.goto('/volumes')
  await page.getByRole('button', { name: 'Backup history', exact: true }).click()
}

test('unconfigured recovery keeps history readable and actions unavailable', async ({ page }) => {
  await fixture(page, { disabled: true })
  await openHistory(page)
  await expect(page.getByText('Backup storage is unavailable.', { exact: false })).toBeVisible()
  await expect(page.getByTestId(`backup-${ids.backup}`)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Restore to new volume' })).toHaveCount(0)
  await expect(page.getByTestId('create-backup')).toHaveCount(0)
})

test('unsupported deployment exposes no recovery controls or metadata requests', async ({
  page,
}) => {
  const state = await fixture(page, { supported: false })
  await page.goto('/volumes')
  await expect(page.getByRole('heading', { name: 'Private data', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Backup history', exact: true })).toHaveCount(0)
  expect(state.reads).toBe(0)
})

test('private offline backup creates a durable request without stopping workloads', async ({
  page,
}) => {
  const state = await fixture(page)
  await page.goto('/volumes')
  await page.getByRole('button', { name: 'Backups for Private data' }).click()
  await expect(page.getByTestId('create-backup')).toBeEnabled()
  await page.getByLabel('Description (optional)').fill('Before experiment')
  await page.getByTestId('create-backup').click()
  await expect(page.getByText('Preparing backup.', { exact: true })).toBeVisible()
  expect(state.creates).toHaveLength(1)
  expect(state.creates[0]).toMatchObject({ description: 'Before experiment' })
  expect(String(state.creates[0].request_id)).toMatch(/^[0-9a-f-]{36}$/)
  expect(state.stops).toBe(0)
})

test('busy private volume cannot request backup and never offers automatic stop', async ({
  page,
}) => {
  const state = await fixture(page, { busy: true })
  await page.goto('/volumes')
  await page.getByRole('button', { name: 'Backups for Private data' }).click()
  await expect(page.getByText('This volume is currently in use.')).toBeVisible()
  await expect(page.getByTestId('create-backup')).toBeDisabled()
  expect(state.creates).toHaveLength(0)
  expect(state.stops).toBe(0)
})

test('deleted-source backup restores only into a new private destination and survives refresh', async ({
  page,
}) => {
  const state = await fixture(page, { sourceDeleted: true })
  await openHistory(page)
  await expect(page.getByText('Source volume deleted', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: 'Restore to new volume' }).click()
  await page.getByTestId('restore-volume-name').fill('Recovered experiment')
  await page.getByTestId('restore-volume-size').fill('1')
  await page.getByTestId('restore-backup-submit').click()
  await expect(page.getByTestId(`restore-${ids.restore}`)).toBeVisible()
  await expect(page.getByRole('link', { name: 'Use in a server' })).toHaveCount(0)
  expect(state.restoreRequests[0]).toMatchObject({
    display_name: 'Recovered experiment',
    max_size_bytes: 1073741824,
  })
  await page.reload()
  await page.getByRole('button', { name: 'Backup history', exact: true }).click()
  await expect(page.getByTestId(`restore-${ids.restore}`)).toBeVisible()
  state.restores[0] = {
    ...state.restores[0],
    status: 'completed',
    message: 'Integrity verified.',
    completed_at: '2026-11-17T13:01:00',
  }
  await page.getByRole('button', { name: 'Refresh backup history' }).click()
  await expect(page.getByText('Recovered experiment is ready.', { exact: false })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Use in a server' })).toBeVisible()
})

test('restore-pinned deletion conflict retains the backup and refreshes its actions', async ({
  page,
}) => {
  const state = await fixture(page, { deleteConflict: true })
  await openHistory(page)
  await page.getByRole('button', { name: 'Delete backup', exact: true }).click()
  await page.getByRole('button', { name: 'Delete backup', exact: true }).last().click()
  await expect(page.getByText('This backup is being restored', { exact: false })).toBeVisible()
  await expect(page.getByTestId(`backup-${ids.backup}`)).toBeVisible()
  expect(state.deletes).toBe(1)
})

test('read-only owner can inspect history but not create restore or deletion requests', async ({
  page,
}) => {
  await fixture(page, { readonly: true })
  await openHistory(page)
  await expect(page.getByTestId(`backup-${ids.backup}`)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Restore to new volume' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Delete backup', exact: true })).toHaveCount(0)
})

test('late backup acceptance cannot toast or populate another owner history', async ({ page }) => {
  const state = await fixture(page, { delayedCreate: true })
  await page.goto('/volumes')
  await page.getByRole('button', { name: 'Backups for Private data' }).click()
  await expect(page.getByTestId('create-backup')).toBeEnabled()
  await page.getByTestId('create-backup').click()
  await expect.poll(() => state.creates.length).toBe(1)
  await page.evaluate(async () => {
    // @ts-expect-error Browser imports the running application module.
    const { useAuthStore } = await import('/src/stores/auth-store.ts')
    useAuthStore.getState().setUser({
      ...useAuthStore.getState().user,
      id: 'd312111a-b198-4f31-97ce-7df0347585bf',
      username: 'another',
    })
  })
  state.release()
  await expect(page.getByText('Backup requested', { exact: true })).toHaveCount(0)
})

for (const status of ['restoring', 'restore_failed']) {
  test(`incomplete ${status} volume cannot be browsed or edited`, async ({ page }) => {
    await fixture(page, { volumeStatus: status })
    await page.goto('/volumes')
    await expect(
      page.getByText(
        status === 'restoring'
          ? 'Restoring · unavailable until verified'
          : 'Restore failed · delete this incomplete volume to clean up'
      )
    ).toBeVisible()
    await expect(page.getByRole('button', { name: 'Browse volume', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Edit volume', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Delete volume', exact: true })).toHaveCount(
      status === 'restore_failed' ? 1 : 0
    )
  })
}
