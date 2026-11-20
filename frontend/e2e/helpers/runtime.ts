// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Shared runtime configuration for Playwright specs.
 *
 * Local development (default): the config starts Vite on
 * http://localhost:5173. External mode (`E2E_EXTERNAL_SERVER=1`) targets a
 * prestarted single-origin stack such as the frontend behind Traefik on
 * http://localhost:8080, and Playwright never starts Vite.
 */

function stripTrailingSlashes(value: string): string {
  return value.replace(/\/+$/, '')
}

export const EXTERNAL_SERVER =
  process.env.E2E_EXTERNAL_SERVER === '1' || process.env.E2E_EXTERNAL_SERVER === 'true'

export const BASE_URL = stripTrailingSlashes(
  process.env.BASE_URL || (EXTERNAL_SERVER ? 'http://localhost:8080' : 'http://localhost:5173')
)

export const ADMIN_USERNAME = process.env.TEST_ADMIN_USERNAME || 'admin'
export const ADMIN_PASSWORD = process.env.TEST_ADMIN_PASSWORD || 'admin123'

/** Runtime image used by ordinary launch/lifecycle specs. */
export const E2E_RUNTIME_IMAGE = process.env.E2E_RUNTIME_IMAGE || 'nukelab-environment-dev:latest'

/** Secondary runtime variant used by identity/recreation scenarios. */
export const E2E_RUNTIME_IMAGE_B = process.env.E2E_RUNTIME_IMAGE_B || 'nukelab-e2e-runtime:b'

/** Workspace/IDE image used by the workspace gateway spec. */
export const E2E_WORKSPACE_IMAGE =
  process.env.E2E_WORKSPACE_IMAGE || 'nukelab-environment-workspace:latest'

/**
 * Build a unique, backend-safe identifier for users, servers, volumes, and
 * environment templates. Server names only accept [A-Za-z0-9_-] and must start
 * with an alphanumeric character; every generated value starts with `prefix`.
 */
export function uniqueName(prefix: string): string {
  const stamp = Date.now().toString(36)
  const suffix = Math.random().toString(36).slice(2, 8)
  return `${prefix}-${stamp}-${suffix}`
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}
