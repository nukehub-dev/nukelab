// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import type { Page } from '@playwright/test'
import { ADMIN_PASSWORD, ADMIN_USERNAME } from './runtime'

export { ADMIN_PASSWORD, ADMIN_USERNAME }

/** Log in through the real login form and wait for the authenticated shell. */
export async function loginAs(
  page: Page,
  username: string = ADMIN_USERNAME,
  password: string = ADMIN_PASSWORD
): Promise<void> {
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

export async function loginAsAdmin(page: Page): Promise<void> {
  await loginAs(page, ADMIN_USERNAME, ADMIN_PASSWORD)
}

/**
 * Clear browser-side session state without assuming the page is already on an
 * app origin. Server-token cookies are HttpOnly and intentionally untouched.
 */
export async function logout(page: Page): Promise<void> {
  if (!/^https?:\/\//i.test(page.url())) {
    await page.goto('/login')
  }
  await page
    .evaluate(() => {
      localStorage.removeItem('nukelab-token')
      localStorage.removeItem('nukelab-refresh')
      localStorage.removeItem('nukelab-auth')
    })
    .catch(() => {
      // Navigation can race with the evaluate call; callers re-navigate to the
      // route under test, which will redirect unauthenticated users to login.
    })
}
