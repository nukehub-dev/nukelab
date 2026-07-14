// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect } from 'react'
import { useAuthStore } from '../stores/auth-store'
import { AUTO_TIMEZONE, useTimezoneStore } from '../stores/timezone-store'

/**
 * Mirror the backend `timezone` preference into the timezone store. The raw
 * user preferences distinguish "unset" (→ automatic/browser) from an explicit
 * zone, so this reads the user mirrored by `useCurrentUser` rather than the
 * merged GET /preferences/ payload.
 */
export function useTimezoneSync() {
  const timezone = useAuthStore((s) => s.user?.preferences?.timezone)
  const setPreference = useTimezoneStore((s) => s.setPreference)

  useEffect(() => {
    setPreference(typeof timezone === 'string' ? timezone : AUTO_TIMEZONE)
  }, [timezone, setPreference])
}
