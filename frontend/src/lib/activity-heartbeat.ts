// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

// How often the heartbeat checks whether an activity ping should be sent.
export const ACTIVITY_HEARTBEAT_INTERVAL_MS = 30_000

// Only interactions within this window count as activity. Kept slightly below
// the minimum idle_shutdown_timeout (5 minutes, enforced server-side in
// backend/app/api/preferences.py) so the final ping after the user's last
// interaction always lands before the server can be stopped — even at the
// minimum configured timeout.
export const ACTIVITY_INPUT_WINDOW_MS = 4 * 60_000

/**
 * Decide whether an activity ping should be sent. A ping is only meaningful
 * when the user actually interacted with the page recently; an open but
 * untouched tab must not keep a server alive forever.
 */
export function shouldPingActivity(
  lastInteractionAt: number | null,
  now: number,
  inputWindowMs: number = ACTIVITY_INPUT_WINDOW_MS
): boolean {
  if (lastInteractionAt === null) return false
  return now - lastInteractionAt <= inputWindowMs
}
