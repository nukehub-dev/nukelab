// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { PERMISSIONS, useAuthStore } from '../stores/auth-store'

interface Shortcut {
  key: string
  modifiers?: ('ctrl' | 'alt' | 'shift' | 'meta')[]
  description: string
  action: () => void
  preventDefault?: boolean
  /** Permission required to see/use the shortcut; omit for shortcuts available to everyone. */
  permission?: string
}

export function useKeyboardShortcuts(shortcuts: Shortcut[]) {
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in inputs
      const target = event.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
        // Allow Escape even in inputs
        if (event.key !== 'Escape') return
      }

      for (const shortcut of shortcuts) {
        const keyMatch = event.key.toLowerCase() === shortcut.key.toLowerCase()

        const modifiersMatch = (shortcut.modifiers ?? []).every((mod) => {
          switch (mod) {
            case 'ctrl':
              return event.ctrlKey
            case 'alt':
              return event.altKey
            case 'shift':
              return event.shiftKey
            case 'meta':
              return event.metaKey
            default:
              return false
          }
        })

        if (keyMatch && modifiersMatch) {
          if (shortcut.preventDefault !== false) {
            event.preventDefault()
          }
          shortcut.action()
          break
        }
      }
    },
    [shortcuts]
  )

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])
}

/**
 * Single source of truth for global shortcuts. Both the keydown handlers and
 * the shortcuts help modal use this list, filtered by the current user's
 * permissions so RBAC-gated destinations (e.g. user administration) are only
 * offered to users who can actually open them.
 */
function useAppShortcuts(): Shortcut[] {
  const navigate = useNavigate()
  const hasPermission = useAuthStore((s) => s.hasPermission)

  return useMemo(() => {
    const shortcuts: Shortcut[] = [
      {
        key: '?',
        description: 'Show keyboard shortcuts help',
        action: () => {
          // Dispatch custom event to show shortcuts modal
          window.dispatchEvent(new CustomEvent('show-shortcuts'))
        },
      },
      {
        key: 'Escape',
        description: 'Close modal/drawer',
        action: () => {
          // Close any open modals/drawers
          const closeButtons = document.querySelectorAll('[data-modal-close], [data-drawer-close]')
          closeButtons.forEach((btn) => (btn as HTMLButtonElement).click())
        },
      },
      {
        key: 'd',
        modifiers: ['ctrl'],
        description: 'Go to Dashboard',
        action: () => navigate({ to: '/' }),
      },
      {
        key: 's',
        modifiers: ['ctrl'],
        description: 'Go to Servers',
        action: () => navigate({ to: '/servers' }),
      },
      {
        key: 'e',
        modifiers: ['ctrl'],
        description: 'Go to Environments',
        action: () => navigate({ to: '/environments' }),
      },
      {
        key: 'u',
        modifiers: ['ctrl'],
        description: 'Go to Users',
        action: () => navigate({ to: '/users' }),
        permission: PERMISSIONS.USERS_READ,
      },
      {
        key: 'n',
        modifiers: ['alt'],
        description: 'New Server',
        action: () => {
          if (window.location.pathname === '/servers') {
            window.dispatchEvent(new CustomEvent('new-server'))
          } else {
            sessionStorage.setItem('nukelab-new-server', 'true')
            navigate({ to: '/servers' })
          }
        },
      },
    ]

    return shortcuts.filter((s) => !s.permission || hasPermission(s.permission))
  }, [navigate, hasPermission])
}

// Global shortcuts for the app
export function useGlobalShortcuts() {
  useKeyboardShortcuts(useAppShortcuts())
}

// Hook to get all shortcuts the current user may use (for the help modal)
export function useShortcutsList(): Shortcut[] {
  return useAppShortcuts()
}
