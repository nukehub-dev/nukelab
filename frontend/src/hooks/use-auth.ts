// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useAuthStore } from '../stores/auth-store'

export function useAuthGuard(requireAuth = true) {
  const navigate = useNavigate()

  useEffect(() => {
    const token = localStorage.getItem('nukelab-token')

    if (requireAuth && !token) {
      // Not logged in, redirect to login
      navigate({ to: '/login' })
    } else if (!requireAuth && token) {
      // Already logged in, redirect to dashboard
      navigate({ to: '/' })
    }
  }, [requireAuth, navigate])
}

export function isAuthenticated(): boolean {
  return !!localStorage.getItem('nukelab-token')
}

export function logout(): void {
  // IIFE so callers can stay fire-and-forget while we await the backend
  // response (it may carry the identity provider's end-session URL).
  void (async () => {
    const token = localStorage.getItem('nukelab-token')
    const refreshToken = localStorage.getItem('nukelab-refresh')
    let oauthLogoutUrl: string | null = null

    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL || '/api'}/auth/logout`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      })
      if (res.ok) {
        const data = (await res.json()) as { oauth_logout_url?: string }
        oauthLogoutUrl = data.oauth_logout_url ?? null
      }
    } catch {
      // Ignore errors — local state is cleared regardless
    }

    // Clear all local state so the UI responds instantly
    localStorage.removeItem('nukelab-token')
    localStorage.removeItem('nukelab-refresh')
    // Clear server auth cookie
    document.cookie = 'nukelab_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT'
    // Clear auth store user
    useAuthStore.getState().setUser(null)
    // Hard navigation — full page reload ensures clean state. For OAuth users
    // this goes through the provider's end-session endpoint first, so the SSO
    // session is terminated too and the next login really asks for credentials.
    window.location.href = oauthLogoutUrl ?? '/login'
  })()
}
