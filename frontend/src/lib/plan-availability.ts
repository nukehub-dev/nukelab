// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import type { Plan } from '../types/api'

/**
 * Missing availability fields come from older API payloads. Treat them as
 * enabled for backward compatibility; the backend enforces the stored flags.
 */
export function isServerPlan(plan: Pick<Plan, 'allow_servers'>): boolean {
  return plan.allow_servers !== false
}

export function isBatchJobPlan(plan: Pick<Plan, 'allow_batch_jobs' | 'gpu_limit'>): boolean {
  return plan.allow_batch_jobs !== false && plan.gpu_limit === 0
}

export interface PlanAvailability {
  servers: boolean
  jobs: boolean
  label: string
}

export function planAvailability(plan: Plan): PlanAvailability {
  const servers = isServerPlan(plan)
  const jobs = isBatchJobPlan(plan)
  return {
    servers,
    jobs,
    label:
      servers && jobs
        ? 'Servers + jobs'
        : servers
          ? 'Servers only'
          : jobs
            ? 'Jobs only'
            : 'Unavailable',
  }
}
