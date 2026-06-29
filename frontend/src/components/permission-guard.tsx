// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useNavigate } from '@tanstack/react-router'
import { useEffect, type ReactNode } from 'react'
import { useAuthStore, PERMISSIONS } from '../stores/auth-store'

interface PermissionGuardProps {
  /** Single permission required */
  permission?: string
  /** Multiple permissions - any by default, all if requireAll=true */
  permissions?: string[]
  /** If true, user must have ALL permissions in the list. If false, any. */
  requireAll?: boolean
  /** Where to redirect if permission check fails */
  redirectTo?: string
  /** Content to show while checking or if denied (default: null) */
  fallback?: ReactNode
  children: ReactNode
}

/**
 * Reusable permission guard component.
 * Checks permissions and redirects if the user is not allowed.
 *
 * @example
 * <PermissionGuard permission={PERMISSIONS.USERS_READ}>
 *   <UsersPage />
 * </PermissionGuard>
 *
 * @example
 * <PermissionGuard permissions={[PERMISSIONS.USERS_CREATE, PERMISSIONS.USERS_UPDATE]} requireAll>
 *   <CreateUserPage />
 * </PermissionGuard>
 */
export function PermissionGuard({
  permission,
  permissions,
  requireAll = false,
  redirectTo = '/',
  fallback = null,
  children,
}: PermissionGuardProps) {
  const navigate = useNavigate()
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

  if (!allowed) {
    return fallback
  }

  return children
}

// Re-export PERMISSIONS for convenience
export { PERMISSIONS }
