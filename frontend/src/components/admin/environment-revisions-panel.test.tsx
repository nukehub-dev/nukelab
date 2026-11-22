// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EnvironmentRevisionsPanel, RevisionFilterEmptyState } from './environment-revisions-panel'
import { useAuthStore } from '../../stores/auth-store'
import type { Environment } from '../../types/api'
import type {
  EnvironmentRevisionPage,
  EnvironmentRevisionSummary,
} from '../../types/environment-revisions'

const mockState = vi.hoisted(() => ({
  page: null as EnvironmentRevisionPage | null,
}))

vi.mock('../../hooks/use-environment-revisions', () => ({
  useEnvironmentRevisions: () => ({
    data: mockState.page,
    isLoading: false,
    isError: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  }),
  useEnvironmentRevisionActions: () => ({
    verifyArtifacts: { mutate: vi.fn(), reset: vi.fn(), isPending: false },
    revokeRevision: { mutate: vi.fn(), reset: vi.fn(), isPending: false },
  }),
}))

const environment: Environment = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Test Environment',
  slug: 'test-environment',
  image: 'ghcr.io/nukehub-dev/runtime:1',
  is_active: true,
  is_public: true,
  created_at: '2026-01-01T00:00:00',
}

function revision(overrides: Partial<EnvironmentRevisionSummary> = {}): EnvironmentRevisionSummary {
  return {
    id: '22222222-2222-4222-8222-222222222222',
    template_id: environment.id,
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
      packages: [],
      ports: [],
      tool_mounts: [],
      environment_variable_names: [],
      volumes: [],
    },
    limitations: ['local_only_artifact'],
    ...overrides,
  }
}

function renderPanel() {
  return renderToStaticMarkup(
    <EnvironmentRevisionsPanel environment={environment} onClose={() => undefined} />
  )
}

beforeEach(() => {
  useAuthStore.setState({
    user: {
      id: '33333333-3333-4333-8333-333333333333',
      username: 'admin',
      email: 'admin@example.com',
      display_name: 'Admin',
      avatar_url: '',
      role: 'admin',
      permissions: ['*'],
      nuke_balance: 0,
      daily_allowance: 0,
      is_active: true,
      is_verified: true,
      login_count: 0,
    },
  })
  mockState.page = {
    items: [
      revision({
        id: '44444444-4444-4444-8444-444444444444',
        portability: 'registry_verified',
        runtime: {
          ...revision().runtime,
          registry_verified: true,
          verified_reference: 'ghcr.io/nukehub-dev/runtime@sha256:verified',
        },
      }),
      revision({ id: '55555555-5555-4555-8555-555555555555' }),
      revision({ id: '66666666-6666-4666-8666-666666666666', revoked: true }),
    ],
    pagination: { limit: 10, offset: 0, total: 25, has_more: true },
  }
})

describe('EnvironmentRevisionsPanel filters', () => {
  it('keeps loaded-page summary counts and labels the filter scope', () => {
    const html = renderPanel()

    expect(html).toContain('Verified 1')
    expect(html).toContain('Local only 1')
    expect(html).toContain('Revoked 1')
    expect(html).toContain('On this page')
    expect(html).toContain('Filter revisions on this page')
    expect(html).toContain('Search revisions on this page')
  })

  it('offers all, verified, local-only and revoked filter chips', () => {
    const html = renderPanel()

    expect(html).toMatch(/data-testid="revision-filter-all"[^>]*aria-pressed="true"[^>]*>All</)
    expect(html).toContain('Registry verified')
    expect(html).toContain('Local only')
    expect(html).toMatch(
      /data-testid="revision-filter-revoked"[^>]*aria-pressed="false"[^>]*>Revoked</
    )
  })

  it('keeps server pagination and load-more controls intact', () => {
    const html = renderPanel()

    expect(html).toContain('Showing 1-3 of 25')
    expect(html).toContain('Load more')
  })

  it('shows a clear-filters action when no loaded revision matches', () => {
    const html = renderToStaticMarkup(<RevisionFilterEmptyState onClear={() => undefined} />)

    expect(html).toContain('No revisions match these filters')
    expect(html).toContain('Filters and search apply only to the revisions loaded on this page.')
    expect(html).toContain('Clear filters')
  })
})
