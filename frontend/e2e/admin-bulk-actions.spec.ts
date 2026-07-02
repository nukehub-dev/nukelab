import { test, expect } from '@playwright/test'
import { loginAsAdmin, ADMIN_USERNAME, ADMIN_PASSWORD } from './helpers/auth'
import {
  apiLogin,
  getOrCreateTestEnvironment,
  getPlanId,
  createServer,
  listServers,
  deleteServer,
} from './helpers/api'

test.describe('Admin bulk server actions', () => {
  let serverId: string
  let serverName: string

  test.beforeAll(async ({ request }) => {
    const { access_token } = await apiLogin(request, ADMIN_USERNAME, ADMIN_PASSWORD)
    const envId = await getOrCreateTestEnvironment(request, access_token)
    const planId = await getPlanId(request, access_token)
    serverName = `e2e-bulk-${Date.now()}`
    const server = await createServer(request, access_token, {
      name: serverName,
      plan_id: planId,
      environment_id: envId,
    })
    serverId = server.id
  })

  test.afterAll(async ({ request }) => {
    const { access_token } = await apiLogin(request, ADMIN_USERNAME, ADMIN_PASSWORD)
    const servers = await listServers(request, access_token)
    const testServers = servers.filter((s) => s.name.startsWith('e2e-bulk-'))
    await Promise.all(testServers.map((s) => deleteServer(request, access_token, s.id)))
  })

  test('admin can select, stop, and delete a server in bulk', async ({ page }) => {
    await loginAsAdmin(page)

    await page.goto('/admin/servers')
    await expect(page.getByText('Server Management')).toBeVisible()

    // DataTable defaults to mobile card view; switch to list/table view.
    const viewToggle = page.locator('button').filter({ hasText: /List|Cards/ })
    const currentLabel = await viewToggle.textContent()
    if (currentLabel?.includes('List')) {
      await viewToggle.click()
    }

    const row = page.getByTestId(`table-row-${serverId}`)
    await expect(row).toBeVisible({ timeout: 15000 })

    await page.getByTestId(`select-server-${serverId}`).click()

    const statusText = (await row.textContent()) || ''
    if (statusText.toLowerCase().includes('running')) {
      await page.getByTestId('bulk-action-stop').click()
      await expect(row).toContainText('stopped', { timeout: 60000 })
      await page.getByTestId(`select-server-${serverId}`).click()
    }

    await page.getByTestId('bulk-action-delete').click()

    await expect(page.getByTestId('confirm-dialog-confirm')).toBeVisible()
    await page.getByTestId('confirm-dialog-confirm').click()

    // Wait for the bulk action toast and list refresh.
    await expect(page.getByText(/Bulk action completed/).first()).toBeVisible({ timeout: 30000 })
    // The server list is cached; refresh to get consistent state before asserting removal.
    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.getByText(serverName).locator('visible=true')).toHaveCount(0, {
      timeout: 15000,
    })
  })
})
