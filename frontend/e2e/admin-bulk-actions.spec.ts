import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'
import {
  adminLogin,
  createServer,
  createTestEnvironment,
  deactivateEnvironment,
  deleteServer,
  getPlanBySlug,
} from './helpers/api'
import { E2E_RUNTIME_IMAGE, uniqueName } from './helpers/runtime'

test.describe('Admin bulk server actions', () => {
  let serverId: string | undefined
  let serverName: string
  let environmentId: string | undefined

  test.beforeAll(async ({ request }) => {
    const { access_token } = await adminLogin(request)
    const environment = await createTestEnvironment(request, access_token, {
      prefix: 'e2e-bulk-env',
      image: E2E_RUNTIME_IMAGE,
    })
    environmentId = environment.id
    const plan = await getPlanBySlug(request, access_token, 'small')
    serverName = uniqueName('e2e-bulk')
    const server = await createServer(request, access_token, {
      name: serverName,
      plan_id: plan.id,
      environment_id: environment.id,
    })
    serverId = server.id
  })

  test.afterAll(async ({ request }) => {
    const { access_token } = await adminLogin(request)
    try {
      if (serverId) await deleteServer(request, access_token, serverId)
    } finally {
      if (environmentId) await deactivateEnvironment(request, access_token, environmentId)
    }
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
      await expect(row).toContainText(/stopped/i, { timeout: 60000 })
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
