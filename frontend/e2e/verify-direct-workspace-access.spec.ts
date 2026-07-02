import { test, expect } from '@playwright/test'

const BASE_URL = 'http://localhost:8080'
const WORKSPACE_IMAGE = 'nukelab-workspace:latest'

async function getAuthToken(): Promise<string> {
  const res = await fetch(`${BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'username=admin&password=admin123',
  })
  const data = await res.json()
  return data.access_token
}

async function findWorkspaceEnvironmentId(token: string): Promise<string> {
  const res = await fetch(`${BASE_URL}/api/environments/`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const list = await res.json()
  const env = list.data.items.find(
    (e: { image?: string; id?: string }) => e.image === WORKSPACE_IMAGE
  )
  if (!env) {
    throw new Error(`Workspace environment (${WORKSPACE_IMAGE}) not found`)
  }
  return env.id
}

async function findSmallPlanId(token: string): Promise<string> {
  const res = await fetch(`${BASE_URL}/api/plans/`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const list = await res.json()
  const plan = list.data.items.find((p: { slug?: string; id?: string }) => p.slug === 'small')
  if (!plan) {
    throw new Error('Small plan not found')
  }
  return plan.id
}

async function createWorkspaceServer(token: string): Promise<{ id: string; url: string }> {
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
  const environmentId = await findWorkspaceEnvironmentId(token)
  const planId = await findSmallPlanId(token)
  const name = `e2e-ws-${crypto.randomUUID().slice(0, 8)}`

  const createRes = await fetch(`${BASE_URL}/api/servers/`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      name,
      environment_id: environmentId,
      plan_id: planId,
      volume_mode: 'read_write',
    }),
  })
  const created = await createRes.json()
  const serverId = created.id ?? created.server?.id
  if (!serverId) {
    throw new Error(`Failed to create workspace server: ${JSON.stringify(created)}`)
  }

  const startRes = await fetch(`${BASE_URL}/api/servers/${serverId}/start`, {
    method: 'POST',
    headers,
  })
  if (!startRes.ok) {
    throw new Error(`Failed to start workspace server ${serverId}: ${startRes.status}`)
  }

  // Wait for the server to reach running state.
  for (let i = 0; i < 30; i++) {
    const statusRes = await fetch(`${BASE_URL}/api/servers/${serverId}`, { headers })
    const status = await statusRes.json()
    const currentStatus = status.status ?? status.server?.status
    if (currentStatus === 'running') {
      break
    }
    await new Promise((resolve) => setTimeout(resolve, 2000))
  }

  return { id: serverId, url: `${BASE_URL}/user/admin/${name}` }
}

test('direct workspace URL access loads the IDE and assets', async ({ page }) => {
  const token = await getAuthToken()
  const { url: serverUrl } = await createWorkspaceServer(token)

  await page.addInitScript((authToken: string) => {
    localStorage.setItem('nukelab-token', authToken)
  }, token)

  page.on('console', (msg) => console.log('PAGE CONSOLE:', msg.text()))
  page.on('pageerror', (err) => console.error('PAGE ERROR:', err.message))

  // Direct access without a server token should redirect to the SPA gateway
  // flow, which obtains a server token and loads the workspace IDE.
  await page.goto(serverUrl)

  // The Traefik middleware redirects the bare prefix to a trailing slash so
  // relative IDE assets resolve under the strip prefix.
  await page.waitForURL(`${serverUrl}/`, { timeout: 60_000 })

  // The workspace IDE should render the NukeIDE shell.
  await expect(page.locator('body')).toContainText('NukeIDE', { timeout: 30_000 })

  // Core IDE assets should have loaded (no 404s for bundle / logo).
  const bundleRequest = page.request.get(`${serverUrl}/bundle.js`)
  const logoRequest = page.request.get(`${serverUrl}/logo.svg`)
  await expect((await bundleRequest).status()).toBe(200)
  await expect((await logoRequest).status()).toBe(200)
})
