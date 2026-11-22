// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import {
  canSubmitRevisionAction,
  ENVIRONMENT_REVISION_MANAGE_PERMISSIONS,
  ENVIRONMENT_REVISION_READ_PERMISSIONS,
  environmentRevisionAccess,
  environmentRevisionErrorInfo,
  environmentRevisionFilterCounts,
  fetchEnvironmentRevisions,
  filterEnvironmentRevisions,
  hasNoSelectableRevision,
  normalizeRevisionReason,
  REVISION_REASON_MAX_LENGTH,
  revisionLimitationLabel,
  revisionManifestDigest,
  revisionMatchesFilter,
  revisionMatchesSearch,
  revisionPlatform,
  revisionPortabilityLabel,
  revisionReasonValidationError,
  revisionVolumeModeLabel,
  revokeEnvironmentRevision,
  verifyEnvironmentArtifacts,
} from './environment-revisions'
import type { EnvironmentRevisionSummary } from '../types/environment-revisions'

function revision(overrides: Partial<EnvironmentRevisionSummary> = {}): EnvironmentRevisionSummary {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    template_id: '22222222-2222-4222-8222-222222222222',
    fingerprint: 'f'.repeat(64),
    portable_fingerprint: null,
    portability: 'local_only',
    revoked: false,
    created_at: '2026-01-01T00:00:00',
    runtime: {
      registry_verified: false,
      os: 'linux',
      architecture: 'amd64',
      variant: null,
      verified_reference: null,
      manifest_digest: null,
      index_digest: null,
      descriptor_media_type: null,
    },
    toolchain: null,
    configuration: {
      image: 'ghcr.io/nukehub-dev/runtime:1',
      tool_image: null,
      packages: ['numpy==2.1.0'],
      ports: ['8080'],
      tool_mounts: ['/opt/nuke'],
      environment_variable_names: ['CUDA_VISIBLE_DEVICES'],
      volumes: [{ mount_path: '/data', mode: 'read_write' }],
    },
    limitations: ['local_only_artifact'],
    ...overrides,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function granted(permissions: string[]) {
  return (required: string[]) => required.every((permission) => permissions.includes(permission))
}

beforeEach(() => {
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => (key === 'nukelab-token' ? 'token' : null),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('environment revision access', () => {
  it('separates read from manage permissions', () => {
    expect(environmentRevisionAccess(granted([...ENVIRONMENT_REVISION_READ_PERMISSIONS]))).toEqual({
      canRead: true,
      canManage: false,
    })
    expect(
      environmentRevisionAccess(granted([...ENVIRONMENT_REVISION_MANAGE_PERMISSIONS]))
    ).toEqual({ canRead: false, canManage: true })
    expect(environmentRevisionAccess(granted([]))).toEqual({
      canRead: false,
      canManage: false,
    })
  })
})

describe('revision reason validation', () => {
  it('trims and bounds the reason without accepting blanks', () => {
    expect(normalizeRevisionReason('  investigate digest  ')).toBe('investigate digest')
    expect(revisionReasonValidationError('   ')).toBe('Enter a reason.')
    expect(revisionReasonValidationError('x'.repeat(REVISION_REASON_MAX_LENGTH))).toBeNull()
    expect(revisionReasonValidationError('x'.repeat(REVISION_REASON_MAX_LENGTH + 1))).toContain(
      'characters or fewer'
    )
    expect(revisionReasonValidationError('bad\u0007reason')).toContain('control characters')
  })

  it('requires an explicit confirmation before a last-revision submit', () => {
    expect(
      canSubmitRevisionAction({
        reason: 'unsafe digest',
        busy: false,
        requiresConfirmation: false,
        confirmed: false,
      })
    ).toBe(true)
    expect(
      canSubmitRevisionAction({
        reason: 'unsafe digest',
        busy: false,
        requiresConfirmation: true,
        confirmed: false,
      })
    ).toBe(false)
    expect(
      canSubmitRevisionAction({
        reason: 'unsafe digest',
        busy: false,
        requiresConfirmation: true,
        confirmed: true,
      })
    ).toBe(true)
    expect(
      canSubmitRevisionAction({
        reason: '',
        busy: false,
        requiresConfirmation: false,
        confirmed: false,
      })
    ).toBe(false)
    expect(
      canSubmitRevisionAction({
        reason: 'unsafe digest',
        busy: true,
        requiresConfirmation: false,
        confirmed: false,
      })
    ).toBe(false)
  })
})

describe('revision presentation helpers', () => {
  it('labels portability, platform and digests without promoting local-only rows', () => {
    expect(revisionPortabilityLabel('registry_verified')).toBe('Registry verified')
    expect(revisionPortabilityLabel('local_only')).toBe('Local only')
    const local = revision().runtime
    expect(revisionPlatform(local)).toBe('linux / amd64')
    expect(revisionPlatform({ ...local, variant: 'v8' })).toBe('linux / amd64 (v8)')
    expect(revisionManifestDigest(local)).toBeNull()
    expect(
      revisionManifestDigest({
        ...local,
        registry_verified: true,
        manifest_digest: 'sha256:abc',
      })
    ).toBe('sha256:abc')
    expect(revisionVolumeModeLabel('read_only')).toBe('Read-only')
    expect(revisionVolumeModeLabel('read_write')).toBe('Read-write')
  })

  it('maps limitations and detects a fully loaded history with no selectable row', () => {
    expect(revisionLimitationLabel('volume_configuration_local_only')).toContain('local only')
    expect(revisionLimitationLabel('custom_limitation')).toBe('custom_limitation')
    expect(hasNoSelectableRevision([revision({ revoked: true })], true)).toBe(true)
    expect(hasNoSelectableRevision([revision({ revoked: true })], false)).toBe(false)
    expect(hasNoSelectableRevision([revision()], true)).toBe(false)
    expect(hasNoSelectableRevision([], true)).toBe(false)
  })
})

describe('environment revision page filtering', () => {
  const verified = revision({
    id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    fingerprint: 'a'.repeat(64),
    portable_fingerprint: 'b'.repeat(64),
    portability: 'registry_verified',
    runtime: {
      ...revision().runtime,
      registry_verified: true,
      manifest_digest: 'sha256:runtime-verified',
      verified_reference: 'ghcr.io/nukehub-dev/runtime@sha256:runtime-verified',
    },
    toolchain: {
      ...revision().runtime,
      registry_verified: true,
      manifest_digest: 'sha256:toolchain-verified',
      verified_reference: 'ghcr.io/nukehub-dev/toolchain@sha256:toolchain-verified',
    },
    configuration: {
      ...revision().configuration,
      image: 'ghcr.io/nukehub-dev/runtime:stable',
      tool_image: 'ghcr.io/nukehub-dev/toolchain:stable',
    },
  })
  const local = revision({
    id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
    fingerprint: 'c'.repeat(64),
    portability: 'local_only',
    configuration: {
      ...revision().configuration,
      image: 'local/runtime:dev',
      tool_image: null,
    },
  })
  const revokedVerified = revision({
    id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    fingerprint: 'd'.repeat(64),
    portability: 'registry_verified',
    revoked: true,
    runtime: {
      ...revision().runtime,
      registry_verified: true,
      verified_reference: 'ghcr.io/nukehub-dev/runtime@sha256:revoked-runtime',
    },
  })
  const revokedLocal = revision({
    id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
    fingerprint: 'e'.repeat(64),
    portability: 'local_only',
    revoked: true,
    configuration: {
      ...revision().configuration,
      image: 'local/runtime:revoked',
      tool_image: null,
    },
  })
  const all = [verified, local, revokedVerified, revokedLocal]

  it('counts the loaded page without promoting revoked history', () => {
    expect(environmentRevisionFilterCounts(all)).toEqual({
      verified: 1,
      localOnly: 1,
      revoked: 2,
    })
  })

  it('keeps revoked rows exclusive from verified and local-only filters', () => {
    expect(filterEnvironmentRevisions(all, { filter: 'all' })).toHaveLength(4)
    expect(filterEnvironmentRevisions(all, { filter: 'registry_verified' })).toEqual([verified])
    expect(filterEnvironmentRevisions(all, { filter: 'local_only' })).toEqual([local])
    expect(filterEnvironmentRevisions(all, { filter: 'revoked' })).toEqual([
      revokedVerified,
      revokedLocal,
    ])
    expect(revisionMatchesFilter(revokedVerified, 'revoked')).toBe(true)
    expect(revisionMatchesFilter(revokedVerified, 'registry_verified')).toBe(false)
  })

  it('searches identifiers, fingerprints, images and verified references case-insensitively', () => {
    expect(revisionMatchesSearch(verified, '  AAAAAAAA-AAAA  ')).toBe(true)
    expect(revisionMatchesSearch(verified, verified.fingerprint.toUpperCase())).toBe(true)
    expect(revisionMatchesSearch(verified, 'GHCR.IO/NUKEHUB-DEV/TOOLCHAIN:STABLE')).toBe(true)
    expect(revisionMatchesSearch(verified, 'SHA256:TOOLCHAIN-VERIFIED')).toBe(true)
    expect(revisionMatchesSearch(local, 'LOCAL/RUNTIME:DEV')).toBe(true)
    expect(revisionMatchesSearch(local, 'registry-verified')).toBe(false)
    expect(filterEnvironmentRevisions(all, { query: 'revoked-runtime' })).toEqual([revokedVerified])
    expect(filterEnvironmentRevisions(all, { query: 'does-not-exist' })).toEqual([])
    expect(filterEnvironmentRevisions(all, { filter: 'local_only', query: 'dev' })).toEqual([local])
  })

  it('returns every loaded revision for an empty filter and query', () => {
    expect(filterEnvironmentRevisions(all, { filter: 'all', query: '   ' })).toEqual(all)
  })
})

describe('environment revision transport', () => {
  it('lists revisions with bounded pagination', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        items: [revision()],
        pagination: { limit: 10, offset: 20, total: 31, has_more: true },
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    const page = await fetchEnvironmentRevisions('env-1', { limit: 10, offset: 20 })

    expect(page.items).toHaveLength(1)
    expect(page.pagination).toEqual({ limit: 10, offset: 20, total: 31, has_more: true })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/environments/env-1/revisions?limit=10&offset=20')
    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({ Authorization: 'Bearer token' })
  })

  it('returns an empty page without inventing a revision', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          items: [],
          pagination: { limit: 20, offset: 0, total: 0, has_more: false },
        })
      )
    )

    const page = await fetchEnvironmentRevisions('env-1')

    expect(page.items).toEqual([])
    expect(page.pagination.total).toBe(0)
  })

  it('preserves a stable backend error code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: { code: 'permission_denied' } }, 403))
    )

    const error = await fetchEnvironmentRevisions('env-1').catch((reason: unknown) => reason)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 403, code: 'permission_denied' })
    expect(environmentRevisionErrorInfo(error)).toMatchObject({
      code: 'permission_denied',
      message: 'You do not have permission to manage environment revisions.',
      requiresLastRevisionConfirmation: false,
    })
  })

  it('verifies artifacts with a trimmed reason', async () => {
    const verified = revision({
      portability: 'registry_verified',
      portable_fingerprint: 'a'.repeat(64),
      runtime: {
        ...revision().runtime,
        registry_verified: true,
        manifest_digest: 'sha256:abc',
        verified_reference: 'ghcr.io/nukehub-dev/runtime@sha256:abc',
      },
      limitations: [],
    })
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ success: true, data: verified }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await verifyEnvironmentArtifacts('env-1', '  verify current tag  ')

    expect(result.data.portability).toBe('registry_verified')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/environments/env-1/verify-artifacts')
    expect(fetchMock.mock.calls[0][1].method).toBe('POST')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      reason: 'verify current tag',
    })
  })

  it('sends the revoke confirmation flag explicitly', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        success: true,
        data: revision({ revoked: true }),
        template_has_selectable_revision: true,
        selectable_revision_count: 2,
        already_revoked: false,
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await revokeEnvironmentRevision('rev-1', {
      reason: 'unsafe artifact',
      confirmLastRevision: false,
    })

    expect(result.selectable_revision_count).toBe(2)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/admin/environment-revisions/rev-1/revoke')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      reason: 'unsafe artifact',
      confirm_last_revision: false,
    })
  })

  it('recognizes the last-revision 409 and resends only after confirmation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            detail: {
              code: 'last_revision_confirmation_required',
              selectable_revision_count: 0,
              replacement_available: false,
            },
          },
          409
        )
      )
    )

    const error = await revokeEnvironmentRevision('rev-1', {
      reason: 'unsafe artifact',
      confirmLastRevision: false,
    }).catch((reason: unknown) => reason)

    const info = environmentRevisionErrorInfo(error)
    expect(info).toMatchObject({
      code: 'last_revision_confirmation_required',
      requiresLastRevisionConfirmation: true,
      selectableRevisionCount: 0,
      replacementAvailable: false,
    })

    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        success: true,
        data: revision({ revoked: true }),
        template_has_selectable_revision: false,
        selectable_revision_count: 0,
        already_revoked: false,
      })
    )
    vi.stubGlobal('fetch', fetchMock)

    await revokeEnvironmentRevision('rev-1', {
      reason: 'unsafe artifact',
      confirmLastRevision: true,
    })

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      reason: 'unsafe artifact',
      confirm_last_revision: true,
    })
  })

  it('maps verification availability failures to concise messages', () => {
    const cases: Array<[string, string]> = [
      ['template_inactive', 'inactive'],
      ['registry_auth_failed', 'credentials'],
      ['artifact_missing', 'not available locally'],
      ['registry_unreachable', 'could not be reached'],
      ['platform_unavailable', 'platform'],
      ['audit_unavailable', 'no change was made'],
    ]
    for (const [code, fragment] of cases) {
      const error = new ApiError('Request failed', 409)
      error.code = code
      expect(environmentRevisionErrorInfo(error).message.toLowerCase()).toContain(fragment)
      expect(environmentRevisionErrorInfo(error).code).toBe(code)
    }
  })
})
