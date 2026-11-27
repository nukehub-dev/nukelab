// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import type { Environment, Plan } from '../types/api'
import {
  describeDeployCost,
  describeDeployVolume,
  eligibleDeployEnvironments,
  eligibleDeployPlans,
  resolveDeployDefaults,
  resolveDeployMountPath,
  summarizeDeployPlan,
} from './deploy-defaults'

function plan(overrides: Partial<Plan> = {}): Plan {
  return {
    id: 'plan',
    name: 'Small',
    slug: 'small',
    category: 'cpu',
    cpu_limit: 2,
    memory_limit: '4g',
    disk_limit: '20g',
    gpu_limit: 0,
    max_servers_per_user: 3,
    cost_per_hour: 1,
    cooldown_seconds: 0,
    is_public: false,
    visible_to_roles: ['user'],
    is_active: true,
    priority: 0,
    created_at: '2026-11-15T12:00:00',
    ...overrides,
  }
}

function environment(overrides: Partial<Environment> = {}): Environment {
  return {
    id: 'env',
    name: 'Workspace',
    slug: 'workspace',
    image: 'workspace:latest',
    is_active: true,
    is_public: true,
    created_at: '2026-11-15T12:00:00',
    ...overrides,
  }
}

describe('catalog eligibility', () => {
  it('excludes inactive entries for every audience', () => {
    expect(eligibleDeployPlans([plan({ is_active: false })])).toEqual([])
    expect(eligibleDeployEnvironments([environment({ is_active: false })])).toEqual([])
  })

  it('keeps role-visible plans and public environments for admins', () => {
    const rolePlan = plan({ id: 'role-plan', slug: 'role-plan', visible_to_roles: ['user'] })
    const publicPlan = plan({ id: 'public-plan', slug: 'public-plan', is_public: true })
    const adminOnlyPlan = plan({
      id: 'admin-plan',
      slug: 'admin-plan',
      visible_to_roles: ['admin'],
    })
    const publicEnvironment = environment({ id: 'public-env', slug: 'public-env' })
    const privateEnvironment = environment({
      id: 'private-env',
      slug: 'private-env',
      is_public: false,
    })

    expect(
      eligibleDeployPlans([rolePlan, publicPlan, adminOnlyPlan], { canAccessAdmin: true }).map(
        (item) => item.id
      )
    ).toEqual(['role-plan', 'public-plan'])
    expect(
      eligibleDeployEnvironments([publicEnvironment, privateEnvironment], {
        canAccessAdmin: true,
      }).map((item) => item.id)
    ).toEqual(['public-env'])
  })

  it('trusts the owner-scoped catalog returned for ordinary users', () => {
    const directGrant = plan({ id: 'grant', slug: 'grant', is_public: false, visible_to_roles: [] })
    const publicEnvironment = environment({ id: 'public-env', slug: 'public-env' })
    const privateEnvironment = environment({
      id: 'private-env',
      slug: 'private-env',
      is_public: false,
    })

    expect(eligibleDeployPlans([directGrant]).map((item) => item.id)).toEqual(['grant'])
    expect(eligibleDeployEnvironments([publicEnvironment, privateEnvironment])).toHaveLength(2)
  })
})

describe('default selection', () => {
  it('preselects the only eligible plan and environment without saved values', () => {
    const result = resolveDeployDefaults({
      plans: [plan({ id: 'plan-small', slug: 'small' }), plan({ id: 'legacy', is_active: false })],
      environments: [
        environment({ id: 'env-workspace', slug: 'workspace' }),
        environment({ id: 'env-private', is_public: false }),
      ],
      canAccessAdmin: true,
    })

    expect(result.planId).toBe('plan-small')
    expect(result.environmentId).toBe('env-workspace')
    expect(result.planSource).toBe('single')
    expect(result.environmentSource).toBe('single')
    expect(result.needsPlanChoice).toBe(false)
    expect(result.needsEnvironmentChoice).toBe(false)
  })

  it('asks for a choice when several eligible plans exist', () => {
    const result = resolveDeployDefaults({
      plans: [
        plan({ id: 'plan-small', slug: 'small' }),
        plan({ id: 'plan-medium', slug: 'medium' }),
      ],
      environments: [environment()],
    })

    expect(result.plan).toBeNull()
    expect(result.planId).toBe('')
    expect(result.needsPlanChoice).toBe(true)
    expect(result.environmentId).toBe('env')
  })

  it('honors saved choices by id or slug while they remain eligible', () => {
    const result = resolveDeployDefaults({
      plans: [
        plan({ id: 'plan-small', slug: 'small' }),
        plan({ id: 'plan-medium', slug: 'medium' }),
      ],
      environments: [environment({ id: 'env-workspace', slug: 'workspace' })],
      savedPlanId: 'medium',
      savedEnvironmentId: 'env-workspace',
    })

    expect(result.planId).toBe('plan-medium')
    expect(result.planSource).toBe('saved')
    expect(result.environmentId).toBe('env-workspace')
    expect(result.environmentSource).toBe('saved')
    expect(result.savedPlanStale).toBe(false)
  })

  it('uses an explicitly marked starter when several entries exist', () => {
    const result = resolveDeployDefaults({
      plans: [
        { ...plan({ id: 'plan-starter', slug: 'starter' }), is_starter: true },
        plan({ id: 'plan-large', slug: 'large' }),
      ],
      environments: [
        { ...environment({ id: 'env-starter' }), is_starter: true },
        environment({ id: 'env-other', slug: 'other' }),
      ],
    })

    expect(result.planId).toBe('plan-starter')
    expect(result.planSource).toBe('starter')
    expect(result.environmentId).toBe('env-starter')
    expect(result.environmentSource).toBe('starter')
  })

  it('does not guess when more than one entry is marked as a starter', () => {
    const result = resolveDeployDefaults({
      plans: [
        { ...plan({ id: 'plan-a', slug: 'a' }), is_starter: true },
        { ...plan({ id: 'plan-b', slug: 'b' }), is_starter: true },
      ],
      environments: [environment()],
    })

    expect(result.plan).toBeNull()
    expect(result.needsPlanChoice).toBe(true)
  })

  it('reports a stale saved plan and requires an explicit choice when ambiguous', () => {
    const result = resolveDeployDefaults({
      plans: [
        plan({ id: 'plan-small', slug: 'small' }),
        plan({ id: 'plan-medium', slug: 'medium' }),
      ],
      environments: [environment()],
      savedPlanId: 'retired-plan',
    })

    expect(result.plan).toBeNull()
    expect(result.savedPlanStale).toBe(true)
    expect(result.needsPlanChoice).toBe(true)
  })

  it('falls back to the only eligible plan while reporting a stale saved plan', () => {
    const result = resolveDeployDefaults({
      plans: [plan({ id: 'plan-small', slug: 'small' })],
      environments: [environment()],
      savedPlanId: 'retired-plan',
    })

    expect(result.planId).toBe('plan-small')
    expect(result.planSource).toBe('single')
    expect(result.savedPlanStale).toBe(true)
  })

  it('does not honor a saved plan that is now inactive', () => {
    const result = resolveDeployDefaults({
      plans: [
        plan({ id: 'plan-small', slug: 'small' }),
        plan({ id: 'plan-medium', slug: 'medium' }),
        plan({ id: 'plan-legacy', slug: 'legacy', is_active: false }),
      ],
      environments: [environment()],
      savedPlanId: 'plan-legacy',
    })

    expect(result.plan).toBeNull()
    expect(result.savedPlanStale).toBe(true)
  })
})

describe('review summaries', () => {
  it('describes new, reused and unavailable private volumes', () => {
    expect(
      describeDeployVolume({ volume_id: '', mount_path: '', max_size_gb: 10 }, [], 'researcher', 0)
    ).toEqual({
      action: 'Create a new private volume',
      detail: '10 GB limit · mounted at /home/researcher',
      missing: false,
    })

    expect(
      describeDeployVolume(
        { volume_id: 'volume-data', mount_path: '/data', max_size_gb: 10 },
        [{ id: 'volume-data', display_name: 'analysis-data', size_bytes: 2 * 1024 ** 3 }],
        'researcher',
        0
      )
    ).toEqual({
      action: 'Reuse analysis-data',
      detail: '2 GB used · mounted at /data',
      missing: false,
    })

    expect(
      describeDeployVolume(
        { volume_id: 'volume-gone', mount_path: '', max_size_gb: 10 },
        [],
        'researcher',
        0
      )
    ).toEqual({
      action: 'Saved volume is no longer available',
      detail: 'Choose a current volume for /home/researcher',
      missing: true,
    })
  })

  it('uses distinct default mount paths', () => {
    expect(resolveDeployMountPath('', 0, 'researcher')).toBe('/home/researcher')
    expect(resolveDeployMountPath('', 1, 'researcher')).toBe('/data')
    expect(resolveDeployMountPath('/work', 1, 'researcher')).toBe('/work')
  })

  it('shows a charging rate only for paid plans', () => {
    expect(describeDeployCost(null)).toBe('Choose a plan')
    expect(describeDeployCost({ cost_per_hour: 0 })).toBe('No NUKE charge')
    expect(describeDeployCost({ cost_per_hour: 2 })).toBe('2 NUKE/hour while running')
  })

  it('summarizes an ambiguous plan catalog honestly', () => {
    expect(summarizeDeployPlan(null, 3)).toBe('3 eligible plans — choose one when you launch')
    expect(summarizeDeployPlan(plan(), 3)).toBe('Small · 2 CPU · 4 GB RAM · 20 GB disk')
  })
})
