// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { EnvironmentRevisionCard } from './environment-revision-card'
import type { EnvironmentRevisionSummary } from '../../types/environment-revisions'

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
      manifest_digest: 'sha256:unverified-local-digest',
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
      environment_variable_names: ['SECRET_TOKEN_NAME'],
      volumes: [{ mount_path: '/data', mode: 'read_write' }],
    },
    limitations: ['local_only_artifact'],
    ...overrides,
  }
}

function portabilityPill(html: string): string {
  return html.match(/data-testid="revision-portability"[^>]*>(.*?)<\/span>/s)?.[1] ?? ''
}

describe('EnvironmentRevisionCard', () => {
  it('keeps a local-only revision visually distinct and hides its unverified digest', () => {
    const html = renderToStaticMarkup(
      <EnvironmentRevisionCard revision={revision()} canManage={false} />
    )

    expect(portabilityPill(html)).toContain('Local only')
    expect(html).toContain('Not registry verified')
    expect(html).toContain('No verified manifest digest captured.')
    expect(html).not.toContain('sha256:unverified-local-digest')
    expect(html).not.toContain('>Revoke<')
  })

  it('shows the verified platform and manifest digest for a portable revision', () => {
    const html = renderToStaticMarkup(
      <EnvironmentRevisionCard
        revision={revision({
          portability: 'registry_verified',
          portable_fingerprint: 'a'.repeat(64),
          runtime: {
            ...revision().runtime,
            registry_verified: true,
            manifest_digest: 'sha256:verified-platform-digest',
            verified_reference: 'ghcr.io/nukehub-dev/runtime@sha256:verified-platform-digest',
          },
          limitations: [],
        })}
        canManage={false}
      />
    )

    expect(portabilityPill(html)).toContain('Registry verified')
    expect(html).toContain('linux / amd64')
    expect(html).toContain('sha256:verified-platform-digest')
  })

  it('shows sanitized configuration names and container volume paths only', () => {
    const html = renderToStaticMarkup(
      <EnvironmentRevisionCard revision={revision()} canManage={false} />
    )

    expect(html).toContain('Environment variables (names only)')
    expect(html).toContain('SECRET_TOKEN_NAME')
    expect(html).toContain('/opt/nuke')
    expect(html).toContain('/data')
    expect(html).toContain('Read-write')
  })

  it('offers revoke only for an active revision to a manager and never on history', () => {
    const active = renderToStaticMarkup(
      <EnvironmentRevisionCard revision={revision()} canManage onRevoke={() => undefined} />
    )
    expect(active).toContain('>Revoke<')

    const revoked = renderToStaticMarkup(
      <EnvironmentRevisionCard
        revision={revision({ revoked: true, limitations: ['local_only_artifact'] })}
        canManage
        onRevoke={() => undefined}
      />
    )
    expect(revoked).toContain('Revoked')
    expect(revoked).not.toContain('>Revoke<')
    expect(revoked).not.toContain('Restore')
  })

  it('offers full-value copy controls for the revision, fingerprint, and verified digests', () => {
    const digest = `sha256:${'a'.repeat(64)}`
    const toolDigest = `sha256:${'b'.repeat(64)}`
    const html = renderToStaticMarkup(
      <EnvironmentRevisionCard
        revision={revision({
          portability: 'registry_verified',
          portable_fingerprint: 'a'.repeat(64),
          runtime: {
            ...revision().runtime,
            registry_verified: true,
            manifest_digest: digest,
            verified_reference: `ghcr.io/nukehub-dev/runtime@${digest}`,
          },
          toolchain: {
            ...revision().runtime,
            registry_verified: true,
            manifest_digest: toolDigest,
            verified_reference: `ghcr.io/nukehub-dev/toolchain@${toolDigest}`,
          },
          limitations: [],
        })}
        canManage={false}
      />
    )

    expect(html).toContain('aria-label="Copy revision ID"')
    expect(html).toContain('aria-label="Copy revision fingerprint"')
    expect(html).toContain('aria-label="Copy runtime manifest digest"')
    expect(html).toContain('aria-label="Copy toolchain manifest digest"')
  })

  it('renders bounded limitation labels instead of raw codes', () => {
    const html = renderToStaticMarkup(
      <EnvironmentRevisionCard
        revision={revision({
          limitations: ['volume_configuration_local_only', 'packages_truncated', 'custom_code'],
        })}
        canManage={false}
      />
    )

    expect(html).toContain('Template volume declarations are not portable')
    expect(html).toContain('Only the first package names are shown.')
    expect(html).toContain('custom_code')

    const bounded = renderToStaticMarkup(
      <EnvironmentRevisionCard
        revision={revision({
          limitations: [
            'local_only_artifact',
            'packages_truncated',
            'ports_truncated',
            'volume_configuration_truncated',
            'hidden_limitation_five',
            'hidden_limitation_six',
          ],
        })}
        canManage={false}
      />
    )
    expect(bounded).toContain('Show all 6 limitations')
    expect(bounded).not.toContain('hidden_limitation_five')
  })
})
