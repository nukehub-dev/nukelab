// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { renderToStaticMarkup } from 'react-dom/server'
import type { ComponentProps } from 'react'
import { describe, expect, it } from 'vitest'
import { EnvironmentRevisionActionDialog } from './environment-revision-action-dialog'
import type { EnvironmentRevisionErrorInfo } from '../../lib/environment-revisions'
import type { EnvironmentRevisionSummary } from '../../types/environment-revisions'

const revision: EnvironmentRevisionSummary = {
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
    packages: [],
    ports: [],
    tool_mounts: [],
    environment_variable_names: [],
    volumes: [],
  },
  limitations: ['local_only_artifact'],
}

const lastRevisionError: EnvironmentRevisionErrorInfo = {
  code: 'last_revision_confirmation_required',
  message: 'This is the last selectable revision. Confirm explicitly to revoke it.',
  requiresLastRevisionConfirmation: true,
  selectableRevisionCount: 0,
  replacementAvailable: false,
}

function renderDialog(
  overrides: Partial<ComponentProps<typeof EnvironmentRevisionActionDialog>> = {}
) {
  return renderToStaticMarkup(
    <EnvironmentRevisionActionDialog
      mode="revoke"
      environmentName="Test Environment"
      revision={revision}
      busy={false}
      error={null}
      onSubmit={() => undefined}
      onClose={() => undefined}
      {...overrides}
    />
  )
}

function submitButton(html: string): string {
  return html.match(/<button[^>]*data-testid="environment-revision-action-submit"[^>]*>/)?.[0] ?? ''
}

describe('EnvironmentRevisionActionDialog', () => {
  it('requires a reason before either action can be submitted', () => {
    const verify = renderToStaticMarkup(
      <EnvironmentRevisionActionDialog
        mode="verify"
        environmentName="Test Environment"
        busy={false}
        error={null}
        onSubmit={() => undefined}
        onClose={() => undefined}
      />
    )

    expect(verify).toContain('Verify current artifacts')
    expect(verify).toContain('Required, 1-255 characters.')
    expect(submitButton(verify)).toContain('disabled=""')
    expect(verify).not.toContain('last-revision-confirmation')
  })

  it('shows the last-revision warning with an unchecked confirmation and blocked submit', () => {
    const html = renderDialog({ error: lastRevisionError })

    expect(html).toContain('This is the last selectable revision.')
    expect(html).toContain('last_revision_confirmation_required')
    expect(html).toContain('0 selectable revisions')
    expect(html).toContain('No replacement revision will be created.')
    expect(html).toContain('Revoke last revision')
    expect(html).toContain('id="environment-revision-confirm-last"')
    expect(html).not.toMatch(/id="environment-revision-confirm-last"[^>]*checked/)
    expect(submitButton(html)).toContain('disabled=""')
  })

  it('does not show a confirmation checkbox on the first revoke request', () => {
    const html = renderDialog()

    expect(html).toContain('Revoke revision')
    expect(html).toContain('Local only')
    expect(html).not.toContain('I understand this leaves the environment')
    expect(html).not.toContain('id="environment-revision-confirm-last"')
    expect(submitButton(html)).toContain('disabled=""')
  })

  it('shows a stable error code and message for non-confirmation failures', () => {
    const html = renderDialog({
      error: {
        code: 'template_inactive',
        message: 'This environment is inactive. Activate it before verifying artifacts.',
        requiresLastRevisionConfirmation: false,
        selectableRevisionCount: 0,
        replacementAvailable: false,
      },
    })

    expect(html).toContain('template_inactive')
    expect(html).toContain('This environment is inactive.')
    expect(html).not.toContain('I understand this leaves the environment')
  })
})
