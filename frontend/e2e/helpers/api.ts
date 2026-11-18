// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import type { APIRequestContext, APIResponse } from '@playwright/test'
import { ADMIN_PASSWORD, ADMIN_USERNAME, BASE_URL, E2E_RUNTIME_IMAGE, uniqueName } from './runtime'

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface ServerVolumeMount {
  volume_id: string
  mount_path: string
  mode: string
  max_size_bytes?: number
}

export interface ServerRecord {
  id: string
  name: string
  status: string
  external_url?: string | null
  status_reason?: string | null
  stop_reason?: string | null
  user_id?: string
  username?: string
  plan_id?: string | null
  environment_id?: string | null
  volume_id?: string | null
  volume_mode?: string | null
  container_id?: string | null
  allocated_cpu?: number | null
  allocated_memory?: string | null
  allocated_disk?: string | null
  created_at?: string | null
  started_at?: string | null
  stopped_at?: string | null
}

export interface VolumeRecord {
  id: string
  name: string
  display_name: string
  owner_id: string
  visibility: string
  size_bytes: number
  max_size_bytes: number | null
  status: string
  server_count: number
  description?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface EnvironmentRecord {
  id: string
  name: string
  slug: string
  image: string
  description?: string | null
  category?: string | null
  is_active?: boolean
  is_public?: boolean
  tool_image?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface PlanRecord {
  id: string
  name: string
  slug: string
  cpu_limit?: number
  memory_limit?: string
  disk_limit?: string
  gpu_limit?: number
  is_active?: boolean
}

export interface UserRecord {
  id: string
  username: string
  email?: string
  role: string
}

export interface CreatedUser extends UserRecord {
  email: string
  password: string
}

export interface TestEnvironmentOptions {
  prefix?: string
  image?: string
  category?: string
  description?: string
  isPublic?: boolean
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/** Build an absolute app URL from a path or pass an absolute URL through. */
export function appUrl(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl
  return `${BASE_URL}${pathOrUrl.startsWith('/') ? '' : '/'}${pathOrUrl}`
}

/**
 * Base-url-aware fetch for direct requests that do not use Playwright's
 * `APIRequestContext` (which already applies `use.baseURL`).
 */
export async function apiFetch(pathOrUrl: string, init?: RequestInit): Promise<Response> {
  return fetch(appUrl(pathOrUrl), init)
}

export async function apiJson<T>(pathOrUrl: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(pathOrUrl, init)
  if (!response.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${pathOrUrl} failed (${response.status})`)
  }
  return (await response.json()) as T
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}`, ...JSON_HEADERS }
}

async function readJson<T>(response: APIResponse, action: string): Promise<T> {
  if (!response.ok()) {
    throw new Error(`${action} failed (${response.status()}): ${await response.text()}`)
  }
  return (await response.json()) as T
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
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

/** Log in with the environment-configured admin credentials. */
export async function adminLogin(request: APIRequestContext): Promise<LoginResponse> {
  return apiLogin(request, ADMIN_USERNAME, ADMIN_PASSWORD)
}

// ── Plans ────────────────────────────────────────────────────────────────────

export async function getPlanBySlug(
  request: APIRequestContext,
  token: string,
  slug = 'small'
): Promise<PlanRecord> {
  const response = await request.get('/api/plans/?is_active=true&limit=100', {
    headers: { Authorization: `Bearer ${token}` },
  })
  const body = await readJson<{ data?: { items?: PlanRecord[] } }>(response, 'List plans')
  const plan = body.data?.items?.find((item) => item.slug === slug)
  if (!plan) throw new Error(`Plan '${slug}' not found`)
  return plan
}

export async function getPlanId(
  request: APIRequestContext,
  token: string,
  slug = 'small'
): Promise<string> {
  return (await getPlanBySlug(request, token, slug)).id
}

// ── Environments ─────────────────────────────────────────────────────────────

export interface CreateEnvironmentInput {
  name: string
  slug: string
  image: string
  description?: string
  category?: string
  is_public?: boolean
}

export async function createEnvironment(
  request: APIRequestContext,
  token: string,
  data: CreateEnvironmentInput
): Promise<EnvironmentRecord> {
  const response = await request.post('/api/environments/', {
    headers: authHeaders(token),
    data: JSON.stringify(data),
  })
  const body = await readJson<{ data: EnvironmentRecord }>(response, 'Create environment')
  return body.data
}

/**
 * Create a unique environment for one test run. Cleanup is deliberately the
 * caller's responsibility so a test can only delete what it created.
 */
export async function createTestEnvironment(
  request: APIRequestContext,
  token: string,
  options: TestEnvironmentOptions = {}
): Promise<EnvironmentRecord> {
  const slug = uniqueName(options.prefix ?? 'e2e-env')
  return createEnvironment(request, token, {
    name: `E2E ${slug}`,
    slug,
    image: options.image ?? E2E_RUNTIME_IMAGE,
    description: options.description ?? 'Ephemeral environment created by a Playwright run.',
    category: options.category ?? 'simulation',
    is_public: options.isPublic ?? true,
  })
}

export async function listEnvironments(
  request: APIRequestContext,
  token: string,
  query = 'is_active=true&limit=100'
): Promise<EnvironmentRecord[]> {
  const response = await request.get(`/api/environments/?${query}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const body = await readJson<{ data?: { items?: EnvironmentRecord[] } }>(
    response,
    'List environments'
  )
  return body.data?.items ?? []
}

/**
 * Deterministic lookup for specs that intentionally reuse a seeded
 * environment. Per-run tests should use `createTestEnvironment` instead.
 */
export async function findEnvironmentByImage(
  request: APIRequestContext,
  token: string,
  image: string
): Promise<EnvironmentRecord | undefined> {
  const environments = await listEnvironments(request, token)
  return environments.find((environment) => environment.image === image)
}

export async function updateEnvironment(
  request: APIRequestContext,
  token: string,
  environmentId: string,
  data: Partial<CreateEnvironmentInput>
): Promise<EnvironmentRecord> {
  const response = await request.put(`/api/environments/${environmentId}`, {
    headers: authHeaders(token),
    data: JSON.stringify(data),
  })
  const body = await readJson<{ data: EnvironmentRecord }>(response, 'Update environment')
  return body.data
}

export async function deactivateEnvironment(
  request: APIRequestContext,
  token: string,
  environmentId: string
): Promise<void> {
  const response = await request.delete(`/api/environments/${environmentId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok() && response.status() !== 404) {
    throw new Error(
      `Deactivate environment failed (${response.status()}): ${await response.text()}`
    )
  }
}

// ── Servers ──────────────────────────────────────────────────────────────────

export interface CreateServerInput {
  name: string
  plan_id: string
  environment_id: string
  volume_id?: string | null
  volume_mode?: string
  volume_mounts?: ServerVolumeMount[]
}

export async function createServer(
  request: APIRequestContext,
  token: string,
  data: CreateServerInput
): Promise<ServerRecord> {
  const response = await request.post('/api/servers/', {
    headers: authHeaders(token),
    data: JSON.stringify(data),
  })
  if (response.status() === 202) {
    const queued = await response.text()
    throw new Error(`Server launch was queued unexpectedly: ${queued}`)
  }
  return readJson<ServerRecord>(response, 'Create server')
}

export async function listServers(
  request: APIRequestContext,
  token: string
): Promise<ServerRecord[]> {
  const response = await request.get('/api/servers/', {
    headers: { Authorization: `Bearer ${token}` },
  })
  const body = await readJson<{ servers?: ServerRecord[] }>(response, 'List servers')
  return body.servers ?? []
}

export async function getServer(
  request: APIRequestContext,
  token: string,
  serverId: string
): Promise<ServerRecord> {
  const response = await request.get(`/api/servers/${serverId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return readJson<ServerRecord>(response, 'Get server')
}

export async function getServerByPath(
  request: APIRequestContext,
  token: string,
  username: string,
  serverName: string
): Promise<ServerRecord> {
  const response = await request.get(
    `/api/servers/by-path/${encodeURIComponent(username)}/${encodeURIComponent(serverName)}`,
    { headers: { Authorization: `Bearer ${token}` } }
  )
  return readJson<ServerRecord>(response, 'Get server by path')
}

export interface ServerActionResponse {
  message: string
  server_id?: string
  status?: string
}

export async function startServer(
  request: APIRequestContext,
  token: string,
  serverId: string
): Promise<ServerActionResponse> {
  const response = await request.post(`/api/servers/${serverId}/start`, {
    headers: authHeaders(token),
    data: JSON.stringify({}),
  })
  return readJson<ServerActionResponse>(response, 'Start server')
}

export async function stopServer(
  request: APIRequestContext,
  token: string,
  serverId: string
): Promise<ServerActionResponse> {
  const response = await request.post(`/api/servers/${serverId}/stop`, {
    headers: authHeaders(token),
    data: JSON.stringify({}),
  })
  return readJson<ServerActionResponse>(response, 'Stop server')
}

export async function deleteServer(
  request: APIRequestContext,
  token: string,
  serverId: string
): Promise<void> {
  const response = await request.delete(`/api/servers/${serverId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok() && response.status() !== 404) {
    throw new Error(`Delete server failed (${response.status()}): ${await response.text()}`)
  }
}

/**
 * Delete a server after an in-flight launch has settled. A cleanup hook can run
 * while the runtime is still provisioning; `launch_in_progress` is retryable,
 * whereas any other error remains a real failure.
 */
export async function deleteServerEventually(
  request: APIRequestContext,
  token: string,
  serverId: string,
  timeoutMs = 90_000
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const response = await request.delete(`/api/servers/${serverId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (response.ok() || response.status() === 404) return
    const detail = await response.text()
    if (response.status() !== 409 || !detail.includes('launch_in_progress')) {
      throw new Error(`Delete server failed (${response.status()}): ${detail}`)
    }
    await delay(1000)
  }
  throw new Error(`Timed out waiting to delete server ${serverId}`)
}

export interface WaitForServerOptions {
  timeoutMs?: number
  intervalMs?: number
}

/**
 * Poll a server until it reaches one of the expected statuses. Always bounded
 * by a deadline; callers must not fall back to fixed sleeps for readiness.
 */
export async function waitForServerStatus(
  request: APIRequestContext,
  token: string,
  serverId: string,
  expected: string | string[],
  options: WaitForServerOptions = {}
): Promise<ServerRecord> {
  const wanted = Array.isArray(expected) ? expected : [expected]
  const deadline = Date.now() + (options.timeoutMs ?? 180_000)
  let last: ServerRecord | undefined

  while (Date.now() < deadline) {
    last = await getServer(request, token, serverId)
    if (wanted.includes(last.status)) return last
    if (last.status === 'error') {
      throw new Error(
        `Server ${serverId} entered error state: ${last.status_reason ?? 'unknown reason'}`
      )
    }
    await delay(options.intervalMs ?? 2000)
  }

  throw new Error(
    `Timed out waiting for server ${serverId} to reach ${wanted.join('|')} ` +
      `(last status: ${last?.status ?? 'unknown'})`
  )
}

// ── Volumes ──────────────────────────────────────────────────────────────────

export interface CreateVolumeInput {
  display_name: string
  description?: string
  max_size_bytes: number
}

export async function createVolume(
  request: APIRequestContext,
  token: string,
  data: CreateVolumeInput
): Promise<VolumeRecord> {
  const response = await request.post('/api/volumes/', {
    headers: authHeaders(token),
    data: JSON.stringify(data),
  })
  return readJson<VolumeRecord>(response, 'Create volume')
}

export async function listVolumes(
  request: APIRequestContext,
  token: string
): Promise<VolumeRecord[]> {
  const response = await request.get('/api/volumes/', {
    headers: { Authorization: `Bearer ${token}` },
  })
  const body = await readJson<{ volumes?: VolumeRecord[] }>(response, 'List volumes')
  return body.volumes ?? []
}

export async function getVolume(
  request: APIRequestContext,
  token: string,
  volumeId: string
): Promise<VolumeRecord> {
  const response = await request.get(`/api/volumes/${volumeId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return readJson<VolumeRecord>(response, 'Get volume')
}

export async function deleteVolume(
  request: APIRequestContext,
  token: string,
  volumeId: string
): Promise<void> {
  const response = await request.delete(`/api/volumes/${volumeId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok() && response.status() !== 404) {
    throw new Error(`Delete volume failed (${response.status()}): ${await response.text()}`)
  }
}

/**
 * Delete a volume after its runtime attachment has drained. Server deletion
 * returns before Docker has necessarily released the mount, so a single
 * delete can race the teardown and receive `volume_busy`.
 */
export async function deleteVolumeWhenDetached(
  request: APIRequestContext,
  token: string,
  volumeId: string,
  timeoutMs = 60_000
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const response = await request.delete(`/api/volumes/${volumeId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (response.ok() || response.status() === 404) return
    const detail = await response.text()
    const attachmentRace =
      response.status() === 409 || (response.status() === 400 && /delete volume/i.test(detail))
    if (!attachmentRace) {
      throw new Error(`Delete volume failed (${response.status()}): ${detail}`)
    }
    await delay(1000)
  }
  throw new Error(`Timed out waiting to delete volume ${volumeId}`)
}

export interface VolumeFileListing {
  type: 'directory' | 'file'
  path: string
  items: Array<{
    name: string
    type: 'directory' | 'file'
    size: number | null
    modified: number
  }>
  total: number
  page: number
  page_size: number
  total_pages: number
}

export async function listVolumeFiles(
  request: APIRequestContext,
  token: string,
  volumeId: string,
  path = ''
): Promise<VolumeFileListing> {
  const response = await request.get(`/api/volumes/${volumeId}/files`, {
    headers: { Authorization: `Bearer ${token}` },
    params: { path },
  })
  return readJson<VolumeFileListing>(response, 'List volume files')
}

export async function downloadVolumeFile(
  request: APIRequestContext,
  token: string,
  volumeId: string,
  path: string
): Promise<Uint8Array> {
  const response = await request.get(`/api/volumes/${volumeId}/download`, {
    headers: { Authorization: `Bearer ${token}` },
    params: { path },
  })
  if (!response.ok()) {
    throw new Error(`Download volume file failed (${response.status()}): ${await response.text()}`)
  }
  return response.body()
}

// ── Users ────────────────────────────────────────────────────────────────────

export const TEST_USER_PASSWORD = 'UserPass123!'

export interface CreateUserInput {
  username: string
  email: string
  password: string
  role?: string
  first_name?: string
  last_name?: string
}

export async function createUser(
  request: APIRequestContext,
  token: string,
  data: CreateUserInput
): Promise<UserRecord> {
  const response = await request.post('/api/users/', {
    headers: authHeaders(token),
    data: JSON.stringify(data),
  })
  return readJson<UserRecord>(response, 'Create user')
}

/**
 * Create a uniquely named user for one test run. The caller must delete the
 * returned user with `deleteUser`.
 */
export async function createTestUser(
  request: APIRequestContext,
  token: string,
  options: {
    prefix?: string
    role?: string
    password?: string
    firstName?: string
    lastName?: string
  } = {}
): Promise<CreatedUser> {
  const username = uniqueName(options.prefix ?? 'e2e-user')
  const email = `${username}@example.com`
  const password = options.password ?? TEST_USER_PASSWORD
  const user = await createUser(request, token, {
    username,
    email,
    password,
    role: options.role ?? 'user',
    first_name: options.firstName,
    last_name: options.lastName,
  })
  return { ...user, email, password }
}

export async function listUsers(
  request: APIRequestContext,
  token: string,
  query = 'limit=100'
): Promise<UserRecord[]> {
  const response = await request.get(`/api/users/?${query}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  const body = await readJson<{ users?: UserRecord[] }>(response, 'List users')
  return body.users ?? []
}

export async function deleteUser(
  request: APIRequestContext,
  token: string,
  userId: string
): Promise<void> {
  const response = await request.delete(`/api/users/${userId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok() && response.status() !== 404) {
    throw new Error(`Delete user failed (${response.status()}): ${await response.text()}`)
  }
}

export async function updateProfile(
  request: APIRequestContext,
  token: string,
  data: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const response = await request.put('/api/users/me/profile', {
    headers: authHeaders(token),
    data: JSON.stringify(data),
  })
  return readJson<Record<string, unknown>>(response, 'Update profile')
}
