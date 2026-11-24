// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { AdminQueuePageContent } from './queue-page'
import { PERMISSIONS, useAuthStore } from '../../stores/auth-store'
import type { User } from '../../types/api'
import type { AdminQueuePage } from '../../types/admin-queue'

const harness = vi.hoisted(() => ({
  queue: {
    data: null as unknown,
    isLoading: false,
    isError: false,
    error: null as unknown,
    refetch: () => undefined,
    isFetching: false,
  },
  ownerUsers: [] as Array<{
    id: string
    username: string
    display_name: string
    avatar_url: string
  }>,
  ownerCalls: [] as unknown[],
}))

vi.mock('../../hooks/use-admin-queue', () => ({
  useAdminQueue: () => harness.queue,
}))

vi.mock('../../hooks/use-users', () => ({
  useUsers: (params: unknown) => {
    harness.ownerCalls.push(params)
    return {
      data: { data: harness.ownerUsers },
      isLoading: false,
      isError: false,
    }
  },
}))

vi.mock('../ui/combobox', () => ({
  Combobox: (props: {
    value: string
    options: Array<{ value: string; label: string; image?: string }>
    disabled?: boolean
  }) => (
    <div
      data-testid="mock-owner-combobox"
      data-value={props.value}
      data-disabled={String(Boolean(props.disabled))}
    >
      {props.options.map((option) => (
        <span key={option.value} data-option-value={option.value} data-option-image={option.image}>
          {option.label}
        </span>
      ))}
    </div>
  ),
}))

vi.mock('../layout/resource-page-layout', () => ({
  ResourcePageLayout: ({
    stats,
    children,
  }: {
    stats?: Array<{ title: string; value: string | number; subtitle?: string }>
    children: ReactNode
  }) => (
    <div>
      {stats?.map((stat) => (
        <p key={stat.title} data-testid="mock-queue-stat">
          {`${stat.title}=${String(stat.value)}|${stat.subtitle ?? ''}`}
        </p>
      ))}
      {children}
    </div>
  ),
}))

const ownerId = '11111111-1111-4111-8111-111111111111'

const page: AdminQueuePage = {
  items: [],
  pagination: { limit: 20, offset: 0, total: 12, has_more: false },
  summary: {
    total: 12,
    pending: 5,
    scheduled: 1,
    starting: 2,
    started: 3,
    failed: 1,
    cancelled: 0,
    recovery_required: 1,
  },
}

function adminUser(permissions: string[]): User {
  return {
    id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    username: 'admin',
    email: 'admin@example.test',
    display_name: 'Ada Admin',
    avatar_url: '',
    role: 'admin',
    permissions,
    nuke_balance: 0,
    daily_allowance: 0,
    is_active: true,
    is_verified: true,
    login_count: 1,
  } as User
}

beforeEach(() => {
  harness.queue.data = page
  harness.queue.isLoading = false
  harness.queue.isError = false
  harness.queue.error = null
  harness.queue.isFetching = false
  harness.ownerCalls = []
  harness.ownerUsers = [
    {
      id: ownerId,
      username: 'alice',
      display_name: 'Alice Admin',
      avatar_url: 'https://example.test/alice.png',
    },
    {
      id: '22222222-2222-4222-8222-222222222222',
      username: 'bob',
      display_name: 'Bob',
      avatar_url: '',
    },
  ]
  useAuthStore.setState({
    user: adminUser([
      PERMISSIONS.SERVERS_READ_ALL,
      PERMISSIONS.ADMIN_ACCESS,
      PERMISSIONS.USERS_READ,
    ]),
  })
})

afterEach(() => {
  useAuthStore.setState({ user: null })
})

describe('AdminQueuePage summary stats', () => {
  it('uses server summary counts instead of page-only counts', () => {
    const html = renderToStaticMarkup(<AdminQueuePageContent />)

    expect(html).toContain('Requests=12|All statuses, all pages')
    expect(html).toContain('Starting=2|All pages')
    expect(html).toContain('Recovery Required=1|All pages')
    expect(html).toContain('Pending=5|All pages')
    expect(html).not.toContain('On this page')
  })

  it('falls back to zero summary counts when an older payload omits them', () => {
    harness.queue.data = {
      items: [],
      pagination: { limit: 20, offset: 0, total: 12, has_more: false },
    } as unknown as AdminQueuePage

    const html = renderToStaticMarkup(<AdminQueuePageContent />)

    expect(html).toContain('Requests=0|All statuses, all pages')
    expect(html).toContain('Starting=0|All pages')
    expect(html).toContain('Recovery Required=0|All pages')
    expect(html).toContain('Pending=0|All pages')
  })
})

describe('AdminQueuePage owner filter', () => {
  it('queries the user directory and renders a searchable owner picker', () => {
    const html = renderToStaticMarkup(<AdminQueuePageContent />)

    expect(harness.ownerCalls).toEqual([{ limit: 50 }])
    expect(html).toContain('mock-owner-combobox')
    expect(html).toContain('Any owner')
    expect(html).toContain('Alice Admin (@alice)')
    expect(html).toContain('Bob (@bob)')
    expect(html).toContain(`data-option-value="${ownerId}"`)
    expect(html).toContain('data-option-image="https://example.test/alice.png"')
    expect(html).not.toContain('Owner UUID')
  })

  it('keeps the UUID input fallback and never queries users without users:read', () => {
    useAuthStore.setState({
      user: adminUser([PERMISSIONS.SERVERS_READ_ALL, PERMISSIONS.ADMIN_ACCESS]),
    })

    const html = renderToStaticMarkup(<AdminQueuePageContent />)

    expect(harness.ownerCalls).toHaveLength(0)
    expect(html).not.toContain('mock-owner-combobox')
    expect(html).toContain('Owner UUID')
    expect(html).toContain('aria-label="Owner ID"')
  })
})
