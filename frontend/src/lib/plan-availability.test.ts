// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import { isBatchJobPlan, isServerPlan, planAvailability } from './plan-availability'
import type { Plan } from '../types/api'

function plan(overrides: Partial<Plan> = {}): Plan {
  return {
    id: 'plan-1',
    name: 'Plan',
    slug: 'plan',
    category: 'cpu',
    cpu_limit: 2,
    memory_limit: '4g',
    disk_limit: '20g',
    gpu_limit: 0,
    max_servers_per_user: 3,
    cost_per_hour: 0,
    cooldown_seconds: 0,
    is_public: true,
    visible_to_roles: ['user'],
    is_active: true,
    priority: 0,
    created_at: '2026-11-28T00:00:00',
    ...overrides,
  }
}

describe('plan availability', () => {
  it('keeps missing legacy flags enabled for compatibility', () => {
    const legacy = plan()
    expect(isServerPlan(legacy)).toBe(true)
    expect(isBatchJobPlan(legacy)).toBe(true)
  })

  it('requires an explicit job flag and a CPU-only plan', () => {
    expect(isBatchJobPlan(plan({ allow_batch_jobs: false }))).toBe(false)
    expect(isBatchJobPlan(plan({ allow_batch_jobs: true, gpu_limit: 1 }))).toBe(false)
    expect(isServerPlan(plan({ allow_servers: false }))).toBe(false)
  })

  it('labels server-only, jobs-only, shared, and unavailable plans', () => {
    expect(planAvailability(plan({ allow_servers: true, allow_batch_jobs: true })).label).toBe(
      'Servers + jobs'
    )
    expect(planAvailability(plan({ allow_servers: true, allow_batch_jobs: false })).label).toBe(
      'Servers only'
    )
    expect(planAvailability(plan({ allow_servers: false, allow_batch_jobs: true })).label).toBe(
      'Jobs only'
    )
    expect(planAvailability(plan({ allow_servers: false, allow_batch_jobs: false })).label).toBe(
      'Unavailable'
    )
    expect(
      planAvailability(plan({ allow_servers: true, allow_batch_jobs: true, gpu_limit: 1 })).label
    ).toBe('Servers only')
  })
})
