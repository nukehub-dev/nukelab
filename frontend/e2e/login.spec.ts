import { test, expect } from '@playwright/test'
import { ADMIN_USERNAME, ADMIN_PASSWORD } from './helpers/auth'

test.describe('Login flow', () => {
  test('admin can log in with local credentials', async ({ page }) => {
    await page.goto('/login')

    await expect(page.getByTestId('login-username').locator('visible=true')).toBeVisible()
    await expect(page.getByTestId('login-password').locator('visible=true')).toBeVisible()

    await page.getByTestId('login-username').locator('visible=true').fill(ADMIN_USERNAME)
    await page.getByTestId('login-password').locator('visible=true').fill(ADMIN_PASSWORD)
    await page.getByTestId('login-submit').locator('visible=true').click()

    await page.waitForURL('/', { timeout: 10000 })
    await expect(page).toHaveURL('/')
  })

  test('shows error for invalid credentials', async ({ page }) => {
    await page.goto('/login')

    await page.getByTestId('login-username').locator('visible=true').fill('admin')
    await page.getByTestId('login-password').locator('visible=true').fill('wrong-password')
    await page.getByTestId('login-submit').locator('visible=true').click()

    await expect(
      page.getByText(/incorrect username or password|login failed/i).locator('visible=true')
    ).toBeVisible()
  })
})
