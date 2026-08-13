import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

// Uses the admin login (the only auth fixture available); admins hold credits:read_own,
// so the user-facing flow at /settings/credits works the same.
test.describe('Credit requests', () => {
  test('submit a request, see it listed as pending, then cancel it', async ({ page }) => {
    await loginAsAdmin(page)
    await page.goto('/settings/credits')

    const requestButton = page.getByTestId('request-credits-button')

    // Idempotency: cancel any open request left over from a previous run.
    if (await requestButton.isDisabled()) {
      await page.getByTestId('credit-request-cancel').first().click()
      await page.getByTestId('confirm-dialog-confirm').click()
      await expect(requestButton).toBeEnabled({ timeout: 10000 })
    }

    // Submit a new request
    await requestButton.click()
    await page.getByTestId('credit-request-amount').fill('100')
    await page.getByTestId('credit-request-reason').fill('E2E test credit request')
    await page.getByTestId('credit-request-submit').click()

    // It appears in "My Requests" as pending and blocks further requests
    await expect(page.getByText('Pending', { exact: true }).first()).toBeVisible({
      timeout: 10000,
    })
    await expect(requestButton).toBeDisabled()

    // Cancel it — the run leaves no open request behind
    await page.getByTestId('credit-request-cancel').first().click()
    await page.getByTestId('confirm-dialog-confirm').click()
    await expect(page.getByText('Cancelled', { exact: true }).first()).toBeVisible({
      timeout: 10000,
    })
    await expect(requestButton).toBeEnabled({ timeout: 10000 })
  })
})
