// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Runner-only fixtures for the combined real-stack acceptance scenario.
 *
 * API traffic always goes through the running stack. Docker is used only to
 * seed/inspect server volume contents and to read image/runtime identities.
 */

import { execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import { closeSync, cpSync, mkdirSync, openSync, readFileSync, statSync, writeSync } from 'node:fs'
import path from 'node:path'
import type { APIRequestContext, APIResponse, Page } from '@playwright/test'

export const ADMIN_USERNAME = process.env.TEST_ADMIN_USERNAME || 'admin'
export const ADMIN_PASSWORD = process.env.TEST_ADMIN_PASSWORD || 'admin123'

export const MOUNT_PATH = '/data'
export const VOLUME_BYTES = 1024 ** 3
export const SMALL_PLAN_SLUG = 'small'

export interface ApiOptions {
  data?: unknown
  form?: Record<string, string>
  params?: Record<string, string | number>
  timeout?: number
}

export interface ApiResult<T> {
  response: APIResponse
  status: number
  body: T | null
  text: string
}

export interface ServerDto {
  id: string
  name: string
  status: string
  container_id: string | null
  volume_id: string | null
  volume_mode: string | null
  volume_mounts: Array<{
    volume_id: string
    mount_path: string
    mode: string
    is_primary: boolean
    volume?: { id: string; name: string; display_name: string; size_bytes: number } | null
  }> | null
  allocated_cpu: number | null
  allocated_memory: string | null
  allocated_disk: string | null
  user_id: string | null
  plan_id: string | null
  environment_id: string | null
}

export interface VolumeDto {
  id: string
  name: string
  display_name: string
  owner_id: string
  visibility: string
  size_bytes: number
  max_size_bytes: number | null
  status: string
  server_count: number
}

export interface QueueEntryDto {
  id: string
  request: {
    name: string
    plan_id: string
    environment_id: string
    resources: { cpu: number; memory_mib: number; disk_mib: number; gpu_count: number }
  }
  status: string
  position: number | null
  reason_code: string | null
  message: string
  server_id: string | null
  can_cancel: boolean
}

export interface QueuedServerDto {
  queued: true
  queue_id: string
  queue_position: number | null
  message: string
  request: QueueEntryDto['request']
}

export interface BackupDto {
  id: string
  source_volume_id: string | null
  source_display_name: string
  status: string
  reason_code: string | null
  message: string
  description: string | null
  created_at: string
  completed_at: string | null
  expires_at: string | null
  compressed_bytes: number | null
  logical_bytes: number | null
  member_count: number | null
  can_restore: boolean
  can_delete: boolean
}

export interface RestoreDto {
  id: string
  backup_id: string
  status: string
  reason_code: string | null
  message: string
  destination_volume_id: string | null
  destination_display_name: string
}

export interface ProvenanceDto {
  state: 'recorded' | 'unrecorded'
  launch_id: string | null
  generation: number | null
  manifest: {
    revision_id: string
    revision_fingerprint: string
    runtime: { requested_reference: string; local_id: string }
    volume_requirements: Array<{ purpose: string; mount_path: string; mode: string }>
  } | null
  actual_runtime: { requested_reference: string; local_id: string } | null
  can_recreate: boolean
  recreation_reason_code: string | null
}

export interface QuotaDto {
  usage: { cpu: number; memory_mb: number; disk_mb: number; gpu: number; servers: number }
  limits: {
    max_cpu_total: number
    max_memory_total: string
    max_disk_total: string
    max_gpu_total: number
    max_servers_total: number
  }
}

export interface SeedManifest {
  stamp: string
  contents: Record<'hello' | 'nested' | 'deep' | 'unicode', string>
  paths: {
    hello: string
    nested: string
    deep: string
    unicode: string
    hardlink: string
    symlink: string
    dir: string
    sub: string
  }
  hashes: Record<string, string>
  sourceModes: Record<string, number>
  logicalBytes: number
  memberCount: number
}

export interface VolumeInspection {
  entries: Record<string, { mode: number; uid: number; gid: number; size: number }>
  hashes: Record<string, string>
  symlinkTarget: string | null
  hardlinksSameInode: boolean
  hardlinkCount: number
}

export interface ArtifactEvidence {
  directory: string
  archivePath: string
  digest: string
  completion: {
    sha256: string
    compressed_bytes: number
    logical_bytes: number
    member_count: number
  }
}

export function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` }
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export function uniqueSlug(prefix: string): string {
  return `${prefix}-${Date.now()}-${randomUUID().slice(0, 8)}`.toLowerCase()
}

export function uniqueName(prefix: string): string {
  return `${prefix}-${Date.now()}-${randomUUID().slice(0, 6)}`
}

export function newRequestId(): string {
  return randomUUID()
}

export function sha256(value: Buffer | string): string {
  return createHash('sha256').update(value).digest('hex')
}

export async function poll<T>(
  label: string,
  read: () => Promise<T>,
  accept: (value: T) => boolean,
  options: { timeoutMs: number; intervalMs?: number; describe?: (value: T) => string }
): Promise<T> {
  const deadline = Date.now() + options.timeoutMs
  let lastValue: T | undefined
  let lastError: unknown
  for (;;) {
    try {
      lastValue = await read()
      if (accept(lastValue)) return lastValue
    } catch (error) {
      lastError = error
    }
    if (Date.now() >= deadline) {
      const detail =
        lastError !== undefined
          ? `last error: ${lastError instanceof Error ? lastError.message : String(lastError)}`
          : `last value: ${
              lastValue !== undefined && options.describe
                ? options.describe(lastValue)
                : JSON.stringify(lastValue)
            }`
      throw new Error(`Timed out after ${options.timeoutMs}ms waiting for ${label}; ${detail}`)
    }
    await sleep(options.intervalMs ?? 1000)
  }
}

export async function apiLogin(
  request: APIRequestContext,
  username: string,
  password: string
): Promise<string> {
  const response = await request.post('/api/auth/login', {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    data: new URLSearchParams({ username, password }).toString(),
    timeout: 30_000,
  })
  if (!response.ok()) {
    throw new Error(
      `API login failed for ${username}: ${response.status()} ${await response.text()}`
    )
  }
  const body = (await response.json()) as { access_token?: string }
  if (!body.access_token) throw new Error(`API login for ${username} returned no access token`)
  return body.access_token
}

export async function apiCall<T>(
  request: APIRequestContext,
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  url: string,
  token: string | null,
  options: ApiOptions = {}
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  let data: string | undefined
  if (options.form) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
    data = new URLSearchParams(options.form).toString()
  } else if (options.data !== undefined) {
    headers['Content-Type'] = 'application/json'
    data = JSON.stringify(options.data)
  }
  const response = await request.fetch(url, {
    method,
    headers,
    data,
    params: options.params,
    timeout: options.timeout ?? 60_000,
  })
  const text = await response.text()
  let body: T | null = null
  if (text) {
    try {
      body = JSON.parse(text) as T
    } catch {
      body = null
    }
  }
  return { response, status: response.status(), body, text }
}

export function apiErrorCode(body: unknown, text: string): string | undefined {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'code' in detail) {
      return String((detail as { code?: unknown }).code)
    }
  }
  return text || undefined
}

export async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto('/login')
  await page.getByTestId('login-username').locator('visible=true').fill(ADMIN_USERNAME)
  await page.getByTestId('login-password').locator('visible=true').fill(ADMIN_PASSWORD)
  await page.getByTestId('login-submit').locator('visible=true').click()
  await page.waitForURL('/', { timeout: 30_000 })
  await page.getByRole('heading', { name: 'Dashboard' }).waitFor({ timeout: 30_000 })
}

export async function downloadFileHash(
  request: APIRequestContext,
  token: string,
  volumeId: string,
  relativePath: string
): Promise<{ digest: string; size: number }> {
  const response = await request.get(`/api/volumes/${volumeId}/download`, {
    headers: authHeaders(token),
    params: { path: relativePath },
    timeout: 60_000,
  })
  if (!response.ok()) {
    throw new Error(
      `Download of ${relativePath} from volume ${volumeId} failed: ${response.status()} ${await response.text()}`
    )
  }
  const body = await response.body()
  return { digest: sha256(body), size: body.length }
}

let detectedEngine: string | undefined

function containerEngine(): string {
  if (process.env.CONTAINER_ENGINE) return process.env.CONTAINER_ENGINE
  if (detectedEngine) return detectedEngine
  for (const candidate of ['docker', 'podman']) {
    try {
      execFileSync(candidate, ['version', '--format', '{{.Server.Version}}'], {
        encoding: 'utf8',
        timeout: 10_000,
      })
      detectedEngine = candidate
      return candidate
    } catch {
      // Try the next supported engine.
    }
  }
  throw new Error('No reachable Docker or Podman engine; set CONTAINER_ENGINE.')
}

export function runDocker(args: string[], timeout = 120_000): string {
  const engine = containerEngine()
  try {
    return execFileSync(engine, args, { encoding: 'utf8', timeout }).trim()
  } catch (error) {
    const failure = error as { stderr?: Buffer | string; stdout?: Buffer | string; message: string }
    const stderr = failure.stderr?.toString().trim()
    const stdout = failure.stdout?.toString().trim()
    throw new Error(`${engine} ${args.join(' ')} failed: ${stderr || stdout || failure.message}`, {
      cause: error,
    })
  }
}

export function dockerImageId(reference: string): string {
  const id = runDocker(['image', 'inspect', '--format', '{{.Id}}', reference], 60_000)
  if (!/^sha256:[a-f0-9]{64}$/.test(id)) {
    throw new Error(`Unexpected local image identity for ${reference}: ${id}`)
  }
  return id
}

export function containerImageIdentity(containerId: string): string {
  const id = runDocker(['inspect', '--format', '{{.Image}}', containerId], 60_000)
  if (!/^sha256:[a-f0-9]{64}$/.test(id)) {
    throw new Error(`Unexpected runtime image identity for ${containerId}: ${id}`)
  }
  return id
}

export interface ContainerHardening {
  user: string
  capDrop: string[] | null
  readonlyRootfs: boolean
  securityOpt: string[] | null
}

export function inspectContainerHardening(containerId: string): ContainerHardening {
  const raw = JSON.parse(runDocker(['inspect', containerId], 60_000)) as Array<{
    Config?: { User?: string }
    HostConfig?: { CapDrop?: string[]; ReadonlyRootfs?: boolean; SecurityOpt?: string[] }
  }>
  const config = raw[0]?.Config
  const host = raw[0]?.HostConfig
  if (!config || !host)
    throw new Error(`Container inspect did not return configuration: ${containerId}`)
  return {
    user: config.User ?? '',
    capDrop: host.CapDrop ?? null,
    readonlyRootfs: host.ReadonlyRootfs === true,
    securityOpt: host.SecurityOpt ?? null,
  }
}

export function containersForServer(serverId: string): string[] {
  const output = runDocker(
    [
      'ps',
      '-a',
      '--no-trunc',
      '--filter',
      `label=nukelab.server.id=${serverId}`,
      '--format',
      '{{.ID}}',
    ],
    60_000
  )
  return output
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

export function execInContainer(containerId: string, script: string, user?: string): string {
  const args = ['exec']
  if (user) args.push('--user', user)
  args.push(containerId, 'sh', '-c', script)
  return runDocker(args)
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`
}

export function seedManifest(stamp: string): SeedManifest {
  const contents = {
    hello: `hello-combined-${stamp}`,
    nested: `nested-combined-${stamp}`,
    deep: `deep-combined-${stamp}`,
    unicode: `unicode-combined-${stamp}`,
  }
  const paths = {
    hello: 'hello.txt',
    nested: 'dir/nested.txt',
    deep: 'dir/sub/deep.dat',
    unicode: 'naïve-数据.txt',
    hardlink: 'hardlink.txt',
    symlink: 'link.txt',
    dir: 'dir',
    sub: 'dir/sub',
  }
  const hashes: Record<string, string> = {}
  let logicalBytes = 0
  for (const key of ['hello', 'nested', 'deep', 'unicode'] as const) {
    const bytes = Buffer.byteLength(`${contents[key]}\n`)
    hashes[paths[key]] = sha256(`${contents[key]}\n`)
    logicalBytes += bytes
  }
  // The hardlink shares the hello payload and is hashed independently by the
  // volume fixture, but it must not count twice toward logical source bytes.
  hashes[paths.hardlink] = hashes[paths.hello]
  return {
    stamp,
    contents,
    paths,
    hashes,
    sourceModes: {
      [paths.hello]: 0o640,
      [paths.hardlink]: 0o640,
      [paths.nested]: 0o644,
      [paths.deep]: 0o600,
      [paths.unicode]: 0o644,
      [paths.dir]: 0o750,
      [paths.sub]: 0o700,
    },
    logicalBytes,
    // dir, nested.txt, dir/sub, deep.dat, hello.txt, hardlink.txt, link.txt, non-ASCII file
    memberCount: 8,
  }
}

/**
 * The API creates a blank named volume owned by root. The platform only fixes
 * permissions for auto-created volumes, so the runner opens the mount point to
 * the runtime user and seeds as UID 65532. This keeps source ownership equal to
 * the platform user without touching unrelated containers or volumes.
 */
export function seedVolume(containerId: string, seed: SeedManifest): void {
  // A blank Docker volume is normally root-owned, but an image-provided mount
  // directory can be copied up as the runtime user. Whichever identity owns the
  // mount point may chmod it; the runner never needs elevated capabilities.
  try {
    execInContainer(containerId, `chmod 777 ${MOUNT_PATH}`, '0:0')
  } catch (rootError) {
    try {
      execInContainer(containerId, `chmod 777 ${MOUNT_PATH}`, '65532:65532')
    } catch (runtimeError) {
      throw new Error(
        `Volume mount ${MOUNT_PATH} could not be opened by root (${String(
          rootError
        )}) or the runtime user (${String(runtimeError)})`,
        { cause: runtimeError }
      )
    }
  }
  const script = [
    'set -eu',
    `mkdir -p /data/${seed.paths.sub}`,
    `printf '%s\\n' ${shellQuote(seed.contents.hello)} > /data/${seed.paths.hello}`,
    `printf '%s\\n' ${shellQuote(seed.contents.nested)} > /data/${seed.paths.nested}`,
    `printf '%s\\n' ${shellQuote(seed.contents.deep)} > /data/${seed.paths.deep}`,
    `printf '%s\\n' ${shellQuote(seed.contents.unicode)} > ${shellQuote(`/data/${seed.paths.unicode}`)}`,
    `ln /data/${seed.paths.hello} /data/${seed.paths.hardlink}`,
    `ln -s ${shellQuote(seed.paths.hello)} /data/${seed.paths.symlink}`,
    `chmod 750 /data/${seed.paths.dir}`,
    `chmod 700 /data/${seed.paths.sub}`,
    `chmod 640 /data/${seed.paths.hello}`,
    `chmod 644 /data/${seed.paths.nested}`,
    `chmod 600 /data/${seed.paths.deep}`,
    `chmod 644 ${shellQuote(`/data/${seed.paths.unicode}`)}`,
  ].join('\n')
  execInContainer(containerId, script, '65532:65532')
}

function statEntry(containerId: string, mountPath: string, relativePath: string): string {
  return execInContainer(
    containerId,
    `stat -c '%a %u %g %s' ${shellQuote(path.posix.join(mountPath, relativePath))}`,
    '65532:65532'
  )
}

function fileSha256(containerId: string, mountPath: string, relativePath: string): string {
  const output = execInContainer(
    containerId,
    `sha256sum ${shellQuote(path.posix.join(mountPath, relativePath))}`,
    '65532:65532'
  )
  const digest = output.split(/\s+/)[0]
  if (!/^[a-f0-9]{64}$/.test(digest)) {
    throw new Error(`Unexpected sha256 output for ${relativePath}: ${output}`)
  }
  return digest
}

export function inspectVolume(containerId: string, seed: SeedManifest): VolumeInspection {
  const filePaths = [
    seed.paths.hello,
    seed.paths.nested,
    seed.paths.deep,
    seed.paths.unicode,
    seed.paths.hardlink,
  ]
  const entries: VolumeInspection['entries'] = {}
  const hashes: VolumeInspection['hashes'] = {}
  for (const relativePath of [...filePaths, seed.paths.dir, seed.paths.sub]) {
    const [mode, uid, gid, size] = statEntry(containerId, MOUNT_PATH, relativePath).split(/\s+/)
    entries[relativePath] = {
      mode: parseInt(mode, 8),
      uid: Number(uid),
      gid: Number(gid),
      size: Number(size),
    }
  }
  for (const relativePath of filePaths) {
    hashes[relativePath] = fileSha256(containerId, MOUNT_PATH, relativePath)
  }
  const symlinkTarget = execInContainer(
    containerId,
    `readlink ${shellQuote(path.posix.join(MOUNT_PATH, seed.paths.symlink))}`,
    '65532:65532'
  )
  const inodeOutput = execInContainer(
    containerId,
    `stat -c '%i %h' ${shellQuote(path.posix.join(MOUNT_PATH, seed.paths.hello))} ${shellQuote(
      path.posix.join(MOUNT_PATH, seed.paths.hardlink)
    )}`,
    '65532:65532'
  )
    .split('\n')
    .map((line) => line.trim().split(/\s+/))
  return {
    entries,
    hashes,
    symlinkTarget,
    hardlinksSameInode: inodeOutput.length === 2 && inodeOutput[0][0] === inodeOutput[1][0],
    hardlinkCount: Number(inodeOutput[0]?.[1] ?? 0),
  }
}

export function artifactDirectory(hostRoot: string, backupId: string): string {
  return path.join(hostRoot, 'backups', safeBackupId(backupId))
}

function artifactHelperImage(): string {
  return process.env.E2E_RUNTIME_IMAGE || 'nukelab-environment-base:latest'
}

function dockerArtifactShell(hostRoot: string, extraArgs: string[], script: string): string {
  return runDocker(
    [
      'run',
      '--rm',
      ...extraArgs,
      '-v',
      `${hostRoot}:/artifacts`,
      '--entrypoint',
      'sh',
      artifactHelperImage(),
      '-c',
      script,
    ],
    120_000
  )
}

function safeBackupId(backupId: string): string {
  if (!/^[a-f0-9-]{36}$/i.test(backupId)) {
    throw new Error(`Refusing unsafe backup artifact id: ${backupId}`)
  }
  return backupId
}

export function copyArtifactDirectory(hostRoot: string, backupId: string, target: string): string {
  const source = artifactDirectory(hostRoot, backupId)
  try {
    cpSync(source, target, { recursive: true })
  } catch {
    // The private backup root is 0700/65532 by design. A runner that cannot
    // read it can still exercise the copy through the daemon, which is the
    // same access path used by the recovery helper.
    mkdirSync(target, { recursive: true })
    dockerArtifactShell(
      hostRoot,
      ['-v', `${target}:/target`],
      `cp -a /artifacts/backups/${safeBackupId(backupId)}/. /target/ && chmod -R a+rwX /target`
    )
  }
  return target
}

export function readArtifactEvidence(hostRoot: string, backupId: string): ArtifactEvidence {
  const directory = artifactDirectory(hostRoot, backupId)
  const archivePath = path.join(directory, 'archive.tar.gz')
  const completionPath = path.join(directory, 'completion.json')
  try {
    const archive = readFileSync(archivePath)
    const completion = JSON.parse(
      readFileSync(completionPath, 'utf8')
    ) as ArtifactEvidence['completion']
    return {
      directory,
      archivePath,
      digest: sha256(archive),
      completion,
    }
  } catch (error) {
    if (!(
      error instanceof Error &&
      'code' in error &&
      (error.code === 'EACCES' || error.code === 'EPERM')
    )) {
      throw error
    }
    const id = safeBackupId(backupId)
    const digest = dockerArtifactShell(
      hostRoot,
      [],
      `sha256sum /artifacts/backups/${id}/archive.tar.gz | cut -d' ' -f1`
    )
    const completion = JSON.parse(
      dockerArtifactShell(hostRoot, [], `cat /artifacts/backups/${id}/completion.json`)
    ) as ArtifactEvidence['completion']
    return { directory, archivePath, digest, completion }
  }
}

/**
 * Overwrites the first bytes of the API-referenced archive after every
 * legitimate restore/recreation has finished. The companion copy taken before
 * this call is runner-only evidence; the stack can only read the original.
 */
export function corruptArtifact(hostRoot: string, backupId: string): void {
  const archivePath = path.join(artifactDirectory(hostRoot, backupId), 'archive.tar.gz')
  try {
    const size = statSync(archivePath).size
    if (size === 0) throw new Error(`Artifact for backup ${backupId} is empty`)
    const replacement = Buffer.alloc(Math.min(32, size), 0x00)
    const descriptor = openSync(archivePath, 'r+')
    try {
      writeSync(descriptor, replacement, 0, replacement.length, 0)
    } finally {
      closeSync(descriptor)
    }
  } catch (error) {
    if (!(
      error instanceof Error &&
      'code' in error &&
      (error.code === 'EACCES' || error.code === 'EPERM')
    )) {
      throw error
    }
    const id = safeBackupId(backupId)
    dockerArtifactShell(
      hostRoot,
      [],
      `dd if=/dev/zero of=/artifacts/backups/${id}/archive.tar.gz bs=1 count=32 conv=notrunc status=none`
    )
  }
}
