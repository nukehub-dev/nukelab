// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useCallback, useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSharedWebSocket } from '../../hooks/use-shared-websocket'
import { useAuthStore } from '../../stores/auth-store'
import { useToast } from '../../stores/toast-store'
import { api } from '../../lib/api'
import { parseUtcDate } from '../../lib/utils'
import type { Notification, NotificationListResponse } from '../../hooks/use-notifications'
import type { Server } from '../../types/api'

const STORAGE_KEY = 'nukelab-last-notification-toast'

function getLastToastTime(): string {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored) return stored
  // Start from epoch on first visit. Server and client clocks can drift, and
  // Redis pub/sub only delivers messages published after subscription, so this
  // avoids missing new notifications because the client clock is ahead.
  const epoch = new Date(0).toISOString()
  localStorage.setItem(STORAGE_KEY, epoch)
  return epoch
}

function setLastToastTime(time: string) {
  localStorage.setItem(STORAGE_KEY, time)
}

const CLOCK_SKEW_TOLERANCE_MS = 5_000
const POLL_INTERVAL_MS = 30_000

/**
 * Listens for real-time notifications via WebSocket and shows toasts.
 * Falls back to HTTP polling so notifications are still delivered when the
 * WebSocket is disconnected, suspended by the OS, or misses an event.
 * Uses localStorage timestamp to avoid replaying old notifications across tabs.
 */
export function useNotificationToasts() {
  const queryClient = useQueryClient()
  const user = useAuthStore((state) => state.user)
  const lastToastTimeRef = useRef<string>(getLastToastTime())
  const lastCacheRefreshRef = useRef<string>(getLastToastTime())
  const mountedAtRef = useRef<string>(new Date().toISOString())
  const { info, success, warning, error } = useToast()

  const { isConnected, subscribe, unsubscribe, onMessage } = useSharedWebSocket()

  // Refresh notification caches for every real notification. This is deduped
  // by its own server-timestamp watermark and is intentionally separate from
  // the toast dedupe below: a suppressed toast (clock skew, another tab,
  // mount guard) must never suppress the badge/list update.
  const refreshCaches = useCallback(
    (notification: Notification) => {
      if (!notification?.created_at) return

      const cutoff = parseUtcDate(lastCacheRefreshRef.current).getTime() - CLOCK_SKEW_TOLERANCE_MS
      if (parseUtcDate(notification.created_at).getTime() <= cutoff) return
      lastCacheRefreshRef.current = notification.created_at

      // Invalidate notification queries so NotificationCenter updates instantly
      queryClient.invalidateQueries({ queryKey: ['notifications'] })

      // If the notification is credit-related and points to a specific request,
      // refresh the request thread/list caches so the conversation updates live.
      const actionUrl = notification.action_url
      if (
        notification.type === 'credit' &&
        actionUrl &&
        (actionUrl.startsWith('/settings/credits') || actionUrl.startsWith('/admin/credits'))
      ) {
        const requestId = new URLSearchParams(actionUrl.split('?')[1]).get('request')
        if (requestId) {
          queryClient.invalidateQueries({ queryKey: ['credit-requests', 'messages', requestId] })
        }
        queryClient.invalidateQueries({ queryKey: ['credit-requests'] })
      }
    },
    [queryClient]
  )

  const showToast = useCallback(
    (notification: Notification, source: 'websocket' | 'poll' = 'websocket') => {
      if (!notification?.created_at) return

      // Deduplicate against both the last toasted notification and the time this
      // component mounted. The mount guard prevents polling from flooding the
      // user with old unread notifications when the app first loads.
      const cutoff = new Date(
        Math.max(
          parseUtcDate(lastToastTimeRef.current).getTime(),
          parseUtcDate(mountedAtRef.current).getTime()
        ) - CLOCK_SKEW_TOLERANCE_MS
      ).toISOString()

      if (parseUtcDate(notification.created_at).getTime() <= parseUtcDate(cutoff).getTime()) {
        return
      }

      // Show toast based on severity
      const toastFn =
        notification.severity === 'success'
          ? success
          : notification.severity === 'warning'
            ? warning
            : notification.severity === 'error'
              ? error
              : info

      if (import.meta.env.DEV) {
        console.log(`[notification-toast] ${source}`, notification)
      }

      toastFn(notification.title, notification.message)

      // Update last toast time
      lastToastTimeRef.current = notification.created_at
      setLastToastTime(notification.created_at)
    },
    [info, success, warning, error]
  )

  // Subscribe to user-specific room when connected
  useEffect(() => {
    if (!isConnected || !user) return
    subscribe('user', user.id)
    return () => {
      unsubscribe('user', user.id)
    }
  }, [isConnected, user, subscribe, unsubscribe])

  // Handle incoming notification events
  useEffect(() => {
    const cleanup = onMessage((message) => {
      if (message.event === 'server:status_changed') {
        const data = message.data as {
          server_id: string
          status: Server['status']
          stop_reason?: string
        }
        if (!data?.server_id) return

        // Immediately update the servers cache so UI reflects the new status
        // without waiting for the slow list_servers refetch
        queryClient.setQueryData(['servers'], (old: Server[] | undefined) => {
          if (!old) return old
          return old.map((s) =>
            s.id === data.server_id
              ? { ...s, status: data.status, stop_reason: data.stop_reason }
              : s
          )
        })
        return
      }

      if (message.event === 'rate_limited') {
        warning('Rate Limited', message.message || 'Too many messages. Please slow down.')
        return
      }

      if (message.event !== 'notification:new') return

      const notification = message.data as Notification
      refreshCaches(notification)
      showToast(notification, 'websocket')
    })

    return cleanup
  }, [onMessage, queryClient, refreshCaches, showToast, warning])

  // Polling fallback: keeps notification delivery robust when the WebSocket is
  // down, the tab is backgrounded, or a single event is dropped.
  useEffect(() => {
    if (!user) return

    let cancelled = false
    const poll = async () => {
      try {
        const response = await api.get<NotificationListResponse>(
          '/notifications/?unread_only=true&page=1&page_size=10'
        )
        if (cancelled) return
        response.notifications.forEach((notification) => {
          refreshCaches(notification)
          showToast(notification, 'poll')
        })
      } catch (e) {
        // Polling is best-effort; avoid spamming the console on transient errors.
        if (import.meta.env.DEV) {
          console.warn('[notification-toast] poll failed', e)
        }
      }
    }

    // Poll immediately on mount to catch any notifications that arrived while
    // the WebSocket was reconnecting, then on the interval.
    void poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [user, refreshCaches, showToast])
}
