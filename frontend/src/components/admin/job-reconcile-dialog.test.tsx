// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AdminJobReconcileDialog, AdminJobReconcileOutcome } from './job-reconcile-dialog'
import type { AdminJobEntry, AdminJobReconcileResult } from '../../types/admin-jobs'

const jobId = 'f4e3f70f-4bf4-4f2d-a66c-35b6790ff9df'

const entry: AdminJobEntry = {
  id: jobId,
  state: 'recovery_required',
  reason_code: 'recovery_required',
  owner_id: '5f584904-6a94-4602-8144-66f215924270',
  owner_username: 'researcher',
  owner_display_name: 'Researcher',
  environment_name: 'Approved runtime',
  environment_display_label: 'Approved runtime',
  plan_name: 'Small research plan',
  volume_display_name: 'pilot-data',
  created_at: '2026-11-27T12:00:00',
  updated_at: '2026-11-27T12:01:00',
  finished_at: null,
  reservation_active: true,
  guard_active: true,
  heartbeat_age_seconds: 420,
  log_state: 'pending',
  cleanup_state: 'pending',
  cleanup_attempts: 2,
  can_reconcile: true,
}

function submitButton(html: string): string {
  return html.match(/<button[^>]*data-testid="admin-job-reconcile-submit"[^>]*>/)?.[0] ?? ''
}

function result(overrides: Partial<AdminJobReconcileResult> = {}): AdminJobReconcileResult {
  return {
    job: { ...entry, state: 'succeeded', can_reconcile: false },
    applied: true,
    already_terminal: false,
    outcome: 'applied',
    terminal_state: 'succeeded',
    proof_source: 'executor_absent',
    reason_code: null,
    ...overrides,
  }
}

describe('AdminJobReconcileDialog', () => {
  it('requires a bounded reason and warns that nothing can be forced', () => {
    const html = renderToStaticMarkup(
      <AdminJobReconcileDialog
        entry={entry}
        busy={false}
        error={null}
        onSubmit={() => undefined}
        onClose={() => undefined}
      />
    )

    expect(html).toContain('Reconcile batch job')
    expect(html).toContain('f4e3f70f')
    expect(html).toContain('Required, 8-500 characters.')
    expect(html).toContain('cannot force a state')
    expect(html).toContain('release a reservation or volume guard')
    expect(submitButton(html)).toContain('disabled=""')
    expect(html).not.toContain('name="force"')
  })

  it('shows the proof-insufficient error without raw payloads', () => {
    const html = renderToStaticMarkup(
      <AdminJobReconcileDialog
        entry={entry}
        busy={false}
        error={{
          code: 'proof_insufficient',
          message:
            'Proof is still insufficient. No job state, reservation, or volume guard was changed.',
        }}
        onSubmit={() => undefined}
        onClose={() => undefined}
      />
    )

    expect(html).toContain('Proof still insufficient')
    expect(html).toContain('No job state, reservation, or volume guard was changed')
    expect(html).not.toContain('/var/lib/private')
  })
})

describe('AdminJobReconcileOutcome', () => {
  it('reports an applied terminal result with its proof source', () => {
    const html = renderToStaticMarkup(<AdminJobReconcileOutcome result={result()} />)

    expect(html).toContain('Reconciliation applied')
    expect(html).toContain('Succeeded')
    expect(html).toContain('Executor absent')
  })

  it('reports a repeated reconcile as already terminal', () => {
    const html = renderToStaticMarkup(
      <AdminJobReconcileOutcome
        result={result({
          applied: false,
          already_terminal: true,
          outcome: 'already_terminal',
          terminal_state: null,
          proof_source: null,
        })}
      />
    )

    expect(html).toContain('Already terminal')
    expect(html).toContain('Repeated reconciliation made no change')
  })

  it('states that ambiguous proof released nothing', () => {
    const html = renderToStaticMarkup(
      <AdminJobReconcileOutcome
        result={result({
          applied: false,
          outcome: 'no_change',
          terminal_state: null,
          proof_source: null,
        })}
      />
    )

    expect(html).toContain('No change applied')
    expect(html).toContain('no reservation or volume guard was released')
    expect(html).toContain('No terminal transition')
  })
})
