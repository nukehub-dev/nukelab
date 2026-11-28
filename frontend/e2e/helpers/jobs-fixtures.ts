// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Real-stack helpers for the batch-job browser scenario.
 *
 * API traffic goes through the running stack with no route mocks. Docker is
 * used only for fixture volume seeding and runner-side runtime inspection.
 */

import type { APIRequestContext, APIResponse } from '@playwright/test'
import { listEnvironments } from './api'
import { apiCall, poll, runDocker, sleep, type ApiResult } from './combined-fixtures'

export const JOBS_PLAN_SLUG = 'jobs-e2e-cpu'
export const JOBS_FILLER_PLAN_SLUG = 'jobs-e2e-filler'
export const JOBS_ENVIRONMENT_SLUG = 'jobs-e2e-runtime'
export const JOBS_ENVIRONMENT_NAME = 'Jobs E2E Approved Runtime'

export interface EligibleJobRevision {
  revision_id: string
  environment_id: string
  environment_name: string
  display_label: string
  fingerprint: string
  portable_fingerprint: string | null
  image_reference: string | null
  supports_jobs: boolean
  reason_code: string | null
}

export interface JobEnvironmentSummary {
  revision_id: string
  environment_id: string
  name: string
  display_label: string
  fingerprint: string
  image_reference: string | null
}

export interface JobResult {
  exit_code: number | null
  outcome_code: string
  started_at: string | null
  finished_at: string | null
  duration_seconds: number | null
  proof: string | null
}

export interface JobDetail {
  id: string
  name: string
  state: string
  reason_code: string | null
  reason_message: string | null
  created_at: string
  updated_at: string
  queue_expires_at: string | null
  started_at: string | null
  finished_at: string | null
  deadline_at: string | null
  can_cancel: boolean
  replayed: boolean
  environment: JobEnvironmentSummary
  plan: {
    id: string
    name: string
    cpu: number
    memory_mib: number
    disk_mib: number
    gpu_count: number
    cost_per_hour: number
  }
  volume: { id: string; display_name: string; available: boolean }
  argv: string[]
  limits: { max_runtime_seconds: number }
  result: JobResult | null
  logs: {
    state: string
    truncated: boolean
    size_bytes: number
    expires_at: string | null
  }
  billing: { mode: string; charged: number }
}

export interface JobListResponse {
  items: Array<{
    id: string
    name: string
    state: string
    reason_code: string | null
    environment_name: string
    created_at: string
    started_at: string | null
    finished_at: string | null
    can_cancel: boolean
  }>
  next_cursor: string | null
}

export interface JobLogs {
  state: string
  text: string | null
  truncated: boolean
  size_bytes: number
  expires_at: string | null
  encoding: string | null
}

export interface JobCapabilities {
  enabled: boolean
  can_submit: boolean
  billing_mode: string
  secrets_enabled: boolean
  storage_limits_enforced: boolean
  storage_enforcement_required: boolean
  reason_code: string | null
  limits: {
    max_active_jobs: number
    max_queued_jobs: number
    default_runtime_seconds: number
    max_runtime_seconds: number
    queue_ttl_seconds: number
    max_argv_items: number
    max_input_bytes: number
    log_tail_bytes: number
    log_retention_seconds: number
  }
}

export interface CreateJobInput {
  name: string
  revision_id: string
  plan_id: string
  volume_id: string
  argv: string[]
  max_runtime_seconds?: number
}

export interface JobContainerInspection {
  id: string
  image: string
  name: string
  user: string
  labels: Record<string, string>
  networkMode: string
  portBindings: Record<string, unknown>
  publishedPorts: Record<string, unknown>
  readonlyRootfs: boolean
  capDrop: string[] | null
  securityOpt: string[] | null
  restartPolicy: string
  autoRemove: boolean
  workingDir: string
  logConfig: { type?: string; config?: Record<string, string> }
  memoryBytes: number
  nanoCpus: number
  pidsLimit: number
  running: boolean
}

const TERMINAL_STATES = new Set([
  'succeeded',
  'failed',
  'cancelled',
  'timed_out',
  'expired',
  'recovery_required',
])

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`
}

async function readJson<T>(response: APIResponse): Promise<T> {
  if (!response.ok()) {
    throw new Error(`Jobs request failed (${response.status()}): ${await response.text()}`)
  }
  return (await response.json()) as T
}

export async function getJobCapabilities(
  request: APIRequestContext,
  token: string
): Promise<JobCapabilities> {
  const response = await request.get('/api/jobs/capabilities', {
    headers: { Authorization: `Bearer ${token}` },
  })
  return readJson<JobCapabilities>(response)
}

export async function findSeededEnvironment(
  request: APIRequestContext,
  token: string,
  runtimeImage: string
) {
  const environments = await listEnvironments(request, token)
  const environment = environments.find(
    (item) => item.slug === JOBS_ENVIRONMENT_SLUG && item.image === runtimeImage
  )
  if (!environment) {
    throw new Error(
      `Seeded environment ${JOBS_ENVIRONMENT_SLUG} for ${runtimeImage} is missing. ` +
        'Run scripts/ci/seed-jobs-fixture.py inside the disposable backend first.'
    )
  }
  return environment
}

export async function findSeededRevision(
  request: APIRequestContext,
  token: string,
  environmentId: string
): Promise<EligibleJobRevision> {
  const result = await apiCall<{ items: EligibleJobRevision[] }>(
    request,
    'GET',
    '/api/jobs/eligible-revisions',
    token
  )
  if (result.status !== 200) {
    throw new Error(
      `List eligible revisions failed (${result.status}): ${result.text.slice(0, 300)}`
    )
  }
  const revision = result.body?.items.find((item) => item.environment_id === environmentId)
  if (!revision) {
    throw new Error(
      'The seeded environment has no eligible job revision. Re-run the CI seed fixture.'
    )
  }
  return revision
}

export async function getJob(
  request: APIRequestContext,
  token: string,
  jobId: string
): Promise<ApiResult<JobDetail>> {
  return apiCall<JobDetail>(request, 'GET', `/api/jobs/${jobId}`, token)
}

export async function listJobs(
  request: APIRequestContext,
  token: string,
  state: 'active' | 'history' | 'all' = 'all'
): Promise<ApiResult<JobListResponse>> {
  return apiCall<JobListResponse>(request, 'GET', '/api/jobs', token, {
    params: { state, limit: 100 },
  })
}

export async function getJobLogs(
  request: APIRequestContext,
  token: string,
  jobId: string
): Promise<ApiResult<JobLogs>> {
  return apiCall<JobLogs>(request, 'GET', `/api/jobs/${jobId}/logs`, token)
}

export async function submitJob(
  request: APIRequestContext,
  token: string,
  body: CreateJobInput,
  idempotencyKey: string
): Promise<ApiResult<JobDetail>> {
  const response = await request.fetch('/api/jobs', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    },
    data: JSON.stringify(body),
    timeout: 60_000,
  })
  const text = await response.text()
  let parsed: JobDetail | null = null
  if (text) {
    try {
      parsed = JSON.parse(text) as JobDetail
    } catch {
      parsed = null
    }
  }
  return { response, status: response.status(), body: parsed, text }
}

export async function cancelJob(
  request: APIRequestContext,
  token: string,
  jobId: string
): Promise<ApiResult<JobDetail>> {
  return apiCall<JobDetail>(request, 'POST', `/api/jobs/${jobId}/cancel`, token, {
    timeout: 60_000,
  })
}

/**
 * Poll a job until it reaches one of the expected states or any terminal or
 * recovery state. The caller asserts the returned state so an unexpected
 * terminal outcome fails with the authoritative detail.
 */
export async function waitForJobState(
  request: APIRequestContext,
  token: string,
  jobId: string,
  expected: string | string[],
  timeoutMs = 240_000
): Promise<JobDetail> {
  const wanted = new Set(Array.isArray(expected) ? expected : [expected])
  return poll(
    `job ${jobId} state ${[...wanted].join('|')}`,
    async () => {
      const result = await getJob(request, token, jobId)
      if (result.status === 404) return null
      if (result.status !== 200 || !result.body) {
        throw new Error(`Get job failed (${result.status}): ${result.text.slice(0, 300)}`)
      }
      return result.body
    },
    (value) => value !== null && (wanted.has(value.state) || TERMINAL_STATES.has(value.state)),
    {
      timeoutMs,
      intervalMs: 750,
      describe: (value) =>
        value ? `state=${value.state} reason=${value.reason_code ?? 'none'}` : 'state=missing',
    }
  ) as Promise<JobDetail>
}

export async function waitForJobTerminal(
  request: APIRequestContext,
  token: string,
  jobId: string,
  timeoutMs = 240_000
): Promise<JobDetail> {
  return waitForJobState(
    request,
    token,
    jobId,
    ['succeeded', 'failed', 'cancelled', 'timed_out', 'expired'],
    timeoutMs
  )
}

export function jobContainerIds(jobId: string): string[] {
  const output = runDocker(
    ['ps', '-a', '--no-trunc', '--filter', `label=nukelab.job.id=${jobId}`, '--format', '{{.ID}}'],
    60_000
  )
  return output
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

export async function waitForNoJobContainers(
  jobId: string,
  timeoutMs = 120_000,
  intervalMs = 1000
): Promise<void> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    if (jobContainerIds(jobId).length === 0) return
    if (Date.now() >= deadline) {
      throw new Error(`Job ${jobId} still has a workload container after ${timeoutMs}ms`)
    }
    await sleep(intervalMs)
  }
}

export function inspectJobContainer(containerId: string): JobContainerInspection {
  const raw = JSON.parse(runDocker(['inspect', containerId], 60_000)) as Array<{
    Id?: string
    Image?: string
    Name?: string
    Config?: {
      User?: string
      Labels?: Record<string, string>
      WorkingDir?: string
    }
    HostConfig?: {
      NetworkMode?: string
      PortBindings?: Record<string, unknown> | null
      ReadonlyRootfs?: boolean
      CapDrop?: string[] | null
      SecurityOpt?: string[] | null
      RestartPolicy?: { Name?: string }
      AutoRemove?: boolean
      LogConfig?: { Type?: string; Config?: Record<string, string> }
      Memory?: number
      NanoCpus?: number
      PidsLimit?: number
    }
    NetworkSettings?: { Ports?: Record<string, unknown> | null }
    State?: { Running?: boolean }
  }>
  const container = raw[0]
  if (!container?.Id) {
    throw new Error(`Container inspect returned no identity: ${containerId}`)
  }
  return {
    id: container.Id,
    image: container.Image ?? '',
    name: (container.Name ?? '').replace(/^\//, ''),
    user: container.Config?.User ?? '',
    labels: container.Config?.Labels ?? {},
    networkMode: container.HostConfig?.NetworkMode ?? '',
    portBindings: container.HostConfig?.PortBindings ?? {},
    publishedPorts: container.NetworkSettings?.Ports ?? {},
    readonlyRootfs: container.HostConfig?.ReadonlyRootfs === true,
    capDrop: container.HostConfig?.CapDrop ?? null,
    securityOpt: container.HostConfig?.SecurityOpt ?? null,
    restartPolicy: container.HostConfig?.RestartPolicy?.Name ?? '',
    autoRemove: container.HostConfig?.AutoRemove === true,
    workingDir: container.Config?.WorkingDir ?? '',
    logConfig: {
      type: container.HostConfig?.LogConfig?.Type,
      config: container.HostConfig?.LogConfig?.Config,
    },
    memoryBytes: container.HostConfig?.Memory ?? 0,
    nanoCpus: container.HostConfig?.NanoCpus ?? 0,
    pidsLimit: container.HostConfig?.PidsLimit ?? 0,
    running: container.State?.Running === true,
  }
}

/**
 * Seed one known input file on a blank private volume. The API creates the
 * named volume owned by root; the runner opens the mount point as root and
 * writes as the fixed runtime user so job ownership matches production.
 */
export function seedJobVolume(
  volumeName: string,
  image: string,
  relativePath: string,
  content: string
): void {
  runDocker(
    [
      'run',
      '--rm',
      '--network',
      'none',
      '--user',
      '0:0',
      '-v',
      `${volumeName}:/work`,
      '--entrypoint',
      '/bin/chmod',
      image,
      '0777',
      '/work',
    ],
    120_000
  )
  runDocker(
    [
      'run',
      '--rm',
      '--network',
      'none',
      '--user',
      '65532:65532',
      '-v',
      `${volumeName}:/work`,
      '--entrypoint',
      '/bin/sh',
      image,
      '-c',
      `printf '%s' ${shellQuote(content)} > /work/${shellQuote(relativePath)}`,
    ],
    120_000
  )
}

export async function downloadVolumeText(
  request: APIRequestContext,
  token: string,
  volumeId: string,
  relativePath: string,
  volumeName?: string
): Promise<string> {
  const response = await request.get(`/api/volumes/${volumeId}/download`, {
    headers: { Authorization: `Bearer ${token}` },
    params: { path: relativePath },
    timeout: 60_000,
  })
  if (response.ok()) return response.text()
  if (process.env.E2E_JOBS_VOLUME_READ === 'docker' && volumeName) {
    // Local stacks may expose the Docker volume root only through the daemon.
    // CI keeps the API download path authoritative; this opt-in fallback lets
    // the runtime scenario prove the bytes without host root access.
    const output = runDocker(
      [
        'run',
        '--rm',
        '--network',
        'none',
        '-v',
        `${volumeName}:/work:ro`,
        '--entrypoint',
        '/bin/cat',
        process.env.E2E_RUNTIME_IMAGE || 'nukelab-e2e-runtime:a',
        `/work/${relativePath}`,
      ],
      60_000
    )
    return output ? `${output}\n` : output
  }
  throw new Error(
    `Download ${relativePath} from volume ${volumeId} failed (${response.status()}): ` +
      (await response.text()).slice(0, 300)
  )
}
