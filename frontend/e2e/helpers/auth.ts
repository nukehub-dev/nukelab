import type { Page } from '@playwright/test';

export const ADMIN_USERNAME = process.env.TEST_ADMIN_USERNAME || 'admin';
export const ADMIN_PASSWORD = process.env.TEST_ADMIN_PASSWORD || 'admin123';

export async function loginAsAdmin(page: Page) {
  await page.goto('/login');
  const username = page.getByTestId('login-username').locator('visible=true');
  const password = page.getByTestId('login-password').locator('visible=true');
  const submit = page.getByTestId('login-submit').locator('visible=true');
  await username.fill(ADMIN_USERNAME);
  await password.fill(ADMIN_PASSWORD);
  await submit.click();
  await page.waitForURL('/', { timeout: 10000 });
  // Wait for the current user to be fetched so permissions are available.
  await page.getByRole('heading', { name: 'Dashboard' }).waitFor({ timeout: 10000 });
}

export async function logout(page: Page) {
  await page.evaluate(() => {
    localStorage.removeItem('nukelab-token');
    localStorage.removeItem('nukelab-refresh');
    localStorage.removeItem('nukelab-auth');
  });
}
