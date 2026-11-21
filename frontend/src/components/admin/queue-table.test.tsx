// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { QueueStatusPills } from './queue-status'
import { AdminQueueTable } from './queue-table'
import type { AdminQueueEntry, AdminQueueStatus } from '../../types/admin-queue'

const ownerId = '11111111-1111-4111-8111-111111111111'
const requestId = '22222222-2222-4222-8222-222222222222'
const serverId = '33333333-3333-4333-8333-333333333333'
const environmentId = '44444444-4444-4444-8444-444444444444'
const planId = '55555555-5555-4555-8555-555555555555'

function entry(overrides: Partial<AdminQueueEntry> = {}): AdminQueueEntry {
  return {
    id: requestId,
    owner_id: ownerId,
    server_id: serverId,
    server_name: 'visible-request',
    environment_id: environmentId,
    plan_id: planId,
    status: 'pending',
    reason_code: 'capacity_wait',
    position: 1,
    priority: 0,
    requested_at: '2026-01-01T00:00:00',
    started_at: null,
    failed_at: null,
    expires_at: '2026-01-01T01:00:00',
    ...overrides,
  }
}

function renderTable(entries: AdminQueueEntry[]) {
  return renderToStaticMarkup(
    <AdminQueueTable
      entries={entries}
      totalCount={entries.length}
      page={1}
      pageCount={1}
      limit={20}
      onPageChange={() => undefined}
      onLimitChange={() => undefined}
    />
  )
}

describe('QueueStatusPills', () => {
  it('shows every bounded status label', () => {
    const statuses: AdminQueueStatus[] = [
      'pending',
      'scheduled',
      'starting',
      'started',
      'failed',
      'cancelled',
    ]
    for (const status of statuses) {
      const html = renderToStaticMarkup(<QueueStatusPills entry={entry({ status })} />)
      expect(html).toContain(
        {
          pending: 'Pending',
          scheduled: 'Scheduled',
          starting: 'Starting',
          started: 'Started',
          failed: 'Failed',
          cancelled: 'Cancelled',
        }[status]
      )
    }
  })

  it('shows recovery-required as a separate warning pill for starting work', () => {
    const html = renderToStaticMarkup(
      <QueueStatusPills
        entry={entry({ status: 'starting', reason_code: 'recovery_required', position: null })}
      />
    )

    expect(html).toContain('Starting')
    expect(html).toContain('Recovery required')
  })
})

describe('AdminQueueTable', () => {
  it('keeps a starting row without a linked operation visible', () => {
    const html = renderTable([
      entry({
        server_id: null,
        status: 'starting',
        reason_code: 'recovery_required',
        position: null,
        started_at: '2026-01-01T00:01:00',
      }),
    ])

    expect(html).toContain('visible-request')
    expect(html).toContain('Starting')
    expect(html).toContain('Recovery required')
    expect(html).toContain('No linked server')
    expect(html).toContain('Awaiting operator verification')
    expect(html).toContain('no admin cancel or retry is available')
  })

  it('renders no admin cancel, retry, or reconcile action controls', () => {
    const html = renderTable([
      entry(),
      entry({
        id: '66666666-6666-4666-8666-666666666666',
        status: 'starting',
        reason_code: 'recovery_required',
        position: null,
      }),
      entry({ id: '77777777-7777-4777-8777-777777777777', status: 'failed' }),
    ])

    expect(html).not.toContain('Cancel request')
    expect(html).not.toContain('Cancel')
    expect(html).not.toContain('Retry')
    expect(html).not.toContain('Reconcile')
  })

  it('never renders payloads, tokens, mounts, or raw exception text', () => {
    const raw = {
      ...entry(),
      request_payload: { launch_token: 'payload-token' },
      claim_token: 'claim-token',
      plan_snapshot: { mount_path: '/home/private' },
      error_message: '/private/host/path: password=secret',
    } as AdminQueueEntry
    const html = renderTable([raw])

    expect(html).toContain('visible-request')
    for (const forbidden of [
      'payload-token',
      'claim-token',
      'plan_snapshot',
      'request_payload',
      '/home/private',
      '/private/host/path',
      'password=secret',
    ]) {
      expect(html).not.toContain(forbidden)
    }
  })

  it('shows a filter-aware empty state', () => {
    const filtered = renderToStaticMarkup(
      <AdminQueueTable
        entries={[]}
        totalCount={0}
        page={1}
        pageCount={1}
        limit={20}
        hasFilters
        onClearFilters={() => undefined}
        onPageChange={() => undefined}
        onLimitChange={() => undefined}
      />
    )
    expect(filtered).toContain('No queue requests match these filters')
    expect(filtered).toContain('Clear filters')

    const empty = renderTable([])
    expect(empty).toContain('No server requests queued')
  })

  it('shows a bounded load error with a refresh-only action', () => {
    const html = renderToStaticMarkup(
      <AdminQueueTable
        entries={[]}
        totalCount={0}
        page={1}
        pageCount={1}
        limit={20}
        isError
        errorMessage="Queue visibility is temporarily unavailable. Try again later."
        onPageChange={() => undefined}
        onLimitChange={() => undefined}
        onRetry={() => undefined}
      />
    )

    expect(html).toContain('Could not load queue requests')
    expect(html).toContain('Queue visibility is temporarily unavailable')
    expect(html).toContain('Try again')
    expect(html).not.toContain('Retry')
    expect(html).not.toContain('Cancel request')
    expect(html).not.toContain('Reconcile')
  })
})
