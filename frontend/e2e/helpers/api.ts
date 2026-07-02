import type { APIRequestContext } from '@playwright/test'

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export async function apiLogin(
  request: APIRequestContext,
  username: string,
  password: string
): Promise<LoginResponse> {
  const response = await request.post('/api/auth/login', {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    data: new URLSearchParams({ username, password }).toString(),
  })
  if (!response.ok()) {
    throw new Error(`API login failed: ${await response.text()}`)
  }
  return response.json()
}

export async function getOrCreateTestEnvironment(
  request: APIRequestContext,
  token: string
): Promise<string> {
  const list = await request.get('/api/environments/?is_active=true&limit=100', {
    headers: { Authorization: `Bearer ${token}` },
  })
  const listBody = await list.json()
  const existing = listBody?.data?.items?.find((e: { slug?: string }) => e.slug === 'e2e-default')
  if (existing) return existing.id

  const create = await request.post('/api/environments/', {
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    data: JSON.stringify({
      name: 'E2E Default',
      slug: 'e2e-default',
      image: 'nginx:alpine',
      description: 'Default environment for E2E tests',
      is_public: true,
      category: 'simulation',
    }),
  })
  if (!create.ok()) {
    throw new Error(`Failed to create test environment: ${await create.text()}`)
  }
  const body = await create.json()
  return body.data.id
}

export async function getPlanId(request: APIRequestContext, token: string): Promise<string> {
  const response = await request.get('/api/plans/?is_active=true&limit=100', {
    headers: { Authorization: `Bearer ${token}` },
  })
  const body = await response.json()
  const plan = body?.data?.items?.find((p: { slug?: string }) => p.slug === 'small')
  if (!plan) throw new Error('Small plan not found')
  return plan.id
}

export async function createServer(
  request: APIRequestContext,
  token: string,
  data: { name: string; plan_id: string; environment_id: string }
): Promise<{ id: string; name: string; status: string }> {
  const response = await request.post('/api/servers/', {
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    data: JSON.stringify(data),
  })
  if (!response.ok()) {
    throw new Error(`Failed to create server: ${await response.text()}`)
  }
  const body = await response.json()
  return body as { id: string; name: string; status: string }
}

export async function listServers(
  request: APIRequestContext,
  token: string
): Promise<Array<{ id: string; name: string; status: string }>> {
  const response = await request.get('/api/servers/', {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok()) return []
  const body = await response.json()
  return body?.servers || []
}

export async function deleteServer(request: APIRequestContext, token: string, serverId: string) {
  await request.delete(`/api/servers/${serverId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

export async function createUser(
  request: APIRequestContext,
  token: string,
  data: {
    username: string
    email: string
    password: string
    role?: string
    first_name?: string
    last_name?: string
  }
): Promise<{ id: string; username: string; role: string }> {
  const response = await request.post('/api/users/', {
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    data: JSON.stringify(data),
  })
  if (!response.ok()) {
    throw new Error(`Failed to create user: ${await response.text()}`)
  }
  const body = await response.json()
  return body as { id: string; username: string; role: string }
}

export async function deleteUser(request: APIRequestContext, token: string, userId: string) {
  await request.delete(`/api/users/${userId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

export async function updateProfile(
  request: APIRequestContext,
  token: string,
  data: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const response = await request.put('/api/users/me/profile', {
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    data: JSON.stringify(data),
  })
  if (!response.ok()) {
    throw new Error(`Failed to update profile: ${await response.text()}`)
  }
  return response.json()
}
