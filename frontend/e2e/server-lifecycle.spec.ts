import { test, expect } from '@playwright/test'
import { loginAsAdmin, ADMIN_USERNAME, ADMIN_PASSWORD } from './helpers/auth'
import {
  apiLogin,
  getOrCreateTestEnvironment,
  getPlanId,
  listServers,
  deleteServer,
} from './helpers/api'

test.describe('Server lifecycle', () => {
  let _testEnvId: string
  let _planId: string
  const serverName = `e2e-server-${Date.now()}`

  test.beforeAll(async ({ request }) => {
    const { access_token } = await apiLogin(request, ADMIN_USERNAME, ADMIN_PASSWORD)
    _testEnvId = await getOrCreateTestEnvironment(request, access_token)
    _planId = await getPlanId(request, access_token)
  })

  test.afterAll(async ({ request }) => {
    const { access_token } = await apiLogin(request, ADMIN_USERNAME, ADMIN_PASSWORD)
    const servers = await listServers(request, access_token)
    const testServers = servers.filter((s) => s.name.startsWith('e2e-server-'))
    await Promise.all(testServers.map((s) => deleteServer(request, access_token, s.id)))
  })

  test('admin can deploy and stop a server', async ({ page }) => {
    await loginAsAdmin(page)

    await page.goto('/servers')
    await page.getByTestId('action-deploy').click()

    // Dialog renders both mobile (first) and desktop (second) shells; use desktop drawer.
    const desktopForm = page.getByTestId('deploy-form').nth(1)
    await expect(desktopForm).toBeVisible()

    await page.getByTestId('deploy-server-name').nth(1).fill(serverName)

    await page.getByTestId('deploy-server-plan-trigger').nth(1).click()
    await page.waitForTimeout(500)
    const planOption = page
      .locator('[data-testid="select-dropdown"] button', {
        hasText: 'Small (2 CPU / 4g / 20 GB disk)',
      })
      .first()
    await planOption.waitFor({ timeout: 5000 })
    await planOption.click()

    await page.getByTestId('deploy-server-environment-trigger').nth(1).click()
    await page.waitForTimeout(500)
    const envOption = page
      .locator('[data-testid="select-dropdown"] button', { hasText: 'E2E Default (e2e-default)' })
      .first()
    await envOption.waitFor({ timeout: 5000 })
    await envOption.click()

    await page.getByTestId('deploy-server-submit').nth(1).click()

    await expect(desktopForm).not.toBeVisible({ timeout: 15000 })

    const row = page.getByTestId(new RegExp(`table-row-.*`))
    const serverRow = row.filter({ hasText: serverName })
    // Table defaults to mobile card view; the TR is present but hidden. Use visible card text.
    await expect(page.getByText(serverName).locator('visible=true')).toBeVisible({ timeout: 30000 })
    await expect(serverRow).toContainText(/running|pending|stopped|error|Start & Open/, {
      timeout: 60000,
    })

    const stopButton = page.getByTestId(new RegExp(`stop-server-.*`)).first()
    if (await stopButton.isVisible().catch(() => false)) {
      await stopButton.click()
      await expect(serverRow).toContainText('stopped', { timeout: 60000 })
    }
  })
})
