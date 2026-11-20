import { test, expect } from '@playwright/test'
import {
  adminLogin,
  apiFetch,
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
  E2E_RUNTIME_IMAGE,
  EXTERNAL_SERVER,
  uniqueName,
} from './helpers/runtime'

function trimTrailingSlash(path: string): string {
  return path.replace(/\/+$/, '')
}

test.describe('Direct server access', () => {
  test.describe.configure({ timeout: 240_000 })

  test.skip(
    !EXTERNAL_SERVER,
    'Gateway access needs a single-origin stack; set E2E_EXTERNAL_SERVER=1 (and BASE_URL).'
  )

  let token: string | undefined
  let environmentId: string | undefined
  let volumeId: string | undefined
  let serverId: string | undefined
  let serverPath: string | undefined

  test.beforeAll(async ({ request }) => {
    if (!EXTERNAL_SERVER) return

    token = (await adminLogin(request)).access_token
    const environment = await createTestEnvironment(request, token, {
      prefix: 'e2e-direct-server-env',
      image: E2E_RUNTIME_IMAGE,
    })
    environmentId = environment.id
    const volume = await createVolume(request, token, {
      display_name: uniqueName('e2e direct server data'),
      max_size_bytes: 1024 ** 3,
    })
    volumeId = volume.id
    const plan = await getPlanBySlug(request, token, 'small')
    const serverName = uniqueName('e2e-direct-srv')
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
    serverPath = running.external_url || `${BASE_URL}/user/${ADMIN_USERNAME}/${serverName}`
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

  test('protected fixture page loads after the SPA token flow', async ({ page }) => {
    if (!serverPath) throw new Error('server fixture was not created')
    const accessToken = token
    if (!accessToken) throw new Error('admin token was not acquired')

    // Without the server access-token cookie, an HTML request must be redirected
    // back through the SPA gateway instead of exposing protected content.
    // Use the trailing-slash form: Traefik's bare-prefix redirect runs first.
    const protectedUrl = `${trimTrailingSlash(serverPath)}/`
    const unauthenticated = await apiFetch(protectedUrl, {
      redirect: 'manual',
      headers: { Accept: 'text/html' },
    })
    expect(unauthenticated.status).toBe(302)
    expect(unauthenticated.headers.get('location') ?? '').toContain('next=')

    // Inject the SPA token so main.tsx runs the gateway flow, requests a
    // short-lived server token, and navigates back to the protected page.
    await page.addInitScript((authToken: string) => {
      localStorage.setItem('nukelab-token', authToken)
    }, accessToken)

    const expected = new URL(serverPath)
    await page.goto(serverPath)

    await expect(
      page,
      'the SPA should return to the protected server URL after acquiring a token'
    ).toHaveURL(
      (url) =>
        url.origin === expected.origin &&
        trimTrailingSlash(url.pathname) === trimTrailingSlash(expected.pathname),
      { timeout: 60_000 }
    )

    // The SPA shell and its gateway screen must be gone; the server container
    // now serves the protected fixture page (or the configured dev runtime).
    await expect(page.locator('#root')).toHaveCount(0)
    await expect(page.locator('body')).toBeVisible()
    await expect(page.locator('body')).not.toBeEmpty()

    // When the disposable fixture image is selected, assert its identity marker
    // instead of relying on a runtime-specific page title.
    if (E2E_RUNTIME_IMAGE.includes('e2e-runtime')) {
      await expect(page.locator('[data-nukelab-fixture="runtime"]')).toBeVisible()
    }

    const protectedResponse = await page.request.get(page.url())
    expect(protectedResponse.status()).toBe(200)
    expect(protectedResponse.headers()['content-type'] ?? '').toContain('text/html')
  })
})
