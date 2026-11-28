// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import type { Environment, Plan } from '../types/api'
import { formatBytes, formatPlanResource } from './utils'

/**
 * Catalog entries may carry an explicit recommendation marker. The current
 * API does not expose one yet, so guidance falls back to the only eligible
 * entry when the catalog is unambiguous.
 */
export interface DeployCatalogPlan extends Plan {
  is_starter?: boolean
}

export interface DeployCatalogEnvironment extends Environment {
  is_starter?: boolean
}

export interface DeployCatalogOptions {
  canAccessAdmin?: boolean
}

export type DeployDefaultSource = 'saved' | 'starter' | 'single' | 'none'

export interface DeployDefaultResolution {
  plans: DeployCatalogPlan[]
  environments: DeployCatalogEnvironment[]
  plan: DeployCatalogPlan | null
  environment: DeployCatalogEnvironment | null
  planId: string
  environmentId: string
  planSource: DeployDefaultSource
  environmentSource: DeployDefaultSource
  savedPlanStale: boolean
  savedEnvironmentStale: boolean
  needsPlanChoice: boolean
  needsEnvironmentChoice: boolean
}

export interface DeployVolumeChoice {
  volume_id: string
  mount_path: string
  max_size_gb: number
}

export interface DeployVolumeRecord {
  id: string
  display_name: string
  size_bytes: number
  max_size_bytes?: number | null
}

export interface DeployVolumeReview {
  action: string
  detail: string
  missing: boolean
}

/**
 * Plans an ordinary owner can launch with. Admins receive the whole catalog,
 * so their view must still resolve the baseline user-visible entries used by
 * the first-run guidance and the setup checklist.
 */
export function isDeployPlanEligible(
  plan: DeployCatalogPlan,
  { canAccessAdmin = false }: DeployCatalogOptions = {}
): boolean {
  if (!plan.is_active) return false
  if (!canAccessAdmin) return true
  return plan.is_public || (plan.visible_to_roles || []).includes('user')
}

export function isDeployEnvironmentEligible(
  environment: DeployCatalogEnvironment,
  { canAccessAdmin = false }: DeployCatalogOptions = {}
): boolean {
  if (!environment.is_active) return false
  return canAccessAdmin ? environment.is_public : true
}

export function eligibleDeployPlans(
  plans: DeployCatalogPlan[],
  options: DeployCatalogOptions = {}
): DeployCatalogPlan[] {
  return plans.filter((plan) => isDeployPlanEligible(plan, options))
}

export function eligibleDeployEnvironments(
  environments: DeployCatalogEnvironment[],
  options: DeployCatalogOptions = {}
): DeployCatalogEnvironment[] {
  return environments.filter((environment) => isDeployEnvironmentEligible(environment, options))
}

function findSavedRecord<T extends { id: string; slug: string }>(
  value: string | undefined,
  records: T[]
): T | undefined {
  if (!value) return undefined
  return records.find((record) => record.id === value || record.slug === value)
}

function chooseDefault<T extends { id: string; slug: string; is_starter?: boolean }>(
  savedValue: string | undefined,
  eligible: T[]
): { record: T | null; source: DeployDefaultSource; savedStale: boolean } {
  const saved = findSavedRecord(savedValue, eligible)
  if (saved) return { record: saved, source: 'saved', savedStale: false }

  const savedStale = Boolean(savedValue)
  const marked = eligible.filter((record) => record.is_starter === true)
  if (marked.length === 1) {
    return { record: marked[0], source: 'starter', savedStale }
  }
  if (eligible.length === 1) {
    return { record: eligible[0], source: 'single', savedStale }
  }
  return { record: null, source: 'none', savedStale }
}

/**
 * Resolve preselectable catalog records without guessing identifiers. Saved
 * values may be either IDs or slugs; they are honored only while the matching
 * record is still eligible. Otherwise the catalog's single/marked starter is
 * used, or the caller is told it must ask for an explicit choice.
 */
export function resolveDeployDefaults({
  plans,
  environments,
  savedPlanId,
  savedEnvironmentId,
  canAccessAdmin = false,
}: {
  plans: DeployCatalogPlan[]
  environments: DeployCatalogEnvironment[]
  savedPlanId?: string
  savedEnvironmentId?: string
  canAccessAdmin?: boolean
}): DeployDefaultResolution {
  const eligiblePlans = eligibleDeployPlans(plans, { canAccessAdmin })
  const eligibleEnvironments = eligibleDeployEnvironments(environments, { canAccessAdmin })

  const planChoice = chooseDefault(savedPlanId, eligiblePlans)
  const environmentChoice = chooseDefault(savedEnvironmentId, eligibleEnvironments)

  return {
    plans: eligiblePlans,
    environments: eligibleEnvironments,
    plan: planChoice.record,
    environment: environmentChoice.record,
    planId: planChoice.record?.id ?? '',
    environmentId: environmentChoice.record?.id ?? '',
    planSource: planChoice.source,
    environmentSource: environmentChoice.source,
    savedPlanStale: planChoice.savedStale,
    savedEnvironmentStale: environmentChoice.savedStale,
    needsPlanChoice: !planChoice.record && eligiblePlans.length > 0,
    needsEnvironmentChoice: !environmentChoice.record && eligibleEnvironments.length > 0,
  }
}

export function resolveDeployMountPath(
  mountPath: string,
  index: number,
  username = 'user'
): string {
  if (mountPath) return mountPath
  return index === 0 ? `/home/${username}` : '/data'
}

/**
 * Describe what happens to private storage for one mount so the review can
 * distinguish a new volume from a reused one without inventing a volume name.
 */
export function describeDeployVolume(
  choice: DeployVolumeChoice,
  volumes: DeployVolumeRecord[],
  username = 'user',
  index = 0
): DeployVolumeReview {
  const mountPath = resolveDeployMountPath(choice.mount_path, index, username)
  if (!choice.volume_id) {
    return {
      action: 'Create a new private volume',
      detail: `${choice.max_size_gb} GB limit · mounted at ${mountPath}`,
      missing: false,
    }
  }

  const volume = volumes.find((record) => record.id === choice.volume_id)
  if (!volume) {
    return {
      action: 'Saved volume is no longer available',
      detail: `Choose a current volume for ${mountPath}`,
      missing: true,
    }
  }

  const usage = volume.max_size_bytes
    ? `${formatBytes(volume.max_size_bytes)} capacity${
        volume.size_bytes > 0 ? `, ${formatBytes(volume.size_bytes)} used` : ''
      }`
    : volume.size_bytes > 0
      ? `${formatBytes(volume.size_bytes)} used`
      : 'Empty'
  return {
    action: `Reuse ${volume.display_name}`,
    detail: `${usage} · mounted at ${mountPath}`,
    missing: false,
  }
}

export function describeDeployCost(plan: Pick<Plan, 'cost_per_hour'> | null): string {
  if (!plan) return 'Choose a plan'
  return plan.cost_per_hour > 0 ? `${plan.cost_per_hour} NUKE/hour while running` : 'No NUKE charge'
}

export function summarizeDeployPlan(plan: Plan | null, eligibleCount = 0): string {
  if (!plan) {
    return eligibleCount > 1
      ? `${eligibleCount} eligible plans — choose one when you launch`
      : 'Choose a plan when you launch'
  }
  return `${plan.name} · ${plan.cpu_limit} CPU · ${formatPlanResource(plan.memory_limit)} RAM · ${formatPlanResource(plan.disk_limit)} disk`
}

export function summarizeDeployEnvironment(
  environment: Environment | null,
  eligibleCount = 0
): string {
  if (!environment) {
    return eligibleCount > 1
      ? `${eligibleCount} eligible environments — choose one when you launch`
      : 'Choose an environment when you launch'
  }
  return environment.name
}
