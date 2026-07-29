import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test.describe('Support page', () => {
  test('shows community, contact, and blog links', async ({ page }) => {
    await loginAsAdmin(page)

    await page.goto('/support')
    await expect(page.getByRole('heading', { name: 'Support' })).toBeVisible()

    const community = page.getByRole('link', { name: /NukeTalk Community/ })
    await expect(community).toHaveAttribute('href', 'https://talk.nukehub.org')
    await expect(community).toHaveAttribute('target', '_blank')

    await expect(page.getByRole('link', { name: /Contact Us/ })).toHaveAttribute(
      'href',
      'https://nukehub.org/contact'
    )
    await expect(page.getByRole('link', { name: /Blog & Updates/ })).toHaveAttribute(
      'href',
      'https://blog.nukehub.org'
    )
  })

  test('support links are present on the login page', async ({ page }) => {
    await page.goto('/login')

    await expect(
      page.getByRole('link', { name: 'Community', exact: true }).first()
    ).toHaveAttribute('href', 'https://talk.nukehub.org')
    await expect(page.getByRole('link', { name: 'Contact', exact: true }).first()).toHaveAttribute(
      'href',
      'https://nukehub.org/contact'
    )
    await expect(page.getByRole('link', { name: 'Blog', exact: true }).first()).toHaveAttribute(
      'href',
      'https://blog.nukehub.org'
    )
  })
})
