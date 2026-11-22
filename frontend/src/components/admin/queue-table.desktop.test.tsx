// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { AdminQueueTable } from './queue-table'
import type { AdminQueueEntry } from '../../types/admin-queue'

vi.mock('../../hooks/use-is-desktop', () => ({
  useIsDesktopViewport: () => true,
}))

const ownerId = '11111111-1111-4111-8111-111111111111'
const requestId = '22222222-2222-4222-8222-222222222222'
const serverId = '33333333-3333-4333-8333-333333333333'
const environmentId = '44444444-4444-4444-8444-444444444444'
const planId = '55555555-5555-4555-8555-555555555555'

function entry(overrides: Partial<AdminQueueEntry> = {}): AdminQueueEntry {
  return {
    id: requestId,
    owner_id: ownerId,
    owner_username: 'alice',
    server_id: serverId,
    server_name: 'desktop-request',
    environment_id: environmentId,
    environment_name: 'Ubuntu 24.04',
    plan_id: planId,
    plan_name: 'Starter',
    resources: { cpu: 2, memory_mib: 4096, disk_mib: 20480, gpu_count: 1 },
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

describe('AdminQueueTable desktop columns', () => {
  it('renders a compact resources column and named owner scope', () => {
    const html = renderTable([entry()])

    expect(html).toContain('Resources')
    expect(html).toContain('Owner @alice · Plan Starter')
    expect(html).toContain('Environment Ubuntu 24.04')
    expect(html).toContain('2 vCPU')
    expect(html).toContain('4 GB RAM')
    expect(html).toContain('20 GB disk')
    expect(html).toContain('1 GPU')
  })
})
