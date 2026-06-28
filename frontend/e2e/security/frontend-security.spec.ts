import { test, expect } from '@playwright/test'
import { loginAsAdmin, loginAs, logout } from '../helpers/auth'
import { apiLogin, createUser, deleteUser } from '../helpers/api'

const XSS_PAYLOAD = '<script>window.__e2eXssExecuted = true</script>'
const XSS_ORGANIZATION = '<img src=x onerror=window.__e2eXssExecuted=true>'

test.describe('Frontend security', () => {
  test('redirects unauthenticated users to login', async ({ page }) => {
    await page.goto('/login')
    await logout(page)
    await page.goto('/servers')
    await expect(page).toHaveURL('/login')
  })

  test('non-admin users cannot access admin routes', async ({ page, request }) => {
    const { access_token } = await apiLogin(
      request,
      process.env.TEST_ADMIN_USERNAME || 'admin',
      process.env.TEST_ADMIN_PASSWORD || 'admin123'
    )

    const timestamp = Date.now()
    const user = await createUser(request, access_token, {
      username: `e2e-user-${timestamp}`,
      email: `e2e-user-${timestamp}@example.com`,
      password: 'UserPass123!',
      role: 'user',
    })

    try {
      await loginAs(page, user.username, 'UserPass123!')
      await page.goto('/admin/users')
      await page.waitForLoadState('networkidle')
      await expect(page).toHaveURL('/')
    } finally {
      const { access_token: adminToken } = await apiLogin(
        request,
        process.env.TEST_ADMIN_USERNAME || 'admin',
        process.env.TEST_ADMIN_PASSWORD || 'admin123'
      )
      await deleteUser(request, adminToken, user.id)
    }
  })

  test('session token is stored in localStorage after login', async ({ page }) => {
    await loginAsAdmin(page)
    const token = await page.evaluate(() => localStorage.getItem('nukelab-token'))
    expect(token).toBeTruthy()
    expect(token?.length).toBeGreaterThan(20)
  })

  test('XSS payloads in profile fields are not executed', async ({ page }) => {
    await loginAsAdmin(page)

    await page.goto('/settings/profile')
    await page.getByRole('button', { name: /Edit Profile/i }).click()

    const aboutField = page.locator('textarea').first()
    await aboutField.fill(XSS_PAYLOAD)

    const organizationField = page.locator('input[placeholder="Organization"]').first()
    await organizationField.fill(XSS_ORGANIZATION)

    await page
      .getByRole('button', { name: /Save Changes/i })
      .nth(1)
      .click()
    await page.waitForSelector('text=Profile updated', { timeout: 10000 })

    // Revisit the profile page to ensure persisted data is rendered.
    await page.goto('/settings/profile')
    await page.waitForLoadState('networkidle')

    const pageText = await page.textContent('body')
    expect(pageText).toContain(XSS_PAYLOAD)
    expect(pageText).toContain(XSS_ORGANIZATION)

    const xssExecuted = await page.evaluate(() => {
      const value = (window as Record<string, unknown>).__e2eXssExecuted
      return value === true
    })
    expect(xssExecuted).toBe(false)

    // Clean up profile so the admin account is not left with suspicious values.
    await page.getByRole('button', { name: /Edit Profile/i }).click()
    await page.locator('textarea').first().fill('')
    await page.locator('input[placeholder="Organization"]').first().fill('')
    await page
      .getByRole('button', { name: /Save Changes/i })
      .nth(1)
      .click()
    await page.waitForSelector('text=Profile updated', { timeout: 10000 })
  })

  test('login error messages do not expose sensitive details', async ({ page }) => {
    await page.goto('/login')
    await page.getByTestId('login-username').locator('visible=true').fill('nonexistent-user-12345')
    await page.getByTestId('login-password').locator('visible=true').fill('wrong-password')
    await page.getByTestId('login-submit').locator('visible=true').click()

    await expect(
      page.getByText(/incorrect username or password|login failed/i).locator('visible=true')
    ).toBeVisible()

    const pageText = await page.textContent('body')
    expect(pageText?.toLowerCase()).not.toContain('stack')
    expect(pageText?.toLowerCase()).not.toContain('traceback')
    expect(pageText?.toLowerCase()).not.toContain('sql')
    expect(pageText?.toLowerCase()).not.toContain('exception')
  })

  test('tokens are not leaked in the static page source', async ({ page }) => {
    await loginAsAdmin(page)
    const token = await page.evaluate(() => localStorage.getItem('nukelab-token'))
    expect(token).toBeTruthy()

    const html = await page.content()
    expect(html).not.toContain(token as string)
  })
})
