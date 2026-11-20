// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { describe, expect, it } from 'vitest'
import { PERMISSIONS, useAuthStore } from './auth-store'
import type { User } from '../types/api'

function makeUser(permissions: string[], role = 'admin'): User {
  return {
    id: 'user-1',
    username: 'admin',
    email: 'admin@example.test',
    role,
    is_active: true,
    permissions,
  } as User
}

describe('auth permission expansion', () => {
  it('treats read_all and write_all as implying their owner-scoped grants', () => {
    useAuthStore
      .getState()
      .setUser(makeUser([PERMISSIONS.SERVERS_READ_ALL, PERMISSIONS.SERVERS_WRITE_ALL]))

    const state = useAuthStore.getState()
    expect(state.hasPermission(PERMISSIONS.SERVERS_READ_OWN)).toBe(true)
    expect(state.hasPermission(PERMISSIONS.SERVERS_WRITE_OWN)).toBe(true)
    expect(state.hasPermission(PERMISSIONS.ADMIN_ACCESS)).toBe(false)
  })

  it('expands volume, workspace, and credit implications', () => {
    useAuthStore
      .getState()
      .setUser(
        makeUser([
          PERMISSIONS.VOLUMES_WRITE_ALL,
          PERMISSIONS.WORKSPACES_READ_ALL,
          PERMISSIONS.CREDITS_READ_ALL,
        ])
      )

    const state = useAuthStore.getState()
    expect(state.hasPermission(PERMISSIONS.VOLUMES_WRITE_OWN)).toBe(true)
    expect(state.hasPermission(PERMISSIONS.VOLUMES_READ_OWN)).toBe(true)
    expect(state.hasPermission(PERMISSIONS.WORKSPACES_READ_OWN)).toBe(true)
    expect(state.hasPermission(PERMISSIONS.CREDITS_READ_OWN)).toBe(true)
  })

  it('does not invent permissions absent from the raw grant list', () => {
    useAuthStore.getState().setUser(makeUser([PERMISSIONS.SERVERS_READ_ALL], 'moderator'))

    expect(useAuthStore.getState().hasPermission(PERMISSIONS.SERVERS_WRITE_OWN)).toBe(false)
  })

  it('lets the wildcard grant satisfy permissions added after this map', () => {
    useAuthStore.getState().setUser(makeUser([PERMISSIONS.ALL], 'super_admin'))

    expect(useAuthStore.getState().hasPermission('future:permission')).toBe(true)
  })
})
