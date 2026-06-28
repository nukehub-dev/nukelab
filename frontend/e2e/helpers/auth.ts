import type { Page } from '@playwright/test'

export const ADMIN_USERNAME = process.env.TEST_ADMIN_USERNAME || 'admin'
export const ADMIN_PASSWORD = process.env.TEST_ADMIN_PASSWORD || 'admin123'

export async function loginAs(page: Page, username: string, password: string) {
  await page.goto('/login')
  const usernameInput = page.getByTestId('login-username').locator('visible=true')
  const passwordInput = page.getByTestId('login-password').locator('visible=true')
  const submit = page.getByTestId('login-submit').locator('visible=true')
  await usernameInput.fill(username)
  await passwordInput.fill(password)
  await submit.click()
  await page.waitForURL('/', { timeout: 10000 })
  // Wait for the current user to be fetched so permissions are available.
  await page.getByRole('heading', { name: 'Dashboard' }).waitFor({ timeout: 10000 })
}

export async function loginAsAdmin(page: Page) {
  await loginAs(page, ADMIN_USERNAME, ADMIN_PASSWORD)
}

export async function logout(page: Page) {
  await page.evaluate(() => {
    localStorage.removeItem('nukelab-token')
    localStorage.removeItem('nukelab-refresh')
    localStorage.removeItem('nukelab-auth')
  })
}
