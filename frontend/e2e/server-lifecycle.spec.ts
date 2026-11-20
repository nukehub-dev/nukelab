import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'
import {
  adminLogin,
  createTestEnvironment,
  deactivateEnvironment,
  deleteServerEventually,
  getPlanBySlug,
  listServers,
  waitForServerStatus,
} from './helpers/api'
import { E2E_RUNTIME_IMAGE, uniqueName } from './helpers/runtime'

test.describe('Server lifecycle', () => {
  test.describe.configure({ timeout: 180_000 })

  const serverName = uniqueName('e2e-server')
  let environmentId: string | undefined
  let planId: string | undefined

  test.beforeAll(async ({ request }) => {
    const { access_token } = await adminLogin(request)
    const environment = await createTestEnvironment(request, access_token, {
      prefix: 'e2e-lifecycle-env',
      image: E2E_RUNTIME_IMAGE,
    })
    environmentId = environment.id
    planId = (await getPlanBySlug(request, access_token, 'small')).id
  })

  test.afterAll(async ({ request }) => {
    const { access_token } = await adminLogin(request)
    try {
      const servers = await listServers(request, access_token)
      const created = servers.filter((server) => server.name === serverName)
      for (const server of created) {
        await deleteServerEventually(request, access_token, server.id)
      }
    } finally {
      if (environmentId) await deactivateEnvironment(request, access_token, environmentId)
    }
  })

  test('admin can deploy and stop a server', async ({ page, request }) => {
    await loginAsAdmin(page)

    await page.goto('/servers')
    await page.getByTestId('action-deploy').click()

    // Responsive dialogs mount a single form shell on the active viewport.
    const desktopForm = page.getByTestId('deploy-form').first()
    await expect(desktopForm).toBeVisible()

    await page.getByTestId('deploy-server-name').first().fill(serverName)

    await page.getByTestId('deploy-server-plan-trigger').first().click()
    const planOption = page
      .getByTestId(`deploy-server-plan-${planId}`)
      .locator('visible=true')
      .first()
    await expect(planOption).toBeVisible({ timeout: 5000 })
    await planOption.click()

    await page.getByTestId('deploy-server-environment-trigger').first().click()
    const environmentOption = page
      .getByTestId(`deploy-server-environment-${environmentId}`)
      .locator('visible=true')
      .first()
    await expect(environmentOption).toBeVisible({ timeout: 5000 })
    await environmentOption.click()

    await page.getByTestId('deploy-server-submit').first().click()

    await expect(desktopForm).not.toBeVisible({ timeout: 60000 })

    const row = page.getByTestId(new RegExp(`table-row-.*`))
    const serverRow = row.filter({ hasText: serverName })

    const { access_token } = await adminLogin(request)
    const created = (await listServers(request, access_token)).find(
      (server) => server.name === serverName
    )
    if (!created) throw new Error(`Server ${serverName} was not created`)
    await waitForServerStatus(request, access_token, created.id, ['running'], {
      timeoutMs: 120_000,
    })

    // Table defaults to mobile card view; the TR is present but hidden. Use visible card text.
    await expect(page.getByText(serverName).locator('visible=true')).toBeVisible({ timeout: 30000 })
    await expect(serverRow).toContainText(/running/i, { timeout: 60_000 })

    const stopButton = page.getByTestId(`stop-server-${created.id}`).locator('visible=true').first()
    await expect(stopButton).toBeVisible({ timeout: 30_000 })
    await stopButton.click()
    await expect(serverRow).toContainText(/stopped/i, { timeout: 60_000 })
  })
})
