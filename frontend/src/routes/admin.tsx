// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Outlet, useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'
import { useAuthStore } from '../stores/auth-store'

export const Route = createFileRoute('/admin')({
  component: AdminLayout,
})

function AdminLayout() {
  const user = useAuthStore((state) => state.user)
  const canAccessAdmin = useAuthStore((state) => state.canAccessAdmin)
  const navigate = useNavigate()
  const hasToken = typeof window !== 'undefined' && Boolean(localStorage.getItem('nukelab-token'))
  // Wait for the first /users/me/profile fetch on a deep link/refresh instead
  // of bouncing an authenticated admin to the dashboard while the store is
  // still empty.
  const authPending = hasToken && !user

  useEffect(() => {
    if (!authPending && !canAccessAdmin()) {
      navigate({ to: '/' })
    }
  }, [authPending, canAccessAdmin, navigate])

  if (authPending || !canAccessAdmin()) {
    return null
  }

  return <Outlet />
}
