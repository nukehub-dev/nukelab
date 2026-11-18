import { test, expect } from '@playwright/test'
import {
  adminLogin,
  createServer,
  createTestEnvironment,
  createVolume,
  deactivateEnvironment,
  deleteServer,
  deleteVolumeWhenDetached,
  getPlanBySlug,
  startServer,
  waitForServerStatus,
} from './helpers/api'
import {
  ADMIN_USERNAME,
  BASE_URL,
  E2E_WORKSPACE_IMAGE,
  EXTERNAL_SERVER,
  uniqueName,
} from './helpers/runtime'

function trimTrailingSlash(path: string): string {
  return path.replace(/\/+$/, '')
}

test.describe('Direct workspace access', () => {
  test.describe.configure({ timeout: 240_000 })

  test.skip(
    !EXTERNAL_SERVER,
    'Gateway access needs a single-origin stack; set E2E_EXTERNAL_SERVER=1 (and BASE_URL).'
  )

  let token: string | undefined
  let environmentId: string | undefined
  let volumeId: string | undefined
  let serverId: string | undefined
  let serverUrl: string | undefined

  test.beforeAll(async ({ request }) => {
    if (!EXTERNAL_SERVER) return

    token = (await adminLogin(request)).access_token
    const environment = await createTestEnvironment(request, token, {
      prefix: 'e2e-workspace-env',
      image: E2E_WORKSPACE_IMAGE,
      category: 'workspace',
    })
    environmentId = environment.id
    const volume = await createVolume(request, token, {
      display_name: uniqueName('e2e workspace home'),
      max_size_bytes: 2 * 1024 ** 3,
    })
    volumeId = volume.id
    const plan = await getPlanBySlug(request, token, 'small')
    const serverName = uniqueName('e2e-ws')
    const created = await createServer(request, token, {
      name: serverName,
      plan_id: plan.id,
      environment_id: environment.id,
      volume_id: volume.id,
      volume_mode: 'read_write',
    })
    serverId = created.id
    if (created.status === 'stopped') {
      await startServer(request, token, created.id)
    }
    const running = await waitForServerStatus(request, token, created.id, ['running'], {
      timeoutMs: 180_000,
    })
    serverUrl = running.external_url || `${BASE_URL}/user/${ADMIN_USERNAME}/${serverName}`
  })

  test.afterAll(async ({ request }) => {
    if (!token) return
    try {
      if (serverId) await deleteServer(request, token, serverId)
    } finally {
      try {
        if (volumeId) await deleteVolumeWhenDetached(request, token, volumeId)
      } finally {
        if (environmentId) await deactivateEnvironment(request, token, environmentId)
      }
    }
  })

  test('direct workspace URL access loads the IDE and assets @workspace', async ({ page }) => {
    if (!serverUrl) throw new Error('workspace server was not created')
    const accessToken = token
    if (!accessToken) throw new Error('admin token was not acquired')

    await page.addInitScript((authToken: string) => {
      localStorage.setItem('nukelab-token', authToken)
    }, accessToken)

    page.on('console', (msg) => console.log('PAGE CONSOLE:', msg.text()))
    page.on('pageerror', (err) => console.error('PAGE ERROR:', err.message))

    // Direct access without a server token goes through the SPA gateway flow,
    // which obtains a server token and loads the workspace IDE.
    await page.goto(serverUrl)

    // Traefik redirects the bare prefix to a trailing slash so relative IDE
    // assets resolve under the strip prefix.
    const expected = new URL(serverUrl)
    await expect(page).toHaveURL(
      (url) =>
        url.origin === expected.origin &&
        trimTrailingSlash(url.pathname) === trimTrailingSlash(expected.pathname) &&
        url.pathname.endsWith('/'),
      { timeout: 60_000 }
    )

    // The workspace IDE should render the NukeIDE shell.
    await expect(page.locator('body')).toContainText('NukeIDE', { timeout: 30_000 })

    // Core IDE assets should have loaded (no 404s for bundle / logo).
    const base = page.url().endsWith('/') ? page.url() : `${page.url()}/`
    const bundleRequest = await page.request.get(new URL('bundle.js', base).toString())
    const logoRequest = await page.request.get(new URL('logo.svg', base).toString())
    expect(bundleRequest.status()).toBe(200)
    expect(logoRequest.status()).toBe(200)
  })
})
