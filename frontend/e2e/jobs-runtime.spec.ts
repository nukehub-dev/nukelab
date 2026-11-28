// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Real-stack batch-job runtime acceptance.
 *
 * Exercises the real API, PostgreSQL, Redis, Celery, Docker and the seeded
 * local-identity environment revision. No routes are mocked. Capacity
 * occupation is enabled with E2E_JOBS_CAPACITY=1 against a dedicated stack
 * whose RESOURCE_POOL_CPU matches the seeded filler plan.
 */

import { createHash } from 'node:crypto'
import { test, expect, type APIRequestContext } from '@playwright/test'
import {
  loginAsAdmin,
  apiCall,
  apiErrorCode,
  apiLogin,
  dockerImageId,
  sleep,
} from './helpers/combined-fixtures'
import {
  createTestUser,
  deleteServerEventually,
  deleteUser,
  deleteVolumeWhenDetached,
  getPlanBySlug,
  TEST_USER_PASSWORD,
  waitForServerStatus,
} from './helpers/api'
import {
  JOBS_FILLER_PLAN_SLUG,
  JOBS_PAID_PLAN_SLUG,
  JOBS_PLAN_SLUG,
  cancelJob,
  downloadVolumeText,
  findSeededEnvironment,
  findSeededRevision,
  getJob,
  getJobCapabilities,
  getJobLogs,
  inspectJobContainer,
  jobContainerIds,
  listJobs,
  seedJobVolume,
  submitJob,
  waitForJobState,
  waitForJobTerminal,
  waitForNoJobContainers,
  type JobCapabilities,
  type JobDetail,
} from './helpers/jobs-fixtures'
import { uniqueName } from './helpers/runtime'

const JOBS_RUNTIME_ENABLED = ['1', 'true'].includes(process.env.E2E_JOBS_RUNTIME ?? '')
const CAPACITY_ENABLED = ['1', 'true'].includes(process.env.E2E_JOBS_CAPACITY ?? '')
const EXTERNAL_SERVER = ['1', 'true'].includes(process.env.E2E_EXTERNAL_SERVER ?? '')
const MAIN_TIMEOUT_MS = 20 * 60_000
const CLEANUP_TIMEOUT_MS = 5 * 60_000
const SERVER_READY_TIMEOUT_MS = 180_000
const VOLUME_BYTES = 256 * 1024 * 1024
const INPUT_NAME = 'job-input.txt'
const OUTPUT_NAME = 'job-output.txt'

interface CreditsResponse {
  balance: number
  summary: {
    current_balance: number
    held: number
    spendable: number
  }
}

interface JobsRuntimeState {
  adminToken?: string
  adminUserId?: string
  stamp: string
  runtimeImage?: string
  imageId?: string
  planId?: string
  fillerPlanId?: string
  paidPlanId?: string
  fillerCpu?: number
  environmentId?: string
  revisionId?: string
  volumeId?: string
  volumeName?: string
  fillerServerId?: string
  secondUserId?: string
  jobIds: string[]
}

const state: JobsRuntimeState = { stamp: uniqueName('jobs-runtime'), jobIds: [] }

function trackJob(job: JobDetail | null | undefined): string {
  if (!job?.id) throw new Error('Job response had no identity')
  if (!state.jobIds.includes(job.id)) state.jobIds.push(job.id)
  return job.id
}

function expectStatus(
  result: { status: number; text: string },
  expected: number,
  label: string
): void {
  expect(result.status, `${label} response: ${result.text.slice(0, 500)}`).toBe(expected)
}

async function submit(
  request: APIRequestContext,
  token: string,
  body: {
    name: string
    revision_id: string
    plan_id: string
    volume_id: string
    argv: string[]
    max_runtime_seconds: number
  },
  key: string
) {
  return submitJob(request, token, body, key)
}

test.describe('@jobs-runtime batch job', () => {
  test.skip(
    !JOBS_RUNTIME_ENABLED,
    'Set E2E_JOBS_RUNTIME=1 against a disposable job-enabled stack to run the batch job scenario.'
  )
  test.skip(
    !EXTERNAL_SERVER,
    'The @jobs-runtime scenario requires E2E_EXTERNAL_SERVER=1 and a prestarted stack.'
  )
  // This is a stateful, expensive acceptance run. A silent retry would leave a
  // second runtime and volume behind and could mask a one-shot guard race.
  test.describe.configure({ mode: 'serial', retries: 0 })

  test.beforeAll(async ({ request }) => {
    if (!JOBS_RUNTIME_ENABLED || !EXTERNAL_SERVER) return
    test.setTimeout(MAIN_TIMEOUT_MS)
    if (!process.env.E2E_RUNTIME_IMAGE) {
      throw new Error('E2E_RUNTIME_IMAGE is required for the @jobs-runtime scenario')
    }
    state.runtimeImage = process.env.E2E_RUNTIME_IMAGE
    state.adminToken = await apiLogin(
      request,
      process.env.TEST_ADMIN_USERNAME || 'admin',
      process.env.TEST_ADMIN_PASSWORD || 'admin123'
    )
    const profile = await apiCall<{ id: string }>(
      request,
      'GET',
      '/api/users/me/profile',
      state.adminToken
    )
    expectStatus(profile, 200, 'admin profile')
    state.adminUserId = profile.body?.id
    expect(state.adminUserId).toBeTruthy()

    const plan = await getPlanBySlug(request, state.adminToken, JOBS_PLAN_SLUG)
    state.planId = plan.id
    const fillerPlan = await getPlanBySlug(request, state.adminToken, JOBS_FILLER_PLAN_SLUG)
    state.fillerPlanId = fillerPlan.id
    state.fillerCpu = fillerPlan.cpu_limit
    try {
      const paidPlan = await getPlanBySlug(request, state.adminToken, JOBS_PAID_PLAN_SLUG)
      state.paidPlanId = paidPlan.id
    } catch {
      state.paidPlanId = undefined
    }

    const environment = await findSeededEnvironment(
      request,
      state.adminToken,
      state.runtimeImage as string
    )
    state.environmentId = environment.id
    const revision = await findSeededRevision(request, state.adminToken, environment.id)
    expect(revision.supports_jobs).toBe(true)
    state.revisionId = revision.revision_id
    state.imageId = dockerImageId(state.runtimeImage as string)

    const volume = await apiCall<{
      id: string
      name: string
      display_name: string
      owner_id: string
      status: string
    }>(request, 'POST', '/api/volumes/', state.adminToken, {
      data: {
        display_name: `Jobs runtime ${state.stamp}`,
        description: 'Disposable batch job output volume',
        max_size_bytes: VOLUME_BYTES,
      },
    })
    expectStatus(volume, 201, 'create job volume')
    if (!volume.body?.id || !volume.body.name) {
      throw new Error(`Volume create returned no identity: ${volume.text}`)
    }
    state.volumeId = volume.body.id
    state.volumeName = volume.body.name
    expect(volume.body.owner_id).toBe(state.adminUserId)
    expect(volume.body.status).toBe('active')

    const input = `jobs-runtime-input-${state.stamp}\n`
    seedJobVolume(state.volumeName, state.runtimeImage as string, INPUT_NAME, input)
    expect(
      await downloadVolumeText(
        request,
        state.adminToken,
        state.volumeId,
        INPUT_NAME,
        state.volumeName
      )
    ).toBe(input)
  })

  test.afterAll(async ({ request }) => {
    test.setTimeout(CLEANUP_TIMEOUT_MS)
    let token: string | undefined = state.adminToken
    if (!token) {
      try {
        token = await apiLogin(
          request,
          process.env.TEST_ADMIN_USERNAME || 'admin',
          process.env.TEST_ADMIN_PASSWORD || 'admin123'
        )
      } catch (error) {
        console.warn(`[jobs cleanup] admin login failed: ${String(error)}`)
      }
    }
    if (token) {
      for (const jobId of state.jobIds) {
        try {
          const current = await getJob(request, token, jobId)
          if (
            current.status === 200 &&
            current.body &&
            !['succeeded', 'failed', 'cancelled', 'timed_out', 'expired'].includes(
              current.body.state
            )
          ) {
            await cancelJob(request, token, jobId)
            await waitForJobTerminal(request, token, jobId, 120_000).catch((error) => {
              console.warn(`[jobs cleanup] job ${jobId} did not settle: ${String(error)}`)
            })
          }
        } catch (error) {
          console.warn(`[jobs cleanup] job ${jobId}: ${String(error)}`)
        }
      }
      if (state.fillerServerId) {
        try {
          await deleteServerEventually(request, token, state.fillerServerId)
        } catch (error) {
          console.warn(`[jobs cleanup] filler server: ${String(error)}`)
        }
      }
      if (state.volumeId) {
        try {
          await deleteVolumeWhenDetached(request, token, state.volumeId)
        } catch (error) {
          console.warn(`[jobs cleanup] volume ${state.volumeId}: ${String(error)}`)
        }
      }
      if (state.secondUserId) {
        try {
          await deleteUser(request, token, state.secondUserId)
        } catch (error) {
          console.warn(`[jobs cleanup] second user: ${String(error)}`)
        }
      }
    }
    console.log(
      JSON.stringify({
        scope: 'jobs-runtime-cleanup',
        jobs: state.jobIds,
        volume: state.volumeId,
        filler_server: state.fillerServerId,
        user: state.secondUserId,
      })
    )
  })

  test('runs a zero-cost CPU job, proves the hardened runtime, then isolates, fails, cancels and cleans up', async ({
    request,
    page,
  }) => {
    test.setTimeout(MAIN_TIMEOUT_MS)
    if (!state.adminToken || !state.planId || !state.environmentId || !state.volumeId) {
      throw new Error('Batch job fixtures were not initialized')
    }
    const token = state.adminToken
    const capabilities: JobCapabilities = await getJobCapabilities(request, token)
    expect(capabilities.enabled).toBe(true)
    expect(capabilities.can_submit).toBe(true)
    expect(['zero_cost', 'paid']).toContain(capabilities.billing_mode)
    expect(capabilities.secrets_enabled).toBe(false)
    expect(capabilities.limits.log_tail_bytes).toBeGreaterThan(0)

    // ── Occupy the last slot, then queue the real job ──────────────────────
    if (CAPACITY_ENABLED) {
      const poolCpu = Number(process.env.RESOURCE_POOL_CPU)
      if (!Number.isFinite(poolCpu) || poolCpu <= 0) {
        throw new Error('E2E_JOBS_CAPACITY=1 requires a numeric RESOURCE_POOL_CPU')
      }
      expect(state.fillerCpu).toBe(poolCpu)
      const fillerName = uniqueName('jobs-runtime-filler')
      const filler = await apiCall<{ id: string; status: string; allocated_cpu?: number }>(
        request,
        'POST',
        '/api/servers/',
        token,
        {
          data: {
            name: fillerName,
            plan_id: state.fillerPlanId,
            environment_id: state.environmentId,
          },
          timeout: SERVER_READY_TIMEOUT_MS,
        }
      )
      if (filler.status === 202) {
        throw new Error(
          `Capacity filler was queued instead of starting; the stack is not dedicated: ${filler.text.slice(0, 500)}`
        )
      }
      expectStatus(filler, 200, 'create capacity filler')
      if (!filler.body?.id) throw new Error('Capacity filler returned no server identity')
      state.fillerServerId = filler.body.id
      const fillerServer = await waitForServerStatus(
        request,
        token,
        state.fillerServerId,
        'running',
        { timeoutMs: SERVER_READY_TIMEOUT_MS }
      )
      expect(fillerServer.allocated_cpu).toBe(poolCpu)
      test.info().annotations.push({
        type: 'jobs-capacity',
        description: `Occupied the full ${poolCpu}-CPU pool with interactive server ${state.fillerServerId}.`,
      })
    } else {
      test.info().annotations.push({
        type: 'jobs-capacity',
        description:
          'E2E_JOBS_CAPACITY is unset; queued/no-container-before-admission assertions are skipped. CI sets it.',
      })
    }

    const input = `jobs-runtime-input-${state.stamp}\n`
    const inputHash = createHash('sha256').update(input).digest('hex')
    const outputPrefix = `jobs-runtime-output-${state.stamp}`
    const jobScript = [
      'set -eu',
      'sleep 25',
      `printf '%s\\n' '${outputPrefix}' > /work/${OUTPUT_NAME}`,
      `printf '%s\\n' '${inputHash}' >> /work/${OUTPUT_NAME}`,
      `cat /work/${INPUT_NAME} >> /work/${OUTPUT_NAME}`,
      `echo 'job-stdout-${state.stamp}'`,
    ].join('\n')
    const expectedOutput = `${outputPrefix}\n${inputHash}\n${input}`
    const primaryBody = {
      name: uniqueName('jobs-runtime-primary'),
      revision_id: state.revisionId as string,
      plan_id: state.planId,
      volume_id: state.volumeId,
      argv: ['/bin/sh', '-c', jobScript],
      max_runtime_seconds: 120,
    }
    const primaryKey = `jobs-runtime-${state.stamp}-primary`
    const primary = await submit(request, token, primaryBody, primaryKey)
    expectStatus(primary, 202, 'submit primary job')
    const primaryId = trackJob(primary.body)
    expect(primary.body?.state).toBe('queued')
    expect(primary.body?.billing).toMatchObject({
      mode: 'zero_cost',
      charged: 0,
      authorized: 0,
      rate_per_hour: 0,
      state: 'none',
      unpaid: 0,
    })
    expect(primary.body?.argv).toEqual(primaryBody.argv)
    expect(primary.body?.environment.revision_id).toBe(state.revisionId)
    expect(primary.body?.plan.id).toBe(state.planId)
    expect(primary.body?.volume.id).toBe(state.volumeId)

    // Idempotent replay returns the same durable row, not a second job.
    const replay = await submit(request, token, primaryBody, primaryKey)
    expectStatus(replay, 200, 'replay primary job')
    expect(replay.body?.id).toBe(primaryId)
    expect(replay.body?.replayed).toBe(true)
    const afterReplayJobs = await listJobs(request, token, 'all')
    expectStatus(afterReplayJobs, 200, 'list jobs after replay')
    expect(
      afterReplayJobs.body?.items.filter((item) => item.name === primaryBody.name)
    ).toHaveLength(1)

    if (CAPACITY_ENABLED) {
      const queued = await waitForJobState(request, token, primaryId, ['queued'], 60_000)
      expect(queued.state).toBe('queued')
      expect(queued.reason_code).toBe('waiting_capacity')
      const active = await listJobs(request, token, 'active')
      expectStatus(active, 200, 'list active jobs')
      expect(active.body?.items.map((item) => item.id)).toContain(primaryId)

      // No workload runtime may exist before admission commits capacity.
      await sleep(6_000)
      const stillQueued = await getJob(request, token, primaryId)
      expectStatus(stillQueued, 200, 'read queued job')
      expect(stillQueued.body?.state).toBe('queued')
      expect(jobContainerIds(primaryId)).toEqual([])

      // The real UI reads the same queued row through the real API.
      await loginAsAdmin(page)
      await page.goto('/jobs')
      const row = page.getByTestId(`job-row-${primaryId}`)
      await expect(row).toBeVisible({ timeout: 30_000 })
      await expect(row).toContainText('Queued')
      await expect(row).toContainText('Waiting for available CPU and memory capacity')

      await deleteServerEventually(request, token, state.fillerServerId as string)
      state.fillerServerId = undefined
    } else {
      await sleep(2_000)
    }

    // ── Admitted runtime evidence ──────────────────────────────────────────
    // The fixture sleeps before writing its result so the runner can inspect
    // exactly one admitted workload container. A job that exits before this
    // point is a fixture failure, not a reason to skip the runtime proof.
    const admitted = await waitForJobState(request, token, primaryId, ['running'], 180_000)
    expect(admitted.state).toBe('running')
    const containers = jobContainerIds(primaryId)
    expect(containers, 'exactly one admitted workload container').toHaveLength(1)
    const inspection = inspectJobContainer(containers[0])
    expect(inspection.name).toBe(`nukelab-job-${primaryId}`)
    expect(inspection.image).toBe(state.imageId)
    expect(inspection.labels['nukelab.workload']).toBe('job')
    expect(inspection.labels['nukelab.job.id']).toBe(primaryId)
    expect(inspection.user).toBe('65532:65532')
    expect(inspection.readonlyRootfs).toBe(true)
    expect(inspection.networkMode).toBe('none')
    expect(inspection.portBindings).toEqual({})
    expect(inspection.publishedPorts).toEqual({})
    expect(inspection.restartPolicy).toBe('no')
    expect(inspection.autoRemove).toBe(false)
    expect(inspection.memoryBytes).toBeGreaterThan(0)
    expect(inspection.nanoCpus).toBeGreaterThan(0)
    expect(inspection.pidsLimit).toBeGreaterThan(0)
    expect(inspection.workingDir).toBe('/work')
    expect(inspection.capDrop).toContain('ALL')
    expect(inspection.securityOpt).toContain('no-new-privileges:true')
    expect(inspection.logConfig.type).toBe('json-file')
    expect(inspection.logConfig.config?.['max-size']).toBe('1m')
    console.log(
      JSON.stringify({
        scope: 'jobs-runtime-container',
        job: primaryId,
        container: inspection.id,
        image: inspection.image,
        user: inspection.user,
        network: inspection.networkMode,
        readonly_rootfs: inspection.readonlyRootfs,
        cap_drop: inspection.capDrop,
        restart_policy: inspection.restartPolicy,
      })
    )

    const finished = await waitForJobTerminal(request, token, primaryId, 180_000)
    expect(finished.state, finished.reason_message ?? '').toBe('succeeded')
    expect(finished.result).toMatchObject({
      exit_code: 0,
      outcome_code: 'succeeded',
      proof: 'runtime',
    })
    expect(finished.billing).toMatchObject({
      mode: 'zero_cost',
      charged: 0,
      authorized: 0,
      rate_per_hour: 0,
      state: 'none',
      unpaid: 0,
    })
    expect(
      await downloadVolumeText(request, token, state.volumeId, OUTPUT_NAME, state.volumeName)
    ).toBe(expectedOutput)

    const primaryLogs = await getJobLogs(request, token, primaryId)
    expectStatus(primaryLogs, 200, 'read primary logs')
    expect(primaryLogs.body?.state).toBe('available')
    expect(primaryLogs.body?.text).toContain(`job-stdout-${state.stamp}`)
    expect(primaryLogs.body?.size_bytes ?? 0).toBeGreaterThan(0)

    // Result, logs and output bytes remain after the container is removed.
    await waitForNoJobContainers(primaryId, 120_000)
    expect(jobContainerIds(primaryId)).toEqual([])
    const persisted = await getJob(request, token, primaryId)
    expectStatus(persisted, 200, 'read primary job after cleanup')
    expect(persisted.body?.state).toBe('succeeded')
    expect(persisted.body?.result?.exit_code).toBe(0)
    expect(persisted.body?.billing).toMatchObject({
      mode: 'zero_cost',
      charged: 0,
      authorized: 0,
      rate_per_hour: 0,
      state: 'none',
      unpaid: 0,
    })
    const persistedLogs = await getJobLogs(request, token, primaryId)
    expectStatus(persistedLogs, 200, 'read primary logs after cleanup')
    expect(persistedLogs.body?.state).toBe('available')
    expect(persistedLogs.body?.text).toContain(`job-stdout-${state.stamp}`)
    expect(
      await downloadVolumeText(request, token, state.volumeId, OUTPUT_NAME, state.volumeName)
    ).toBe(expectedOutput)

    // ── Nonzero exit ───────────────────────────────────────────────────────
    const failing = await submit(
      request,
      token,
      {
        name: uniqueName('jobs-runtime-nonzero'),
        revision_id: state.revisionId as string,
        plan_id: state.planId,
        volume_id: state.volumeId,
        argv: ['/bin/sh', '-c', `echo 'nonzero-${state.stamp}' >&2; exit 7`],
        max_runtime_seconds: 120,
      },
      `jobs-runtime-${state.stamp}-nonzero`
    )
    expectStatus(failing, 202, 'submit nonzero job')
    const failingId = trackJob(failing.body)
    const failed = await waitForJobTerminal(request, token, failingId, 180_000)
    expect(failed.state, failed.reason_message ?? '').toBe('failed')
    expect(failed.reason_code).toBe('nonzero_exit')
    expect(failed.result).toMatchObject({ exit_code: 7, outcome_code: 'failed' })
    expect(failed.billing).toMatchObject({
      mode: 'zero_cost',
      charged: 0,
      authorized: 0,
      rate_per_hour: 0,
      state: 'none',
      unpaid: 0,
    })
    const failedLogs = await getJobLogs(request, token, failingId)
    expectStatus(failedLogs, 200, 'read nonzero logs')
    expect(failedLogs.body?.text).toContain(`nonzero-${state.stamp}`)
    await waitForNoJobContainers(failingId, 120_000)

    // ── Bounded log tail ───────────────────────────────────────────────────
    const logLimit = capabilities.limits.log_tail_bytes
    const emittedBytes = logLimit + 65_536
    const truncating = await submit(
      request,
      token,
      {
        name: uniqueName('jobs-runtime-logs'),
        revision_id: state.revisionId as string,
        plan_id: state.planId,
        volume_id: state.volumeId,
        argv: ['/bin/sh', '-c', `head -c ${emittedBytes} /dev/zero | tr "\\0" x; echo`],
        max_runtime_seconds: 120,
      },
      `jobs-runtime-${state.stamp}-logs`
    )
    expectStatus(truncating, 202, 'submit truncating job')
    const truncatingId = trackJob(truncating.body)
    const truncatedJob = await waitForJobTerminal(request, token, truncatingId, 180_000)
    expect(truncatedJob.state, truncatedJob.reason_message ?? '').toBe('succeeded')
    const truncatedLogs = await getJobLogs(request, token, truncatingId)
    expectStatus(truncatedLogs, 200, 'read truncated logs')
    expect(truncatedLogs.body?.state).toBe('truncated')
    expect(truncatedLogs.body?.truncated).toBe(true)
    expect(truncatedLogs.body?.size_bytes ?? 0).toBeGreaterThan(logLimit)
    expect((truncatedLogs.body?.text ?? '').length).toBeLessThanOrEqual(logLimit)
    await waitForNoJobContainers(truncatingId, 120_000)

    // ── Cancellation and cleanup ───────────────────────────────────────────
    const cancelTarget = await submit(
      request,
      token,
      {
        name: uniqueName('jobs-runtime-cancel'),
        revision_id: state.revisionId as string,
        plan_id: state.planId,
        volume_id: state.volumeId,
        argv: ['/bin/sh', '-c', `echo 'cancel-ready-${state.stamp}'; sleep 600`],
        max_runtime_seconds: 600,
      },
      `jobs-runtime-${state.stamp}-cancel`
    )
    expectStatus(cancelTarget, 202, 'submit cancel job')
    const cancelId = trackJob(cancelTarget.body)
    const running = await waitForJobState(request, token, cancelId, ['running'], 180_000)
    expect(running.state).toBe('running')
    expect(jobContainerIds(cancelId)).toHaveLength(1)
    const cancelResponse = await cancelJob(request, token, cancelId)
    expectStatus(cancelResponse, 200, 'cancel running job')
    expect(['cancelling', 'cancelled']).toContain(cancelResponse.body?.state)
    const cancelled = await waitForJobTerminal(request, token, cancelId, 180_000)
    expect(cancelled.state).toBe('cancelled')
    expect(cancelled.result?.outcome_code).toBe('cancelled')
    expect(cancelled.reason_code).toBe('request_cancelled')
    expect(cancelled.billing).toMatchObject({
      mode: 'zero_cost',
      charged: 0,
      authorized: 0,
      rate_per_hour: 0,
      state: 'none',
      unpaid: 0,
    })
    await waitForNoJobContainers(cancelId, 120_000)
    const persistedCancel = await getJob(request, token, cancelId)
    expectStatus(persistedCancel, 200, 'read cancelled job after cleanup')
    expect(persistedCancel.body?.state).toBe('cancelled')

    // ── Owner isolation ────────────────────────────────────────────────────
    const foreign = await createTestUser(request, token, {
      prefix: 'jobs-foreign',
      password: TEST_USER_PASSWORD,
    })
    state.secondUserId = foreign.id
    const foreignToken = await apiLogin(request, foreign.username, foreign.password)

    const foreignGet = await getJob(request, foreignToken, primaryId)
    expect(foreignGet.status).toBe(404)
    expect(apiErrorCode(foreignGet.body, foreignGet.text)).toBe('job_not_found')
    const foreignLogs = await getJobLogs(request, foreignToken, primaryId)
    expect(foreignLogs.status).toBe(404)
    const foreignCancel = await cancelJob(request, foreignToken, primaryId)
    expect(foreignCancel.status).toBe(404)
    const foreignList = await listJobs(request, foreignToken, 'all')
    expectStatus(foreignList, 200, 'foreign job list')
    expect(foreignList.body?.items).toEqual([])
    const foreignVolume = await apiCall(
      request,
      'GET',
      `/api/volumes/${state.volumeId}`,
      foreignToken
    )
    expect([403, 404]).toContain(foreignVolume.status)
    expect(foreignVolume.text).not.toContain(outputPrefix)
    const foreignDownload = await request.get(`/api/volumes/${state.volumeId}/download`, {
      headers: { Authorization: `Bearer ${foreignToken}` },
      params: { path: OUTPUT_NAME },
    })
    expect(foreignDownload.status()).not.toBe(200)
    expect(await foreignDownload.text()).not.toContain(outputPrefix)

    console.log(
      JSON.stringify({
        scope: 'jobs-runtime-evidence',
        jobs: state.jobIds,
        image_reference: state.runtimeImage,
        image_local_id: state.imageId,
        plan: state.planId,
        revision: state.revisionId,
        volume: state.volumeId,
        capacity_occupied: CAPACITY_ENABLED,
        log_tail_bytes: logLimit,
      })
    )
  })

  test('holds paid credits, settles actual runtime, and writes one ledger entry', async ({
    request,
  }) => {
    test.setTimeout(MAIN_TIMEOUT_MS)
    test.skip(!state.paidPlanId, 'Paid batch plan was not seeded for this stack.')
    const paidPlanId = state.paidPlanId
    const revisionId = state.revisionId
    const volumeId = state.volumeId
    if (!state.adminToken || !paidPlanId || !revisionId || !volumeId) {
      throw new Error('Paid batch job fixtures were not initialized')
    }
    const token = state.adminToken
    const capabilities = await getJobCapabilities(request, token)
    test.skip(capabilities.billing_mode !== 'paid', 'Paid batch billing is disabled.')

    const creditsBefore = await apiCall<CreditsResponse>(request, 'GET', '/api/credits/', token)
    expectStatus(creditsBefore, 200, 'read credits before paid job')
    const heldBefore = creditsBefore.body?.summary.held ?? 0
    const spendableBefore = creditsBefore.body?.summary.spendable ?? 0
    const balanceBefore = creditsBefore.body?.balance ?? 0

    const paidBody = {
      name: uniqueName('jobs-runtime-paid'),
      revision_id: revisionId,
      plan_id: paidPlanId,
      volume_id: volumeId,
      argv: ['/bin/sh', '-c', `sleep 2; echo 'paid-${state.stamp}'`],
      max_runtime_seconds: 120,
    }
    const submitted = await submit(request, token, paidBody, `jobs-runtime-${state.stamp}-paid`)
    expectStatus(submitted, 202, 'submit paid job')
    const paidJobId = trackJob(submitted.body)
    expect(submitted.body?.billing).toMatchObject({
      mode: 'paid',
      charged: 0,
      authorized: 2,
      rate_per_hour: 60,
      state: 'held',
      unpaid: 0,
    })

    const creditsDuring = await apiCall<CreditsResponse>(request, 'GET', '/api/credits/', token)
    expectStatus(creditsDuring, 200, 'read credits while paid job is held')
    expect(creditsDuring.body?.summary.held ?? 0).toBe(heldBefore + 2)
    expect(creditsDuring.body?.summary.spendable ?? 0).toBe(spendableBefore - 2)
    expect(creditsDuring.body?.balance ?? 0).toBe(balanceBefore)

    const finished = await waitForJobTerminal(request, token, paidJobId, 180_000)
    expect(finished.state, finished.reason_message ?? '').toBe('succeeded')
    expect(finished.billing.mode).toBe('paid')
    expect(finished.billing.state).toBe('settled')
    expect(finished.billing.authorized).toBe(2)
    expect(finished.billing.rate_per_hour).toBe(60)
    expect(finished.billing.charged).toBeGreaterThanOrEqual(1)
    expect(finished.billing.charged).toBeLessThanOrEqual(2)
    expect(finished.billing.unpaid).toBe(0)
    expect(finished.billing.authorized - finished.billing.charged).toBeGreaterThanOrEqual(0)

    const creditsAfter = await apiCall<CreditsResponse>(request, 'GET', '/api/credits/', token)
    expectStatus(creditsAfter, 200, 'read credits after paid settlement')
    expect(creditsAfter.body?.summary.held ?? 0).toBe(heldBefore)
    expect(creditsAfter.body?.balance ?? 0).toBe(balanceBefore - finished.billing.charged)
    expect(creditsAfter.body?.summary.spendable ?? 0).toBe(
      (creditsAfter.body?.balance ?? 0) - (creditsAfter.body?.summary.held ?? 0)
    )

    const history = await apiCall<{
      transactions: Array<{
        type: string
        amount: number
        metadata: Record<string, unknown>
      }>
    }>(request, 'GET', '/api/credits/history?transaction_type=batch_job_usage&limit=20', token)
    expectStatus(history, 200, 'read paid job ledger history')
    const settlements = (history.body?.transactions ?? []).filter(
      (transaction) => transaction.metadata?.job_id === paidJobId
    )
    expect(settlements).toHaveLength(1)
    expect(settlements[0].type).toBe('batch_job_usage')
    expect(settlements[0].amount).toBe(-finished.billing.charged)

    await waitForNoJobContainers(paidJobId, 120_000)
    console.log(
      JSON.stringify({
        scope: 'jobs-runtime-paid-evidence',
        job: paidJobId,
        plan: paidPlanId,
        authorized: finished.billing.authorized,
        charged: finished.billing.charged,
        rate_per_hour: finished.billing.rate_per_hour,
        ledger_transactions: settlements.length,
      })
    )
  })
})
