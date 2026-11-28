// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useAuthStore } from '../stores/auth-store'

interface PageGuardOptions {
  permission?: string
  permissions?: string[]
  /** Additional any-of gate applied after the primary permission check. */
  anyPermission?: string[]
  requireAll?: boolean
  redirectTo?: string
}

/**
 * Hook for page-level permission guards with automatic redirect.
 * Returns whether the user is allowed to view the page.
 *
 * @example
 * function AdminPage() {
 *   const allowed = usePageGuard({ permission: PERMISSIONS.ADMIN_ACCESS });
 *   if (!allowed) return null;
 *   return <div>Admin content</div>;
 * }
 */
export function usePageGuard(options: PageGuardOptions): boolean {
  const navigate = useNavigate()
  const { permission, permissions, anyPermission, requireAll = false, redirectTo = '/' } = options

  const user = useAuthStore((state) => state.user)
  const hasPermission = useAuthStore((state) => state.hasPermission)
  const hasAnyPermission = useAuthStore((state) => state.hasAnyPermission)
  const hasAllPermissions = useAuthStore((state) => state.hasAllPermissions)
  const hasToken = typeof window !== 'undefined' && Boolean(localStorage.getItem('nukelab-token'))
  // A deep link/refresh can render before useCurrentUser has populated the
  // persisted store. Do not redirect an authenticated request before that
  // first profile fetch has a chance to settle.
  const authPending = hasToken && !user

  let allowed = true

  if (permission) {
    allowed = hasPermission(permission)
  } else if (permissions && permissions.length > 0) {
    allowed = requireAll ? hasAllPermissions(permissions) : hasAnyPermission(permissions)
  }
  if (allowed && anyPermission && anyPermission.length > 0) {
    allowed = hasAnyPermission(anyPermission)
  }

  useEffect(() => {
    if (!authPending && !allowed) {
      navigate({ to: redirectTo })
    }
  }, [allowed, authPending, navigate, redirectTo])

  return authPending ? false : allowed
}
