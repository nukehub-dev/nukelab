// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { OperationReconcileDialog } from './operation-reconcile-dialog'
import type { AdminOperationErrorInfo } from '../../lib/admin-operations'
import type { AdminOperation } from '../../types/admin-operations'

const operation: AdminOperation = {
  kind: 'launch',
  id: '11111111-1111-4111-8111-111111111111',
  state: 'executing',
  action: 'create',
  owner_id: null,
  created_at: '2026-01-01T00:00:00',
  updated_at: '2026-01-01T00:01:00',
  finished_at: null,
  reason_code: null,
  evidence_reason_code: null,
  recovery_required: true,
  heartbeat_age_seconds: 120,
  liveness: 'ambiguous',
  proof_source: 'worker_heartbeat_missing',
  runtime_state: 'absent',
  diagnostics: {},
  counters: {},
}

const recoveryError: AdminOperationErrorInfo = {
  code: 'recovery_required',
  message: 'Proof is still ambiguous. No mutation or reservation release occurred.',
  recoveryRequired: true,
  applied: false,
  evidence: {
    state: 'executing',
    liveness: 'ambiguous',
    proof_source: 'worker_heartbeat_missing',
    runtime_state: 'absent',
    reason_code: 'runtime_absent',
    diagnostics: { row_state: 'executing', container_count: '2' },
  },
}

function submitButton(html: string): string {
  return html.match(/<button[^>]*data-testid="operation-reconcile-submit"[^>]*>/)?.[0] ?? ''
}

describe('OperationReconcileDialog', () => {
  it('requires a reason before the proof-only reconcile can be submitted', () => {
    const html = renderToStaticMarkup(
      <OperationReconcileDialog
        operation={operation}
        busy={false}
        error={null}
        onSubmit={() => undefined}
        onClose={() => undefined}
      />
    )

    expect(html).toContain('Reconcile launch operation')
    expect(html).toContain('Required, 1-255 characters.')
    expect(html).toContain('there is no force or override control')
    expect(submitButton(html)).toContain('disabled=""')
    expect(html).not.toContain('name="force"')
  })

  it('shows the 409 proof evidence and the no-mutation message', () => {
    const html = renderToStaticMarkup(
      <OperationReconcileDialog
        operation={operation}
        busy={false}
        error={recoveryError}
        onSubmit={() => undefined}
        onClose={() => undefined}
      />
    )

    expect(html).toContain('Recovery still required')
    expect(html).toContain('No mutation or reservation release occurred')
    expect(html).toContain('Liveness ambiguous')
    expect(html).toContain('Worker heartbeat missing')
    expect(html).toContain('runtime_absent')
    expect(html).toContain('Matching containers')
    expect(submitButton(html)).toContain('disabled=""')
    expect(html).not.toContain('name="force"')
    expect(html).not.toContain('>Force<')
    expect(html).not.toContain('>Override<')
  })
})
