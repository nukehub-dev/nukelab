// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { OperationDetailContent, OperationReconcileOutcome } from './operation-detail'
import { OperationErrorNotice } from './operation-error-notice'
import { OperationStatusPills } from './operation-status'
import type { AdminOperation, AdminOperationReconcileResult } from '../../types/admin-operations'
import type { AdminOperationErrorInfo } from '../../lib/admin-operations'

function operation(overrides: Partial<AdminOperation> = {}): AdminOperation {
  return {
    kind: 'launch',
    id: '11111111-1111-4111-8111-111111111111',
    state: 'executing',
    action: 'create',
    owner_id: '22222222-2222-4222-8222-222222222222',
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:01:00',
    finished_at: null,
    reason_code: null,
    evidence_reason_code: 'runtime_absent',
    recovery_required: false,
    heartbeat_age_seconds: 5,
    liveness: 'stopped',
    proof_source: 'graceful_marker',
    runtime_state: 'absent',
    diagnostics: { row_state: 'executing', container_count: '2' },
    counters: { container_count: 2 },
    ...overrides,
  }
}

function result(
  overrides: Partial<AdminOperationReconcileResult> = {}
): AdminOperationReconcileResult {
  return {
    ...operation({ state: 'failed' }),
    previous_state: 'executing',
    applied: true,
    terminal_state: 'failed',
    ...overrides,
  }
}

describe('OperationStatusPills', () => {
  it('shows recovery-required, liveness, and runtime evidence pills', () => {
    const html = renderToStaticMarkup(
      <OperationStatusPills
        operation={operation({
          kind: 'backup',
          state: 'recovery_required',
          recovery_required: true,
          liveness: 'ambiguous',
          runtime_state: 'ambiguous',
        })}
      />
    )

    expect(html).toContain('Recovery required')
    expect(html).toContain('Liveness ambiguous')
    expect(html).toContain('Runtime ambiguous')
  })
})

describe('OperationDetailContent', () => {
  it('renders sanitized evidence without foreign paths or raw diagnostics', () => {
    const html = renderToStaticMarkup(
      <OperationDetailContent
        operation={operation({
          diagnostics: {
            row_state: 'executing',
            container_count: '2',
            raw_docker_inspect: '/srv/private/token',
            health_status: 'healthy',
          },
          counters: { container_count: 2, unknown_counter: 9 },
        })}
        canManage={false}
      />
    )

    expect(html).toContain('Executor stopped')
    expect(html).toContain('Graceful shutdown marker')
    expect(html).toContain('Runtime absent')
    expect(html).toContain('Sanitized diagnostics')
    expect(html).toContain('Row state')
    expect(html).toContain('Matching containers')
    expect(html).toContain('Health')
    expect(html).not.toContain('raw_docker_inspect')
    expect(html).not.toContain('/srv/private/token')
    expect(html).not.toContain('unknown_counter')
    expect(html).toContain('no force or override control')
  })

  it('gates reconcile behind manage permission for an active operation', () => {
    const reader = renderToStaticMarkup(
      <OperationDetailContent operation={operation()} canManage={false} />
    )
    const manager = renderToStaticMarkup(
      <OperationDetailContent operation={operation()} canManage onReconcile={() => undefined} />
    )

    expect(reader).not.toContain('Reconcile operation')
    expect(reader).toContain('Reconcile requires operations manage and admin access.')
    expect(manager).toContain('Reconcile operation')
  })

  it('does not offer reconcile on an immutable terminal operation', () => {
    const html = renderToStaticMarkup(
      <OperationDetailContent
        operation={operation({ state: 'failed', recovery_required: false })}
        canManage
        onReconcile={() => undefined}
      />
    )

    expect(html).toContain('Terminal operations are immutable')
    expect(html).not.toContain('Reconcile operation')
  })
})

describe('OperationReconcileOutcome', () => {
  it('reports applied, previous, current, and terminal state', () => {
    const html = renderToStaticMarkup(<OperationReconcileOutcome result={result()} />)

    expect(html).toContain('Reconciliation applied')
    expect(html).toContain('Applied')
    expect(html).toContain('Yes')
    expect(html).toContain('Executing')
    expect(html).toContain('Failed')
    expect(html).toContain('Terminal state')
  })

  it('never claims volume success when the API did not apply a mutation', () => {
    const html = renderToStaticMarkup(
      <OperationReconcileOutcome
        result={result({
          kind: 'backup',
          state: 'in_progress',
          previous_state: 'in_progress',
          applied: false,
          terminal_state: 'succeeded',
        })}
      />
    )

    expect(html).toContain('No state change applied')
    expect(html).not.toContain('Reconciliation applied')
    expect(html).toContain('Volume completion still requires the recovery service')
    expect(html).toContain('No')
  })
})

describe('OperationErrorNotice', () => {
  it('shows the 409 evidence and states that nothing was mutated', () => {
    const error: AdminOperationErrorInfo = {
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
    const html = renderToStaticMarkup(<OperationErrorNotice error={error} />)

    expect(html).toContain('Recovery still required')
    expect(html).toContain('No mutation or reservation release occurred')
    expect(html).toContain('Liveness ambiguous')
    expect(html).toContain('Worker heartbeat missing')
    expect(html).toContain('runtime_absent')
    expect(html).toContain('Row state')
    expect(html).not.toContain('force')
    expect(html).not.toContain('override')
  })
})
