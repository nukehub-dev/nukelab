// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useRef } from 'react'
import { api } from '../lib/api'
import { ACTIVITY_HEARTBEAT_INTERVAL_MS, shouldPingActivity } from '../lib/activity-heartbeat'

// Deliberate input events only — passive mouse movement is not activity.
const INPUT_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const

async function pingServerActivity(serverId: string): Promise<void> {
  try {
    await api.post(`/servers/${serverId}/activity`, {})
  } catch {
    // Activity pings are best-effort; don't surface failures to the user.
  }
}

/**
 * Keep a running server's last_activity fresh, but only while the tab is
 * visible AND the user interacted with the page within the input window.
 * Previously a merely visible tab pinged forever, which prevented the
 * idle-shutdown task from ever stopping the server.
 */
export function useActivityHeartbeat(serverId: string | undefined, enabled: boolean): void {
  const lastInteractionRef = useRef<number | null>(null)

  useEffect(() => {
    if (!serverId || !enabled) return

    const recordInteraction = () => {
      lastInteractionRef.current = Date.now()
    }
    // Navigating to the page is itself a deliberate interaction.
    recordInteraction()

    const sendPing = () => {
      if (document.visibilityState !== 'visible') return
      if (shouldPingActivity(lastInteractionRef.current, Date.now())) {
        void pingServerActivity(serverId)
      }
    }

    sendPing()

    const interval = setInterval(sendPing, ACTIVITY_HEARTBEAT_INTERVAL_MS)
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') sendPing()
    }
    document.addEventListener('visibilitychange', handleVisibility)
    for (const event of INPUT_EVENTS) {
      window.addEventListener(event, recordInteraction, { passive: true })
    }

    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', handleVisibility)
      for (const event of INPUT_EVENTS) {
        window.removeEventListener(event, recordInteraction)
      }
    }
  }, [serverId, enabled])
}
