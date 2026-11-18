// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Combined real-stack acceptance: reproducible environment capture, offline
 * volume backup/restore, durable queued recreation, owner privacy, capacity
 * admission and the normal cancellation/claim boundary.
 *
 * Everything goes through the running HTTP API. Docker access is runner-only
 * fixture work for seeded volume data and runtime identity evidence.
 */

import { test, expect, type APIRequestContext } from '@playwright/test'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import {
  ADMIN_PASSWORD,
  ADMIN_USERNAME,
  MOUNT_PATH,
  SMALL_PLAN_SLUG,
  VOLUME_BYTES,
  apiCall,
  apiErrorCode,
  apiLogin,
  containerImageIdentity,
  containersForServer,
  inspectContainerHardening,
  copyArtifactDirectory,
  corruptArtifact,
  dockerImageId,
  downloadFileHash,
  inspectVolume,
  loginAsAdmin,
  newRequestId,
  poll,
  readArtifactEvidence,
  seedManifest,
  seedVolume,
  uniqueName,
  uniqueSlug,
  type BackupDto,
  type ProvenanceDto,
  type QueueEntryDto,
  type QueuedServerDto,
  type QuotaDto,
  type RestoreDto,
  type SeedManifest,
  type ServerDto,
  type VolumeDto,
} from './helpers/combined-fixtures'

const COMBINED_ENABLED = process.env.E2E_COMBINED === '1'
const MAIN_TIMEOUT_MS = 20 * 60_000
const CLEANUP_TIMEOUT_MS = 5 * 60_000
const SERVER_READY_TIMEOUT_MS = 180_000
const OPERATION_TIMEOUT_MS = 120_000
const QUEUE_ADMISSION_TIMEOUT_MS = SERVER_READY_TIMEOUT_MS + 60_000
const POLL_INTERVAL_MS = 1_000

interface CombinedState {
  adminToken?: string
  adminUserId?: string
  runtimeImageA?: string
  runtimeImageB?: string
  imageA?: string
  imageB?: string
  smallPlanId?: string
  planId?: string
  envAId?: string
  envFId?: string
  volumeVId?: string
  volumeV2Id?: string
  volumeVfId?: string
  backupId?: string
  restoreId?: string
  failedDestinationVolumeId?: string
  userId?: string
  serverIds: string[]
  queueIds: string[]
  restoreIds: string[]
  artifactTempDir?: string
  seed?: SeedManifest
}

const state: CombinedState = { serverIds: [], queueIds: [], restoreIds: [] }

function trackServer(id: string | null | undefined): void {
  if (id && !state.serverIds.includes(id)) state.serverIds.push(id)
}

function trackQueue(id: string | null | undefined): void {
  if (id && !state.queueIds.includes(id)) state.queueIds.push(id)
}

function expectStatus(
  result: { status: number; text: string },
  expected: number,
  label: string
): void {
  expect(result.status, `${label} response: ${result.text}`).toBe(expected)
}

async function listOwnerServers(
  request: APIRequestContext,
  token: string,
  userId: string
): Promise<Array<{ id: string; name: string; status: string }>> {
  // The admin server-list endpoint is cached; the per-user view is not and is
  // therefore authoritative for name/count assertions right after admission.
  const result = await apiCall<{ servers: Array<{ id: string; name: string; status: string }> }>(
    request,
    'GET',
    `/api/users/${userId}/servers`,
    token
  )
  expectStatus(result, 200, 'list owner servers')
  return result.body?.servers ?? []
}

async function getServer(
  request: APIRequestContext,
  token: string,
  serverId: string
): Promise<ServerDto | null> {
  const result = await apiCall<ServerDto>(request, 'GET', `/api/servers/${serverId}`, token)
  if (result.status === 404) return null
  expectStatus(result, 200, `get server ${serverId}`)
  return result.body
}

async function waitForServer(
  request: APIRequestContext,
  token: string,
  serverId: string,
  status: string,
  timeoutMs = SERVER_READY_TIMEOUT_MS
): Promise<ServerDto> {
  const server = await poll(
    `server ${serverId} status ${status}`,
    () => getServer(request, token, serverId),
    (value) => value !== null && [status, 'error', 'failed'].includes(value.status),
    {
      timeoutMs,
      intervalMs: POLL_INTERVAL_MS,
      describe: (value) => `status=${value?.status ?? 'missing'}`,
    }
  )
  if (!server || server.status !== status) {
    throw new Error(
      `Server ${serverId} reached ${server?.status ?? 'missing'} instead of ${status}`
    )
  }
  return server
}

async function waitForServerGone(
  request: APIRequestContext,
  token: string,
  serverId: string,
  timeoutMs = OPERATION_TIMEOUT_MS
): Promise<void> {
  await poll(
    `server ${serverId} deletion`,
    () => getServer(request, token, serverId),
    (value) => value === null,
    { timeoutMs, intervalMs: POLL_INTERVAL_MS, describe: (value) => value?.status ?? 'missing' }
  )
}

async function stopServer(
  request: APIRequestContext,
  token: string,
  serverId: string
): Promise<ServerDto> {
  const result = await apiCall<{ status: string }>(
    request,
    'POST',
    `/api/servers/${serverId}/stop`,
    token,
    {
      data: { reason: 'combined acceptance stop' },
      timeout: SERVER_READY_TIMEOUT_MS,
    }
  )
  expectStatus(result, 200, `stop server ${serverId}`)
  return waitForServer(request, token, serverId, 'stopped')
}

async function deleteServer(
  request: APIRequestContext,
  token: string,
  serverId: string
): Promise<void> {
  const result = await apiCall<{ message: string }>(
    request,
    'DELETE',
    `/api/servers/${serverId}`,
    token,
    {
      timeout: SERVER_READY_TIMEOUT_MS,
    }
  )
  if (![200, 204, 404].includes(result.status)) {
    throw new Error(`Delete server ${serverId} failed: ${result.status} ${result.text}`)
  }
  await waitForServerGone(request, token, serverId)
}

async function listVolumes(request: APIRequestContext, token: string): Promise<VolumeDto[]> {
  const result = await apiCall<{ volumes: VolumeDto[] }>(request, 'GET', '/api/volumes/', token)
  expectStatus(result, 200, 'list volumes')
  return result.body?.volumes ?? []
}

async function getVolume(
  request: APIRequestContext,
  token: string,
  volumeId: string
): Promise<VolumeDto | null> {
  const result = await apiCall<VolumeDto>(request, 'GET', `/api/volumes/${volumeId}`, token)
  if (result.status === 404) return null
  expectStatus(result, 200, `get volume ${volumeId}`)
  return result.body
}

async function listVolumeFiles(
  request: APIRequestContext,
  token: string,
  volumeId: string,
  directory = ''
): Promise<Array<{ name: string; type: string; size: number | null }>> {
  const result = await apiCall<{
    type: string
    items: Array<{ name: string; type: string; size: number | null }>
  }>(request, 'GET', `/api/volumes/${volumeId}/files`, token, {
    params: { path: directory, page_size: 100 },
  })
  expectStatus(result, 200, `list volume ${volumeId} path ${directory || '/'}`)
  return result.body?.items ?? []
}

async function getQueue(
  request: APIRequestContext,
  token: string,
  queueId: string
): Promise<QueueEntryDto | null> {
  const result = await apiCall<QueueEntryDto>(request, 'GET', `/api/server-queue/${queueId}`, token)
  if (result.status === 404) return null
  expectStatus(result, 200, `get queue ${queueId}`)
  return result.body
}

async function getBackup(
  request: APIRequestContext,
  token: string,
  backupId: string
): Promise<BackupDto | null> {
  const result = await apiCall<BackupDto>(request, 'GET', `/api/volume-backups/${backupId}`, token)
  if (result.status === 404) return null
  expectStatus(result, 200, `get backup ${backupId}`)
  return result.body
}

async function getRestore(
  request: APIRequestContext,
  token: string,
  restoreId: string
): Promise<RestoreDto | null> {
  const result = await apiCall<RestoreDto>(
    request,
    'GET',
    `/api/volume-restores/${restoreId}`,
    token
  )
  if (result.status === 404) return null
  expectStatus(result, 200, `get restore ${restoreId}`)
  return result.body
}

async function getQuota(request: APIRequestContext, token: string): Promise<QuotaDto> {
  const result = await apiCall<{ success: boolean; data: QuotaDto }>(
    request,
    'GET',
    '/api/quotas/',
    token
  )
  expectStatus(result, 200, 'get quota')
  if (!result.body?.data) throw new Error('Quota response had no data')
  return result.body.data
}

async function getBalance(request: APIRequestContext, token: string): Promise<number> {
  const result = await apiCall<{ nuke_balance: number }>(
    request,
    'GET',
    '/api/users/me/profile',
    token
  )
  expectStatus(result, 200, 'get profile balance')
  return result.body?.nuke_balance ?? 0
}

async function expectSeededContent(
  request: APIRequestContext,
  token: string,
  volumeId: string,
  seed: SeedManifest
): Promise<void> {
  const expectedPaths = [
    seed.paths.hello,
    seed.paths.nested,
    seed.paths.deep,
    seed.paths.unicode,
    seed.paths.hardlink,
  ]
  for (const relativePath of expectedPaths) {
    const digest = await downloadFileHash(request, token, volumeId, relativePath)
    expect(digest.digest, `SHA-256 for ${relativePath}`).toBe(seed.hashes[relativePath])
    const size = Buffer.byteLength(
      relativePath === seed.paths.hardlink
        ? `${seed.contents.hello}\n`
        : `${
            seed.contents[
              relativePath === seed.paths.hello
                ? 'hello'
                : relativePath === seed.paths.nested
                  ? 'nested'
                  : relativePath === seed.paths.deep
                    ? 'deep'
                    : 'unicode'
            ]
          }\n`
    )
    expect(digest.size, `downloaded size for ${relativePath}`).toBe(size)
  }
}

async function cleanupServer(
  request: APIRequestContext,
  token: string,
  serverId: string
): Promise<void> {
  const deadline = Date.now() + OPERATION_TIMEOUT_MS
  for (;;) {
    const server = await getServer(request, token, serverId)
    if (!server) return
    if (['starting', 'stopping'].includes(server.status)) {
      if (Date.now() >= deadline) {
        console.warn(`[combined cleanup] server ${serverId} stayed ${server.status}; leaving it`)
        return
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
      continue
    }
    const result = await apiCall<{ message: string }>(
      request,
      'DELETE',
      `/api/servers/${serverId}`,
      token,
      {
        timeout: SERVER_READY_TIMEOUT_MS,
      }
    )
    if ([200, 204, 404].includes(result.status)) {
      await waitForServerGone(request, token, serverId).catch((error) => {
        console.warn(`[combined cleanup] server ${serverId}: ${String(error)}`)
      })
      return
    }
    if (result.status === 409) {
      if (Date.now() >= deadline) {
        console.warn(`[combined cleanup] server ${serverId} delete stayed busy; leaving it`)
        return
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
      continue
    }
    console.warn(
      `[combined cleanup] server ${serverId} delete failed: ${result.status} ${result.text}`
    )
    return
  }
}

async function cleanupMultipleServers(request: APIRequestContext, token: string): Promise<void> {
  for (const serverId of state.serverIds) {
    try {
      await cleanupServer(request, token, serverId)
    } catch (error) {
      console.warn(`[combined cleanup] server ${serverId}: ${String(error)}`)
    }
  }
}

async function cleanupVolumes(request: APIRequestContext, token: string): Promise<void> {
  const ids = [
    state.failedDestinationVolumeId,
    state.volumeV2Id,
    state.volumeVfId,
    state.volumeVId,
  ].filter((value): value is string => Boolean(value))
  if (state.backupId) {
    // Catch a destination created by a restore whose 202 response was lost or
    // whose test failed before recording the destination identity.
    try {
      const restores = await apiCall<{ items: RestoreDto[] }>(
        request,
        'GET',
        '/api/volume-restores',
        token,
        { params: { backup_id: state.backupId, page_size: 100 } }
      )
      if (restores.status === 200) {
        for (const restore of restores.body?.items ?? []) {
          if (restore.destination_volume_id && !ids.includes(restore.destination_volume_id)) {
            ids.push(restore.destination_volume_id)
          }
        }
      }
    } catch (error) {
      console.warn(`[combined cleanup] restore destination discovery: ${String(error)}`)
    }
  }
  for (const volumeId of ids) {
    try {
      const deadline = Date.now() + OPERATION_TIMEOUT_MS
      for (;;) {
        const volume = await getVolume(request, token, volumeId)
        if (!volume) break
        const result = await apiCall<{ message: string }>(
          request,
          'DELETE',
          `/api/volumes/${volumeId}`,
          token,
          { timeout: SERVER_READY_TIMEOUT_MS }
        )
        if ([200, 204, 404].includes(result.status)) break
        if (result.status === 409 && Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
          continue
        }
        console.warn(
          `[combined cleanup] volume ${volumeId} (${volume.name}, ${volume.status}) not removed: ${result.status} ${result.text}`
        )
        break
      }
    } catch (error) {
      console.warn(`[combined cleanup] volume ${volumeId}: ${String(error)}`)
    }
  }
}

async function cleanupBackup(request: APIRequestContext, token: string): Promise<void> {
  const backupId = state.backupId
  if (!backupId) return
  const backup = await getBackup(request, token, backupId)
  if (!backup || backup.status === 'deleted') return
  const result = await apiCall<BackupDto>(
    request,
    'DELETE',
    `/api/volume-backups/${backupId}`,
    token
  )
  if (![200, 202, 404].includes(result.status)) {
    console.warn(
      `[combined cleanup] backup ${backupId} delete failed: ${result.status} ${result.text}`
    )
    return
  }
  try {
    const finalBackup = await poll(
      `backup ${backupId} deletion`,
      () => getBackup(request, token, backupId),
      (value) => value === null || ['deleted', 'delete_failed', 'failed'].includes(value.status),
      {
        timeoutMs: OPERATION_TIMEOUT_MS,
        intervalMs: POLL_INTERVAL_MS,
        describe: (value) => `status=${value?.status ?? 'missing'}`,
      }
    )
    if (finalBackup && finalBackup.status !== 'deleted') {
      console.warn(
        `[combined cleanup] backup ${backupId} (${finalBackup.status}) could not be safely removed`
      )
    }
  } catch (error) {
    console.warn(`[combined cleanup] backup ${backupId}: ${String(error)}`)
  }
}

async function cleanupQueues(request: APIRequestContext, token: string): Promise<void> {
  for (const queueId of state.queueIds) {
    try {
      const entry = await getQueue(request, token, queueId)
      if (!entry || entry.status !== 'pending') continue
      const result = await apiCall<QueueEntryDto>(
        request,
        'POST',
        `/api/server-queue/${queueId}/cancel`,
        token
      )
      if (![200, 204, 404, 409].includes(result.status)) {
        console.warn(
          `[combined cleanup] queue ${queueId} cancel failed: ${result.status} ${result.text}`
        )
      }
    } catch (error) {
      console.warn(`[combined cleanup] queue ${queueId}: ${String(error)}`)
    }
  }
}

test.describe('combined release acceptance', () => {
  test.skip(
    !COMBINED_ENABLED,
    'Set E2E_COMBINED=1 against a disposable stack to run the combined release scenario.'
  )
  // This is a stateful, expensive acceptance run: a silent retry would leave a
  // second set of stacks behind and could mask a one-shot race failure.
  test.describe.configure({ mode: 'serial', retries: 0 })

  test.beforeAll(async ({ request }) => {
    test.setTimeout(MAIN_TIMEOUT_MS)
    const required = ['E2E_RUNTIME_IMAGE', 'E2E_RUNTIME_IMAGE_B'] as const
    const missing = required.filter((name) => !process.env[name])
    if (missing.length > 0) {
      throw new Error(`Combined scenario requires environment variables: ${missing.join(', ')}`)
    }
    if (!['1', 'true'].includes(process.env.E2E_EXTERNAL_SERVER ?? '')) {
      throw new Error('E2E_EXTERNAL_SERVER=1 is required for the combined real-stack scenario')
    }
    state.adminToken = await apiLogin(request, ADMIN_USERNAME, ADMIN_PASSWORD)
    const profile = await apiCall<{ id: string }>(
      request,
      'GET',
      '/api/users/me/profile',
      state.adminToken
    )
    expectStatus(profile, 200, 'admin profile')
    state.adminUserId = profile.body?.id
    state.runtimeImageA = process.env.E2E_RUNTIME_IMAGE
    state.runtimeImageB = process.env.E2E_RUNTIME_IMAGE_B
    state.imageA = dockerImageId(state.runtimeImageA as string)
    state.imageB = dockerImageId(state.runtimeImageB as string)
    expect(
      state.imageB,
      'Runtime fixture B must be a distinct image from runtime fixture A'
    ).not.toBe(state.imageA)

    const plans = await apiCall<{
      success: boolean
      data: { items: Array<{ id: string; slug: string; is_active: boolean }> }
    }>(request, 'GET', '/api/plans/', state.adminToken, {
      params: { is_active: 'true', limit: 100 },
    })
    expectStatus(plans, 200, 'list plans')
    const small = plans.body?.data?.items?.find((plan) => plan.slug === SMALL_PLAN_SLUG)
    if (!small) {
      throw new Error('The seeded small plan is required by the combined capacity scenario')
    }
    state.smallPlanId = small.id
  })

  test.afterAll(async ({ request }) => {
    test.setTimeout(CLEANUP_TIMEOUT_MS)
    let token = state.adminToken
    try {
      token = token ?? (await apiLogin(request, ADMIN_USERNAME, ADMIN_PASSWORD))
    } catch (error) {
      console.warn(`[combined cleanup] admin login failed: ${String(error)}`)
      return
    }
    try {
      await cleanupQueues(request, token)
    } catch (error) {
      console.warn(`[combined cleanup] queue cleanup: ${String(error)}`)
    }
    try {
      await cleanupMultipleServers(request, token)
    } catch (error) {
      console.warn(`[combined cleanup] server cleanup: ${String(error)}`)
    }
    try {
      await cleanupBackup(request, token)
    } catch (error) {
      console.warn(`[combined cleanup] backup cleanup: ${String(error)}`)
    }
    try {
      await cleanupVolumes(request, token)
    } catch (error) {
      console.warn(`[combined cleanup] volume cleanup: ${String(error)}`)
    }
    if (state.userId) {
      try {
        const result = await apiCall(request, 'DELETE', `/api/users/${state.userId}`, token)
        if (![200, 204, 404].includes(result.status)) {
          await apiCall(request, 'POST', `/api/users/${state.userId}/disable`, token, {
            data: { disabled: true, reason: 'combined acceptance cleanup' },
          })
        }
      } catch (error) {
        console.warn(`[combined cleanup] user ${state.userId}: ${String(error)}`)
      }
    }
    for (const [label, envId] of [
      ['environment A', state.envAId],
      ['environment F', state.envFId],
    ] as const) {
      if (!envId) continue
      try {
        const result = await apiCall(request, 'DELETE', `/api/environments/${envId}`, token)
        if (![200, 204, 404].includes(result.status)) {
          console.warn(`[combined cleanup] ${label} ${envId} deactivate failed: ${result.status}`)
        }
      } catch (error) {
        console.warn(`[combined cleanup] ${label} ${envId}: ${String(error)}`)
      }
    }
    if (state.planId) {
      try {
        const result = await apiCall(request, 'DELETE', `/api/plans/${state.planId}`, token)
        if (![200, 204, 404].includes(result.status)) {
          console.warn(
            `[combined cleanup] plan ${state.planId} deactivate failed: ${result.status}`
          )
        }
      } catch (error) {
        console.warn(`[combined cleanup] plan ${state.planId}: ${String(error)}`)
      }
    }
    if (state.artifactTempDir) {
      try {
        rmSync(state.artifactTempDir, { recursive: true, force: true })
      } catch (error) {
        console.warn(`[combined cleanup] artifact copy: ${String(error)}`)
      }
    }
    console.log(
      JSON.stringify({
        scope: 'combined-cleanup',
        plan: state.planId,
        environments: [state.envAId, state.envFId],
        volumes: [
          state.volumeVId,
          state.volumeV2Id,
          state.volumeVfId,
          state.failedDestinationVolumeId,
        ],
        backup: state.backupId,
        restores: state.restoreIds,
        servers: state.serverIds,
        queues: state.queueIds,
        user: state.userId,
      })
    )
  })

  test('@combined captures A, backs up and restores V, queues recreation, then admits A with V2', async ({
    request,
    page,
  }) => {
    test.setTimeout(MAIN_TIMEOUT_MS)
    if (
      !state.adminToken ||
      !state.adminUserId ||
      !state.smallPlanId ||
      !state.imageA ||
      !state.imageB
    ) {
      throw new Error('Combined test fixtures were not initialized')
    }
    const adminToken = state.adminToken
    const adminUserId = state.adminUserId
    const stamp = uniqueName('combined')
    const seed = seedManifest(stamp)
    state.seed = seed
    const planName = `Combined 3x6 ${stamp}`
    const planSlug = uniqueSlug('combined-plan')
    const envAName = `Combined Runtime A ${stamp}`
    const envASlug = uniqueSlug('combined-runtime-a')
    const envFName = `Combined Filler Runtime ${stamp}`
    const envFSlug = uniqueSlug('combined-filler-runtime')
    const serverName = uniqueName('combined-source')
    const recreatedName = uniqueName('combined-recreated')
    const fillerName = uniqueName('combined-filler')
    const cancelName = uniqueName('combined-cancel')
    const raceName = uniqueName('combined-race')
    const volumeVName = `Combined data ${stamp}`
    const volumeVfName = `Combined filler data ${stamp}`
    const volumeV2Name = `Combined restored ${stamp}`
    const restoreDescription = `Combined backup ${stamp}`

    const evidence: Record<string, unknown> = { stamp }

    const createServer = async (
      name: string,
      planId: string,
      environmentId: string,
      volumeId: string | null,
      mountPath: string
    ): Promise<ServerDto> => {
      const result = await apiCall<ServerDto | QueuedServerDto>(
        request,
        'POST',
        '/api/servers/',
        adminToken,
        {
          data: {
            name,
            plan_id: planId,
            environment_id: environmentId,
            volume_mounts: volumeId
              ? [{ volume_id: volumeId, mount_path: mountPath, mode: 'read_write' }]
              : undefined,
          },
          timeout: SERVER_READY_TIMEOUT_MS,
        }
      )
      if (result.status === 202) {
        const queued = result.body as QueuedServerDto
        trackQueue(queued.queue_id)
        throw new Error(
          `Server ${name} was queued instead of starting; the combined scenario needs free capacity: ${result.text}`
        )
      }
      expectStatus(result, 200, `create server ${name}`)
      const server = result.body as ServerDto | null
      if (!server?.id) {
        throw new Error(`Server create for ${name} returned no server identity: ${result.text}`)
      }
      trackServer(server.id)
      return waitForServer(request, adminToken, server.id, 'running')
    }

    // 1. Custom plan with exactly the capacity used by the scenario.
    const plan = await apiCall<{ success: boolean; data: { id: string; slug: string } }>(
      request,
      'POST',
      '/api/plans/',
      adminToken,
      {
        data: {
          name: planName,
          slug: planSlug,
          description: 'Combined real-stack acceptance plan',
          category: 'cpu',
          cpu_limit: 3.0,
          memory_limit: '6g',
          disk_limit: '30g',
          max_servers_per_user: 10,
          cost_per_hour: 1,
          is_public: true,
        },
      }
    )
    expectStatus(plan, 201, 'create combined plan')
    state.planId = plan.body?.data.id
    expect(state.planId).toBeTruthy()

    // 2. Approved environment A, a stable filler environment, private volume V and filler volume VF.
    const envA = await apiCall<{ success: boolean; data: { id: string; image: string } }>(
      request,
      'POST',
      '/api/environments/',
      adminToken,
      {
        data: {
          name: envAName,
          slug: envASlug,
          image: state.runtimeImageA,
          description: 'Combined runtime A fixture',
          is_public: true,
          category: 'base',
        },
      }
    )
    expectStatus(envA, 201, 'create environment A')
    state.envAId = envA.body?.data.id
    expect(state.envAId).toBeTruthy()

    const envF = await apiCall<{ success: boolean; data: { id: string; image: string } }>(
      request,
      'POST',
      '/api/environments/',
      adminToken,
      {
        data: {
          name: envFName,
          slug: envFSlug,
          image: state.runtimeImageA,
          description: 'Combined stable filler runtime',
          is_public: true,
          category: 'base',
        },
      }
    )
    expectStatus(envF, 201, 'create filler environment')
    state.envFId = envF.body?.data.id
    expect(state.envFId).toBeTruthy()

    const volumeV = await apiCall<VolumeDto>(request, 'POST', '/api/volumes/', adminToken, {
      data: {
        display_name: volumeVName,
        description: 'Combined source data volume',
        max_size_bytes: VOLUME_BYTES,
      },
    })
    expectStatus(volumeV, 201, 'create volume V')
    state.volumeVId = volumeV.body?.id
    expect(state.volumeVId).toBeTruthy()

    const volumeVf = await apiCall<VolumeDto>(request, 'POST', '/api/volumes/', adminToken, {
      data: {
        display_name: volumeVfName,
        description: 'Combined filler capacity volume',
        max_size_bytes: VOLUME_BYTES,
      },
    })
    expectStatus(volumeVf, 201, 'create filler volume VF')
    state.volumeVfId = volumeVf.body?.id
    expect(state.volumeVfId).toBeTruthy()

    // 3. Launch S with the custom plan, environment A and V read-write at /data.
    const source = await createServer(
      serverName,
      state.planId as string,
      state.envAId as string,
      state.volumeVId as string,
      MOUNT_PATH
    )
    expect(source.status).toBe('running')
    expect(source.container_id).toBeTruthy()
    expect(source.plan_id).toBe(state.planId)
    expect(source.environment_id).toBe(state.envAId)
    expect(source.volume_mounts).toEqual([
      expect.objectContaining({
        volume_id: state.volumeVId,
        mount_path: MOUNT_PATH,
        mode: 'read_write',
        is_primary: true,
      }),
    ])

    const provenance = await apiCall<ProvenanceDto>(
      request,
      'GET',
      `/api/servers/${source.id}/provenance`,
      adminToken
    )
    expectStatus(provenance, 200, 'source provenance')
    const sourceProvenance = provenance.body
    expect(sourceProvenance?.state).toBe('recorded')
    expect(sourceProvenance?.launch_id).toBeTruthy()
    expect(sourceProvenance?.actual_runtime?.local_id).toBe(state.imageA)
    expect(sourceProvenance?.actual_runtime?.local_id).not.toBe(state.imageB)
    expect(sourceProvenance?.manifest?.runtime.requested_reference).toBe(state.runtimeImageA)
    expect(sourceProvenance?.manifest?.volume_requirements).toEqual([
      expect.objectContaining({ mount_path: MOUNT_PATH, mode: 'read_write' }),
    ])
    const sourceLaunchId = sourceProvenance?.launch_id ?? null
    const sourceRevisionId = sourceProvenance?.manifest?.revision_id ?? null
    expect(sourceLaunchId).toBeTruthy()
    expect(sourceRevisionId).toBeTruthy()

    seedVolume(source.container_id as string, seed)
    const sourceBefore = inspectVolume(source.container_id as string, seed)
    expect(sourceBefore.hashes).toEqual(seed.hashes)
    for (const [relativePath, expectedMode] of Object.entries(seed.sourceModes)) {
      expect(sourceBefore.entries[relativePath]?.mode, `source mode ${relativePath}`).toBe(
        expectedMode
      )
    }
    for (const relativePath of Object.keys(seed.sourceModes)) {
      expect(sourceBefore.entries[relativePath]?.uid, `source uid ${relativePath}`).toBe(65532)
      expect(sourceBefore.entries[relativePath]?.gid, `source gid ${relativePath}`).toBe(65532)
    }
    expect(sourceBefore.symlinkTarget).toBe(seed.paths.hello)
    expect(sourceBefore.hardlinksSameInode).toBe(true)
    expect(sourceBefore.hardlinkCount).toBe(2)
    evidence.source = {
      id: source.id,
      container: source.container_id,
      launch: sourceLaunchId,
      revision: sourceRevisionId,
      runtime: sourceProvenance?.actual_runtime,
      hashes: seed.hashes,
      logicalBytes: seed.logicalBytes,
      memberCount: seed.memberCount,
    }

    // 4. Stop S, take the offline backup, and prove the volume guard holds off starts.
    const stopped = await stopServer(request, adminToken, source.id)
    expect(stopped.status).toBe('stopped')
    expect(stopped.container_id).toBeNull()

    const backupRequest = await apiCall<BackupDto>(
      request,
      'POST',
      `/api/volumes/${state.volumeVId}/backups`,
      adminToken,
      {
        data: {
          request_id: newRequestId(),
          description: restoreDescription,
        },
        timeout: OPERATION_TIMEOUT_MS,
      }
    )
    expectStatus(backupRequest, 202, 'request volume backup')
    const backupId = backupRequest.body?.id
    expect(backupId).toBeTruthy()
    state.backupId = backupId ?? undefined

    const earlyBackup = await getBackup(request, adminToken, backupId as string)
    evidence.backupEarlyStatus = earlyBackup?.status
    if (earlyBackup && ['pending', 'in_progress'].includes(earlyBackup.status)) {
      const eligibility = await apiCall<{
        eligible: boolean
        reason_code: string | null
      }>(request, 'GET', `/api/volumes/${state.volumeVId}/backup-eligibility`, adminToken)
      expectStatus(eligibility, 200, 'backup eligibility while active')
      if (eligibility.body?.eligible) {
        // The tiny fixture helper can finish between the status read and this
        // eligibility read. In that case there is no active guard left to race.
        test.info().annotations.push({
          type: 'combined-race',
          description:
            'Backup completed before the exclusion probe; asserting the completed after-state instead.',
        })
      } else {
        expect(eligibility.body?.reason_code, 'active backup must exclude other volume work').toBe(
          'volume_busy'
        )

        const startAttempt = await apiCall<{ status: string }>(
          request,
          'POST',
          `/api/servers/${source.id}/start`,
          adminToken,
          {
            data: { reason: 'combined backup exclusion check' },
            timeout: SERVER_READY_TIMEOUT_MS,
          }
        )
        evidence.startDuringBackupStatus = startAttempt.status
        if (startAttempt.status === 409) {
          expect(
            apiErrorCode(startAttempt.body, startAttempt.text),
            'direct start must be rejected by the active exclusive volume operation'
          ).toBe('volume_busy')
          const unchanged = await getServer(request, adminToken, source.id)
          expect(unchanged?.status).toBe('stopped')
          expect(unchanged?.container_id).toBeNull()
        } else if (startAttempt.status === 200) {
          // The helper can finish between the eligibility and start requests.
          test.info().annotations.push({
            type: 'combined-race',
            description:
              'Backup completed before the start request; asserting the after-state instead.',
          })
          await waitForServer(request, adminToken, source.id, 'running')
          const stoppedAgain = await stopServer(request, adminToken, source.id)
          expect(stoppedAgain.status).toBe('stopped')
        } else {
          throw new Error(
            `Unexpected start-during-backup response: ${startAttempt.status} ${startAttempt.text}`
          )
        }
      }
    } else {
      test.info().annotations.push({
        type: 'combined-race',
        description: `Backup was already ${earlyBackup?.status ?? 'missing'} before the queue/start attempt; asserting the after-state instead.`,
      })
    }

    const completedBackup = await poll(
      `backup ${backupId} completion`,
      () => getBackup(request, adminToken, backupId as string),
      (value) =>
        value !== null && ['completed', 'failed', 'recovery_required'].includes(value.status),
      {
        timeoutMs: OPERATION_TIMEOUT_MS,
        intervalMs: POLL_INTERVAL_MS,
        describe: (value) => `status=${value?.status ?? 'missing'}`,
      }
    )
    expect(completedBackup?.status, completedBackup?.message).toBe('completed')
    expect(completedBackup?.can_restore).toBe(true)
    expect(completedBackup?.can_delete).toBe(true)
    expect(completedBackup?.completed_at).toBeTruthy()
    expect(
      completedBackup?.expires_at,
      'completed backup must retain retention metadata'
    ).toBeTruthy()
    expect(completedBackup?.compressed_bytes ?? 0).toBeGreaterThan(0)
    expect(completedBackup?.logical_bytes).toBe(seed.logicalBytes)
    expect(completedBackup?.member_count).toBe(seed.memberCount)
    expect(completedBackup?.source_volume_id).toBe(state.volumeVId)
    expect(completedBackup?.source_display_name).toBe(volumeVName)
    const backupText = JSON.stringify(completedBackup)
    for (const forbidden of [
      process.env.E2E_VOLUME_BACKUP_HOST_PATH,
      process.env.VOLUME_STORAGE_PATH,
      'archive.tar.gz',
      'backups/',
      'backup_path',
      'sha256',
    ]) {
      if (forbidden) expect(backupText).not.toContain(forbidden)
    }

    const hostArtifactRoot = process.env.E2E_VOLUME_BACKUP_HOST_PATH
    if (hostArtifactRoot) {
      try {
        const artifact = readArtifactEvidence(hostArtifactRoot, backupId as string)
        expect(artifact.digest, 'archive digest must match the completed metadata').toBe(
          artifact.completion.sha256
        )
        expect(artifact.completion.compressed_bytes).toBe(completedBackup?.compressed_bytes)
        expect(artifact.completion.logical_bytes).toBe(completedBackup?.logical_bytes)
        expect(artifact.completion.member_count).toBe(completedBackup?.member_count)
        evidence.artifact = {
          digest: artifact.digest,
          compressed: artifact.completion.compressed_bytes,
          logical: artifact.completion.logical_bytes,
          members: artifact.completion.member_count,
        }
      } catch (error) {
        test.info().annotations.push({
          type: 'combined-checksum',
          description: `Runner could not read the private artifact; checksum integrity is proven by the successful restore instead: ${String(error)}`,
        })
      }
    } else {
      test.info().annotations.push({
        type: 'combined-checksum',
        description:
          'E2E_VOLUME_BACKUP_HOST_PATH is unset; the public DTO omits the artifact digest, so successful checksum-verified restore is the integrity proof.',
      })
    }

    // Source data must not change during capture.
    await expectSeededContent(request, adminToken, state.volumeVId as string, seed)

    // 5. Move the template tag to B. The captured revision A must remain the recreation source.
    const updatedEnv = await apiCall<{ success: boolean; data: { id: string; image: string } }>(
      request,
      'PUT',
      `/api/environments/${state.envAId}`,
      adminToken,
      { data: { image: state.runtimeImageB } }
    )
    expectStatus(updatedEnv, 200, 'update environment A image to B')
    expect(updatedEnv.body?.data.image).toBe(state.runtimeImageB)
    const provenanceAfterUpdate = await apiCall<ProvenanceDto>(
      request,
      'GET',
      `/api/servers/${source.id}/provenance`,
      adminToken,
      { params: { launch_id: sourceLaunchId as string } }
    )
    expectStatus(provenanceAfterUpdate, 200, 'source provenance after template update')
    expect(provenanceAfterUpdate.body?.actual_runtime?.local_id).toBe(state.imageA)
    expect(provenanceAfterUpdate.body?.manifest?.revision_id).toBe(sourceRevisionId)
    expect(provenanceAfterUpdate.body?.can_recreate).toBe(true)

    // 6. Restore into a fresh private volume V2 and verify content/metadata.
    const restoreRequest = await apiCall<RestoreDto>(
      request,
      'POST',
      `/api/volume-backups/${backupId}/restore`,
      adminToken,
      {
        data: {
          request_id: newRequestId(),
          display_name: volumeV2Name,
          max_size_bytes: VOLUME_BYTES,
        },
        timeout: OPERATION_TIMEOUT_MS,
      }
    )
    expectStatus(restoreRequest, 202, 'request restore into V2')
    const restoreId = restoreRequest.body?.id
    const volumeV2Id = restoreRequest.body?.destination_volume_id
    expect(restoreId).toBeTruthy()
    expect(volumeV2Id).toBeTruthy()
    state.restoreId = restoreId ?? undefined
    if (restoreId) state.restoreIds.push(restoreId)
    state.volumeV2Id = volumeV2Id ?? undefined

    const completedRestore = await poll(
      `restore ${restoreId} completion`,
      () => getRestore(request, adminToken, restoreId as string),
      (value) =>
        value !== null && ['completed', 'failed', 'recovery_required'].includes(value.status),
      {
        timeoutMs: OPERATION_TIMEOUT_MS,
        intervalMs: POLL_INTERVAL_MS,
        describe: (value) => `status=${value?.status ?? 'missing'}`,
      }
    )
    expect(completedRestore?.status, completedRestore?.message).toBe('completed')
    expect(completedRestore?.destination_volume_id).toBe(volumeV2Id)
    expect(completedRestore?.destination_display_name).toBe(volumeV2Name)
    const restoreText = JSON.stringify(completedRestore)
    for (const forbidden of [
      process.env.E2E_VOLUME_BACKUP_HOST_PATH,
      process.env.VOLUME_STORAGE_PATH,
      'archive.tar.gz',
      'backups/',
      'destination_name',
    ]) {
      if (forbidden) expect(restoreText).not.toContain(forbidden)
    }

    const volumeV2 = await getVolume(request, adminToken, volumeV2Id as string)
    expect(volumeV2?.status).toBe('active')
    expect(volumeV2?.size_bytes).toBe(seed.logicalBytes)
    expect(volumeV2?.max_size_bytes).toBe(VOLUME_BYTES)
    expect(volumeV2?.display_name).toBe(volumeV2Name)

    const rootEntries = await listVolumeFiles(request, adminToken, volumeV2Id as string)
    expect(rootEntries.map((entry) => entry.name)).toEqual(
      expect.arrayContaining([
        seed.paths.dir,
        seed.paths.hello,
        seed.paths.hardlink,
        seed.paths.symlink,
        seed.paths.unicode,
      ])
    )
    expect(rootEntries.find((entry) => entry.name === seed.paths.dir)?.type).toBe('directory')
    expect(rootEntries.find((entry) => entry.name === seed.paths.unicode)?.type).toBe('file')
    const directoryEntries = await listVolumeFiles(
      request,
      adminToken,
      volumeV2Id as string,
      seed.paths.dir
    )
    expect(directoryEntries.map((entry) => entry.name)).toContain('nested.txt')
    const subEntries = await listVolumeFiles(
      request,
      adminToken,
      volumeV2Id as string,
      seed.paths.sub
    )
    expect(subEntries.map((entry) => entry.name)).toContain('deep.dat')
    await expectSeededContent(request, adminToken, volumeV2Id as string, seed)
    await expectSeededContent(request, adminToken, state.volumeVId as string, seed)

    evidence.restore = {
      id: restoreId,
      volume: volumeV2Id,
      status: completedRestore?.status,
    }

    // 7. Fill the pool, then queue a pinned recreation with explicit V2.
    const filler = await createServer(
      fillerName,
      state.smallPlanId as string,
      state.envFId as string,
      state.volumeVfId as string,
      '/filler-data'
    )
    expect(filler.status).toBe('running')
    expect(filler.allocated_cpu).toBe(2)

    const sourceDuringCapacity = await getServer(request, adminToken, source.id)
    expect(sourceDuringCapacity?.status).toBe('stopped')

    const balanceBeforeQueue = await getBalance(request, adminToken)
    const quotaBeforeQueue = await getQuota(request, adminToken)
    const volumesBeforeQueue = (await listVolumes(request, adminToken)).map((volume) => volume.id)

    const recreate = await apiCall<QueuedServerDto>(
      request,
      'POST',
      '/api/servers/recreate',
      adminToken,
      {
        data: {
          source_launch_id: sourceLaunchId,
          name: recreatedName,
          plan_id: state.planId,
          volume_mounts: [
            {
              volume_id: state.volumeV2Id,
              mount_path: MOUNT_PATH,
              mode: 'read_write',
              is_primary: true,
            },
          ],
        },
        timeout: SERVER_READY_TIMEOUT_MS,
      }
    )
    expectStatus(recreate, 202, 'queue pinned recreation')
    expect(recreate.body?.queued).toBe(true)
    expect(recreate.body?.queue_position ?? 0).toBeGreaterThanOrEqual(1)
    expect(recreate.body?.request.name).toBe(recreatedName)
    expect(recreate.body?.request.plan_id).toBe(state.planId)
    expect(recreate.body?.request.environment_id).toBe(state.envAId)
    expect(recreate.body?.request.resources).toMatchObject({
      cpu: 3,
      memory_mib: 6144,
      disk_mib: 30720,
      gpu_count: 0,
    })
    const recreationQueueId = recreate.body?.queue_id
    expect(recreationQueueId).toBeTruthy()
    trackQueue(recreationQueueId)
    // The public queue DTO intentionally hides the private launch payload
    // (revision identity and mount selection). Preservation is proven below by
    // the admitted server's provenance and its actual V2 mount, both of which
    // would differ if the mutable B tag or the source V had been re-selected.
    evidence.recreationQueue = {
      id: recreationQueueId,
      position: recreate.body?.queue_position,
      revision: sourceRevisionId,
      volume: state.volumeV2Id,
    }
    test.info().annotations.push({
      type: 'combined-queue-visibility',
      description:
        'The public queue DTO hides the private revision/volume payload. Revision and mount preservation are asserted by the admitted runtime A identity and V2 mount below.',
    })

    // A queued request must not create a server, volume, quota or credit side effect.
    const serversAfterQueue = await listOwnerServers(request, adminToken, adminUserId)
    expect(serversAfterQueue.filter((server) => server.name === recreatedName)).toEqual([])
    const volumesAfterQueue = (await listVolumes(request, adminToken)).map((volume) => volume.id)
    expect(new Set(volumesAfterQueue)).toEqual(new Set(volumesBeforeQueue))
    expect(await getBalance(request, adminToken)).toBe(balanceBeforeQueue)
    const quotaDuringQueue = await getQuota(request, adminToken)
    expect(quotaDuringQueue.usage).toEqual(quotaBeforeQueue.usage)
    const queueDetail = await getQueue(request, adminToken, recreationQueueId as string)
    expect(queueDetail?.status).toBe('pending')
    expect(queueDetail?.reason_code).toBe('capacity_wait')
    expect(queueDetail?.can_cancel).toBe(true)

    // 8. Durable owner queue visibility plus a rendered queue assertion.
    const ownerQueue = await apiCall<{ items: QueueEntryDto[]; total: number }>(
      request,
      'GET',
      '/api/server-queue',
      adminToken,
      { params: { status: 'pending', page: 1, page_size: 25 } }
    )
    expectStatus(ownerQueue, 200, 'owner pending queue')
    expect(ownerQueue.body?.items.map((entry) => entry.id)).toContain(recreationQueueId)

    await loginAsAdmin(page)
    await page.goto(`/servers?tab=queue&request=${recreationQueueId}`)
    const queueCard = page.getByTestId(`queue-request-${recreationQueueId}`).first()
    await expect(queueCard).toBeVisible({ timeout: 30_000 })
    await expect(queueCard).toContainText(recreatedName)
    await expect(queueCard).toContainText('Waiting')

    // A second non-admin user cannot discover, read, cancel or inspect owner recovery metadata.
    const secondUsername = uniqueName('combined-user')
    const secondPassword = 'Combined!Pass123'
    const secondUser = await apiCall<{ id: string; username: string }>(
      request,
      'POST',
      '/api/users/',
      adminToken,
      {
        data: {
          username: secondUsername,
          email: `${secondUsername}@combined.test`,
          password: secondPassword,
          role: 'user',
          first_name: 'Combined',
          last_name: 'Probe',
        },
      }
    )
    expectStatus(secondUser, 201, 'create second user')
    state.userId = secondUser.body?.id
    expect(state.userId).toBeTruthy()
    const secondToken = await apiLogin(request, secondUsername, secondPassword)

    const foreignQueue = await apiCall<{ items: QueueEntryDto[]; total: number }>(
      request,
      'GET',
      '/api/server-queue',
      secondToken
    )
    expectStatus(foreignQueue, 200, 'foreign queue list')
    expect(foreignQueue.body?.items).toEqual([])
    expect(foreignQueue.body?.total).toBe(0)
    const foreignQueueDetail = await apiCall(
      request,
      'GET',
      `/api/server-queue/${recreationQueueId}`,
      secondToken
    )
    expect(foreignQueueDetail.status).toBe(404)
    expect(apiErrorCode(foreignQueueDetail.body, foreignQueueDetail.text)).toBe('request_not_found')
    const foreignCancel = await apiCall(
      request,
      'POST',
      `/api/server-queue/${recreationQueueId}/cancel`,
      secondToken
    )
    expect(foreignCancel.status).toBe(404)
    expect(apiErrorCode(foreignCancel.body, foreignCancel.text)).toBe('request_not_found')

    const foreignBackup = await apiCall(
      request,
      'GET',
      `/api/volume-backups/${backupId}`,
      secondToken
    )
    expect([403, 404]).toContain(foreignBackup.status)
    expect(foreignBackup.text).not.toContain(volumeVName)
    expect(foreignBackup.text).not.toContain(volumeV2Name)
    const foreignRestore = await apiCall(
      request,
      'GET',
      `/api/volume-restores/${restoreId}`,
      secondToken
    )
    expect([403, 404]).toContain(foreignRestore.status)
    expect(foreignRestore.text).not.toContain(volumeV2Name)
    const foreignBackups = await apiCall<{ items: BackupDto[] }>(
      request,
      'GET',
      '/api/volume-backups',
      secondToken
    )
    if (foreignBackups.status === 200) {
      expect(foreignBackups.body?.items ?? []).toEqual([])
    } else {
      expect([403, 404]).toContain(foreignBackups.status)
    }

    // Re-read the owner queue after the privacy checks to prove it is durable and uncharged.
    const durableQueue = await getQueue(request, adminToken, recreationQueueId as string)
    expect(durableQueue?.status).toBe('pending')
    expect(await getBalance(request, adminToken)).toBe(balanceBeforeQueue)

    // 9. Release filler capacity and wait for exactly one admission.
    await deleteServer(request, adminToken, filler.id)
    const admittedQueue = await poll(
      `queue ${recreationQueueId} admission`,
      () => getQueue(request, adminToken, recreationQueueId as string),
      (value) => value !== null && ['started', 'failed', 'cancelled'].includes(value.status),
      {
        timeoutMs: QUEUE_ADMISSION_TIMEOUT_MS,
        intervalMs: POLL_INTERVAL_MS,
        describe: (value) => `status=${value?.status ?? 'missing'}`,
      }
    )
    expect(admittedQueue?.status, admittedQueue?.message).toBe('started')
    const recreatedServerId = admittedQueue?.server_id
    expect(recreatedServerId).toBeTruthy()
    trackServer(recreatedServerId)
    const recreatedServer = await waitForServer(
      request,
      adminToken,
      recreatedServerId as string,
      'running'
    )
    expect(recreatedServer.name).toBe(recreatedName)
    expect(recreatedServer.container_id).toBeTruthy()
    expect(recreatedServer.plan_id).toBe(state.planId)
    expect(recreatedServer.environment_id).toBe(state.envAId)
    expect(recreatedServer.allocated_cpu).toBe(3)
    expect(recreatedServer.allocated_memory).toBe('6g')
    expect(recreatedServer.allocated_disk).toBe('30g')
    expect(recreatedServer.volume_mounts).toEqual([
      expect.objectContaining({
        volume_id: state.volumeV2Id,
        mount_path: MOUNT_PATH,
        mode: 'read_write',
        is_primary: true,
      }),
    ])

    const namedServers = (await listOwnerServers(request, adminToken, adminUserId)).filter(
      (server) => server.name === recreatedName
    )
    expect(namedServers).toHaveLength(1)
    expect(namedServers[0].id).toBe(recreatedServerId)
    const runtimeContainers = containersForServer(recreatedServerId as string)
    expect(runtimeContainers).toHaveLength(1)
    expect(runtimeContainers[0]).toBe(recreatedServer.container_id)
    expect(containerImageIdentity(recreatedServer.container_id as string)).toBe(state.imageA)
    expect(containerImageIdentity(recreatedServer.container_id as string)).not.toBe(state.imageB)
    // Queue admission runs in celery-worker; it must apply the same runtime
    // hardening contract as API-created servers (PENT-NKL-018).
    expect(inspectContainerHardening(recreatedServer.container_id as string)).toMatchObject({
      user: '65532:65532',
      capDrop: ['ALL'],
      readonlyRootfs: true,
      securityOpt: expect.arrayContaining(['no-new-privileges:true']),
    })

    const recreatedProvenance = await apiCall<ProvenanceDto>(
      request,
      'GET',
      `/api/servers/${recreatedServerId}/provenance`,
      adminToken
    )
    expectStatus(recreatedProvenance, 200, 'recreated provenance')
    expect(recreatedProvenance.body?.state).toBe('recorded')
    expect(recreatedProvenance.body?.actual_runtime?.local_id).toBe(state.imageA)
    expect(recreatedProvenance.body?.actual_runtime?.local_id).not.toBe(state.imageB)
    expect(recreatedProvenance.body?.manifest?.revision_id).toBe(sourceRevisionId)
    expect(recreatedProvenance.body?.manifest?.volume_requirements).toEqual([
      expect.objectContaining({ mount_path: MOUNT_PATH, mode: 'read_write' }),
    ])

    const restoredInspection = inspectVolume(recreatedServer.container_id as string, seed)
    expect(restoredInspection.hashes).toEqual(seed.hashes)
    for (const relativePath of [
      seed.paths.hello,
      seed.paths.nested,
      seed.paths.deep,
      seed.paths.unicode,
      seed.paths.hardlink,
    ]) {
      expect(restoredInspection.entries[relativePath]?.mode, `restored mode ${relativePath}`).toBe(
        0o600
      )
      expect(restoredInspection.entries[relativePath]?.uid, `restored uid ${relativePath}`).toBe(
        65532
      )
      expect(restoredInspection.entries[relativePath]?.gid, `restored gid ${relativePath}`).toBe(
        65532
      )
    }
    for (const relativePath of [seed.paths.dir, seed.paths.sub]) {
      expect(
        restoredInspection.entries[relativePath]?.mode,
        `restored dir mode ${relativePath}`
      ).toBe(0o700)
      expect(
        restoredInspection.entries[relativePath]?.uid,
        `restored dir uid ${relativePath}`
      ).toBe(65532)
    }
    expect(restoredInspection.symlinkTarget).toBe(seed.paths.hello)
    expect(restoredInspection.hardlinksSameInode).toBe(true)
    expect(restoredInspection.hardlinkCount).toBe(2)
    await expectSeededContent(request, adminToken, state.volumeV2Id as string, seed)

    const quotaAfterAdmission = await getQuota(request, adminToken)
    expect(quotaAfterAdmission.usage.servers).toBe(quotaBeforeQueue.usage.servers)
    expect(quotaAfterAdmission.usage.cpu - quotaBeforeQueue.usage.cpu).toBe(3 - 2)
    expect(quotaAfterAdmission.usage.memory_mb - quotaBeforeQueue.usage.memory_mb).toBe(6144 - 4096)
    expect(quotaAfterAdmission.usage.disk_mb).toBe(quotaBeforeQueue.usage.disk_mb)
    expect(quotaAfterAdmission.usage.gpu).toBe(quotaBeforeQueue.usage.gpu)
    const balanceAfterAdmission = await getBalance(request, adminToken)
    expect(balanceAfterAdmission, 'no wait charge or duplicate debit during admission').toBe(
      balanceBeforeQueue
    )
    const volumesAfterAdmission = (await listVolumes(request, adminToken)).map(
      (volume) => volume.id
    )
    expect(new Set(volumesAfterAdmission)).toEqual(new Set(volumesBeforeQueue))

    evidence.admission = {
      queue: recreationQueueId,
      server: recreatedServerId,
      runtime: recreatedProvenance.body?.actual_runtime?.local_id,
      containers: runtimeContainers,
      quotaBefore: quotaBeforeQueue.usage,
      quotaAfter: quotaAfterAdmission.usage,
      balanceBefore: balanceBeforeQueue,
      balanceAfter: balanceAfterAdmission,
    }

    // 12. Real browser detail page: provenance and restored mount are rendered from the API.
    // The detail route reads the owner server list; refresh its short-lived cache
    // through the real activity endpoint before opening the page.
    const activity = await apiCall(
      request,
      'POST',
      `/api/servers/${recreatedServerId}/activity`,
      adminToken
    )
    expectStatus(activity, 200, 'refresh owner server list before UI check')
    await page.goto(`/servers/${recreatedServerId}`)
    await expect(page.getByRole('heading', { name: 'Environment details' })).toBeVisible({
      timeout: 30_000,
    })
    await expect(
      page.getByText(/Last verified launch · current server status: running/)
    ).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(/Verified generation: 1/)).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(state.imageA as string).first()).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('heading', { name: 'Volume Mounts' })).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.getByText(volumeV2Name, { exact: false }).first()).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.getByText(MOUNT_PATH, { exact: true }).first()).toBeVisible({
      timeout: 30_000,
    })
    await expect(page.getByText('RW', { exact: true }).first()).toBeVisible({ timeout: 30_000 })
    evidence.ui = {
      server: recreatedServerId,
      provenanceLabel: 'Last verified launch',
      runtimeLabel: state.imageA,
      volume: volumeV2Name,
      mount: MOUNT_PATH,
    }

    // 10. Cancellation drill while capacity is full again.
    await stopServer(request, adminToken, recreatedServer.id)
    const filler2 = await createServer(
      fillerName,
      state.smallPlanId as string,
      state.envFId as string,
      state.volumeVfId as string,
      '/filler-data'
    )
    expect(filler2.status).toBe('running')

    const pendingRequest = await apiCall<QueuedServerDto>(
      request,
      'POST',
      '/api/servers/',
      adminToken,
      {
        data: {
          name: cancelName,
          plan_id: state.planId,
          environment_id: state.envFId,
          volume_mounts: [
            { volume_id: state.volumeV2Id, mount_path: MOUNT_PATH, mode: 'read_write' },
          ],
        },
        timeout: SERVER_READY_TIMEOUT_MS,
      }
    )
    expectStatus(pendingRequest, 202, 'queue cancellation drill request')
    const cancelQueueId = pendingRequest.body?.queue_id
    expect(cancelQueueId).toBeTruthy()
    trackQueue(cancelQueueId)
    const cancelResult = await apiCall<QueueEntryDto>(
      request,
      'POST',
      `/api/server-queue/${cancelQueueId}/cancel`,
      adminToken
    )
    expectStatus(cancelResult, 200, 'cancel pending request')
    expect(cancelResult.body?.status).toBe('cancelled')
    expect(cancelResult.body?.can_cancel).toBe(false)
    expect(
      (await listOwnerServers(request, adminToken, adminUserId)).filter(
        (server) => server.name === cancelName
      )
    ).toEqual([])

    const raceRequest = await apiCall<QueuedServerDto>(
      request,
      'POST',
      '/api/servers/',
      adminToken,
      {
        data: {
          name: raceName,
          plan_id: state.planId,
          environment_id: state.envFId,
          volume_mounts: [
            { volume_id: state.volumeV2Id, mount_path: MOUNT_PATH, mode: 'read_write' },
          ],
        },
        timeout: SERVER_READY_TIMEOUT_MS,
      }
    )
    expectStatus(raceRequest, 202, 'queue cancel/claim race request')
    const raceQueueId = raceRequest.body?.queue_id
    expect(raceQueueId).toBeTruthy()
    trackQueue(raceQueueId)

    const [deleteFillerResult, cancelRaceResult] = await Promise.all([
      apiCall<{ message: string }>(request, 'DELETE', `/api/servers/${filler2.id}`, adminToken, {
        timeout: SERVER_READY_TIMEOUT_MS,
      }),
      apiCall<QueueEntryDto>(
        request,
        'POST',
        `/api/server-queue/${raceQueueId}/cancel`,
        adminToken
      ),
    ])
    expect([200, 204]).toContain(deleteFillerResult.status)
    expect([200, 409]).toContain(cancelRaceResult.status)
    if (cancelRaceResult.status === 200) {
      expect(cancelRaceResult.body?.status).toBe('cancelled')
    } else {
      expect(apiErrorCode(cancelRaceResult.body, cancelRaceResult.text)).toBe('launch_in_progress')
    }

    const raceEntry = await poll(
      `queue ${raceQueueId} cancel/claim terminal state`,
      () => getQueue(request, adminToken, raceQueueId as string),
      (entry) => entry !== null && ['started', 'cancelled', 'failed'].includes(entry.status),
      {
        timeoutMs: QUEUE_ADMISSION_TIMEOUT_MS,
        intervalMs: POLL_INTERVAL_MS,
        describe: (entry) => `status=${entry?.status ?? 'missing'}`,
      }
    )
    expect(raceEntry?.status, raceEntry?.message).not.toBe('failed')
    const raceServers = (await listOwnerServers(request, adminToken, adminUserId)).filter(
      (server) => server.name === raceName
    )
    if (raceEntry?.status === 'cancelled') {
      expect(raceServers, 'a cancelled request must never create a server').toEqual([])
    } else {
      expect(raceEntry?.status).toBe('started')
      expect(raceServers).toHaveLength(1)
      trackServer(raceServers[0].id)
      const raceServer = await waitForServer(request, adminToken, raceServers[0].id, 'running')
      expect(raceServer.plan_id).toBe(state.planId)
      await deleteServer(request, adminToken, raceServer.id)
    }
    evidence.cancelClaim = {
      cancelledQueue: cancelQueueId,
      raceQueue: raceQueueId,
      raceResult: raceEntry?.status,
      raceServers: raceServers.map((server) => server.id),
    }

    console.log(JSON.stringify({ scope: 'combined-evidence', ...evidence }))
    test.info().annotations.push({
      type: 'combined-evidence',
      description: JSON.stringify(evidence),
    })
  })

  test('@combined corrupted backup artifact fails restore without source or destination writes', async ({
    request,
  }) => {
    test.setTimeout(5 * 60_000)
    const hostRoot = process.env.E2E_VOLUME_BACKUP_HOST_PATH
    if (!hostRoot) {
      test.skip(
        true,
        'E2E_VOLUME_BACKUP_HOST_PATH is unset; the corrupt-artifact drill is skipped.'
      )
      return
    }
    if (!state.adminToken || !state.backupId || !state.volumeVId || !state.seed) {
      test.skip(
        true,
        'The main combined scenario did not retain a completed backup and source volume.'
      )
      return
    }
    const adminToken = state.adminToken
    const backupId = state.backupId
    const sourceVolumeId = state.volumeVId
    const seed = state.seed

    const completed = await getBackup(request, adminToken, backupId)
    if (!completed || completed.status !== 'completed') {
      test.skip(
        true,
        `Backup ${backupId} is not completed (${completed?.status ?? 'missing'}); corrupt-artifact drill skipped.`
      )
      return
    }

    // A configured backup root is part of the CI contract. If the artifact is
    // still unreadable through the runner/daemon fallback, fail instead of
    // silently dropping the required corruption drill.
    const artifact = readArtifactEvidence(hostRoot, backupId)
    expect(artifact.digest).toBe(artifact.completion.sha256)

    const tempRoot = mkdtempSync(path.join(tmpdir(), 'nukelab-combined-artifact-'))
    state.artifactTempDir = tempRoot
    const beforeCopy = copyArtifactDirectory(hostRoot, backupId, path.join(tempRoot, 'backup'))
    corruptArtifact(hostRoot, backupId)

    const restoreRequest = await apiCall<RestoreDto>(
      request,
      'POST',
      `/api/volume-backups/${backupId}/restore`,
      adminToken,
      {
        data: {
          request_id: newRequestId(),
          display_name: uniqueName('Combined corrupt restore'),
          max_size_bytes: VOLUME_BYTES,
        },
        timeout: OPERATION_TIMEOUT_MS,
      }
    )
    expectStatus(restoreRequest, 202, 'request restore from corrupted artifact')
    const corruptRestoreId = restoreRequest.body?.id
    const corruptDestinationId = restoreRequest.body?.destination_volume_id
    expect(corruptRestoreId).toBeTruthy()
    expect(corruptDestinationId).toBeTruthy()
    if (corruptRestoreId) state.restoreIds.push(corruptRestoreId)
    state.failedDestinationVolumeId = corruptDestinationId ?? undefined

    const failedRestore = await poll(
      `corrupted restore ${corruptRestoreId} failure`,
      () => getRestore(request, adminToken, corruptRestoreId as string),
      (value) =>
        value !== null && ['failed', 'completed', 'recovery_required'].includes(value.status),
      {
        timeoutMs: OPERATION_TIMEOUT_MS,
        intervalMs: POLL_INTERVAL_MS,
        describe: (value) => `status=${value?.status ?? 'missing'}`,
      }
    )
    expect(failedRestore?.status, 'a corrupted artifact must never restore successfully').toBe(
      'failed'
    )
    expect(['helper_failed', 'artifact_corrupt']).toContain(failedRestore?.reason_code)
    expect(failedRestore?.destination_volume_id).toBe(corruptDestinationId)

    const destination = await getVolume(request, adminToken, corruptDestinationId as string)
    expect(destination?.status).toBe('restore_failed')
    expect(destination?.size_bytes).toBe(0)
    const destinationFiles = await apiCall(
      request,
      'GET',
      `/api/volumes/${corruptDestinationId}/files`,
      adminToken
    )
    expect(destinationFiles.status).toBe(409)
    expect(apiErrorCode(destinationFiles.body, destinationFiles.text)).toBe('volume_busy')

    // Source V must not be mutated by a failed restore.
    await expectSeededContent(request, adminToken, sourceVolumeId, seed)

    console.log(
      JSON.stringify({
        scope: 'combined-corrupt-artifact',
        backup: backupId,
        restore: corruptRestoreId,
        destination: corruptDestinationId,
        reason: failedRestore?.reason_code,
        copiedArtifact: beforeCopy,
      })
    )
    test.info().annotations.push({
      type: 'combined-corrupt-artifact',
      description: JSON.stringify({
        backup: backupId,
        restore: corruptRestoreId,
        destination: corruptDestinationId,
        reason: failedRestore?.reason_code,
      }),
    })
  })
})
