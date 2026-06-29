// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useAuthStore } from '../stores/auth-store'

interface PageGuardOptions {
  permission?: string
  permissions?: string[]
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
  const { permission, permissions, requireAll = false, redirectTo = '/' } = options

  const hasPermission = useAuthStore((state) => state.hasPermission)
  const hasAnyPermission = useAuthStore((state) => state.hasAnyPermission)
  const hasAllPermissions = useAuthStore((state) => state.hasAllPermissions)

  let allowed = true

  if (permission) {
    allowed = hasPermission(permission)
  } else if (permissions && permissions.length > 0) {
    allowed = requireAll ? hasAllPermissions(permissions) : hasAnyPermission(permissions)
  }

  useEffect(() => {
    if (!allowed) {
      navigate({ to: redirectTo })
    }
  }, [allowed, navigate, redirectTo])

  return allowed
}
