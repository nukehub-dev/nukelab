// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { create } from 'zustand'

/** Preference value meaning "follow the browser's timezone". */
export const AUTO_TIMEZONE = 'auto'

interface TimezoneState {
  /** Stored preference: 'auto' or an IANA zone id. */
  preference: string
  /** IANA zone the shared formatters actually apply. */
  effectiveZone: string
  setPreference: (tz: string) => void
}

/** The browser's own IANA zone, falling back to UTC on very old engines. */
export function getBrowserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

function isValidTimezone(tz: string): boolean {
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: tz })
    return true
  } catch {
    return false
  }
}

function resolveZone(preference: string): string {
  if (preference === AUTO_TIMEZONE) return getBrowserTimezone()
  return isValidTimezone(preference) ? preference : getBrowserTimezone()
}

/**
 * Non-persisted mirror of the backend `timezone` preference — the backend is
 * the source of truth, and `useTimezoneSync` keeps this store in line with
 * it. Kept self-contained (no imports from lib/) to avoid import cycles.
 */
export const useTimezoneStore = create<TimezoneState>()((set) => ({
  preference: AUTO_TIMEZONE,
  effectiveZone: getBrowserTimezone(),
  setPreference: (tz) => {
    const preference = tz !== AUTO_TIMEZONE && isValidTimezone(tz) ? tz : AUTO_TIMEZONE
    set({ preference, effectiveZone: resolveZone(preference) })
  },
}))
