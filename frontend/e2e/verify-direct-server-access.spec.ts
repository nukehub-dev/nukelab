import { test, expect } from '@playwright/test'

const SERVER_URL = 'http://localhost:8080/user/admin/test'

async function getAuthToken(): Promise<string> {
  const res = await fetch('http://localhost:8080/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'username=admin&password=admin123',
  })
  const data = await res.json()
  return data.access_token
}

async function ensureServerRunning(token: string): Promise<void> {
  const headers = { Authorization: `Bearer ${token}` }
  const listRes = await fetch('http://localhost:8080/api/servers', { headers })
  const list = await listRes.json()
  const server = list.servers.find(
    (s: { username?: string; name?: string }) => s.username === 'admin' && s.name === 'test'
  )
  if (!server) {
    throw new Error('Server admin/test not found')
  }
  if (server.status !== 'running') {
    await fetch(`http://localhost:8080/api/servers/${server.id}/start`, {
      method: 'POST',
      headers,
    })
    // Give the container a moment to reach a ready state.
    await new Promise((resolve) => setTimeout(resolve, 3000))
  }
}

test('direct /user/admin/test access redirects through gateway to server', async ({ page }) => {
  const token = await getAuthToken()
  await ensureServerRunning(token)

  // Inject the auth token so the SPA is logged in when it loads.
  await page.addInitScript((authToken: string) => {
    localStorage.setItem('nukelab-token', authToken)
  }, token)

  // Capture navigation events for debugging.
  page.on('console', (msg) => console.log('PAGE CONSOLE:', msg.text()))

  // Direct access without a server token should redirect to the SPA,
  // which then navigates to the gateway, acquires a token, and loads
  // the server environment.
  await page.goto(SERVER_URL)

  // The browser is initially redirected to /?next=/user/admin/test by the
  // server container, then the SPA navigates to the gateway, gets a token,
  // and finally loads the real server. Allow up to 60s for container ready.
  await expect(page).toHaveTitle(/ttyd/, { timeout: 60_000 })
})
