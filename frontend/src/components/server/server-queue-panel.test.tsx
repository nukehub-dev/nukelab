// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { QueueRecoveryNotice, QueueRequestCard, QueueRequestDetail } from './server-queue-panel'
import type { QueueStatus, ServerQueueEntry } from '../../types/server-queue'

const requestId = '22222222-2222-4222-8222-222222222222'

function entry(overrides: Partial<ServerQueueEntry> = {}): ServerQueueEntry {
  return {
    id: requestId,
    request: {
      name: 'owner-request',
      plan_id: '55555555-5555-4555-8555-555555555555',
      environment_id: '44444444-4444-4444-8444-444444444444',
      resources: { cpu: 2, memory_mib: 2048, disk_mib: 1024, gpu_count: 0 },
    },
    status: 'pending' as QueueStatus,
    position: 1,
    reason_code: 'capacity_wait',
    message: 'Waiting for available capacity.',
    requested_at: '2026-01-01T00:00:00',
    expires_at: '2026-01-01T01:00:00',
    started_at: null,
    server_id: null,
    can_cancel: true,
    ...overrides,
  }
}

function cardHtml(value: ServerQueueEntry, canManage = true) {
  return renderToStaticMarkup(
    <QueueRequestCard
      entry={value}
      index={0}
      planName="Small"
      environmentName="Base"
      canManage={canManage}
      cancelPending={false}
      onSelect={() => undefined}
      onCancel={() => undefined}
    />
  )
}

describe('QueueRecoveryNotice', () => {
  it('shows the support and resubmit path for recovery-required requests', () => {
    const html = renderToStaticMarkup(<QueueRecoveryNotice reasonCode="recovery_required" />)

    expect(html).toContain('Operator verification required')
    expect(html).toContain('Contact support before')
    expect(html).toContain('resubmit only after support confirms')
    expect(html).toContain('No admin retry is available')
  })

  it('is absent for other reason codes and missing reasons', () => {
    expect(renderToStaticMarkup(<QueueRecoveryNotice reasonCode={null} />)).toBe('')
    expect(renderToStaticMarkup(<QueueRecoveryNotice reasonCode="capacity_wait" />)).toBe('')
  })
})

describe('owner queue request actions', () => {
  it('offers cancellation only while a request is pending', () => {
    const pending = cardHtml(entry({ status: 'pending', can_cancel: true }))
    expect(pending).toContain('Cancel request')

    const starting = cardHtml(
      entry({
        status: 'starting',
        position: null,
        reason_code: 'recovery_required',
        can_cancel: true,
        message: '/home/private token=secret',
      })
    )
    expect(starting).toContain('Operator verification required')
    expect(starting).not.toContain('Cancel request')
    expect(starting).not.toContain('/home/private')
    expect(starting).not.toContain('token=secret')

    const started = cardHtml(entry({ status: 'started', position: null, can_cancel: false }))
    expect(started).not.toContain('Cancel request')
  })

  it('does not show cancellation when the owner lacks write permission', () => {
    const html = cardHtml(entry({ status: 'pending', can_cancel: true }), false)
    expect(html).not.toContain('Cancel request')
  })

  it('shows recovery guidance in the request detail without foreign metadata', () => {
    const html = renderToStaticMarkup(
      <QueueRequestDetail
        entry={entry({
          status: 'starting',
          position: null,
          reason_code: 'recovery_required',
          can_cancel: false,
          message: '/home/private token=secret',
        })}
        planName="Small"
        environmentName="Base"
        canManage
        cancelPending={false}
        onCancel={() => undefined}
        onClose={() => undefined}
      />
    )

    expect(html).toContain('Operator verification required')
    expect(html).toContain('resubmit only after support confirms')
    expect(html).toContain('Operator verification required')
    expect(html).not.toContain('Cancel request')
    expect(html).not.toContain('/home/private')
    expect(html).not.toContain('token=secret')
    expect(html).not.toContain('request_payload')
    expect(html).not.toContain('claim_token')
    expect(html).not.toContain('plan_snapshot')
  })
})
