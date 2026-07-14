// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useState } from 'react'

// Matches Tailwind's lg breakpoint.
const DESKTOP_QUERY = '(min-width: 1024px)'

/**
 * Tracks whether the viewport is at least lg-wide. Use it to skip expensive
 * visual effects (animated blur layers, parallax) on mobile, where they
 * cause scroll jank and battery drain.
 */
export function useIsDesktopViewport() {
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(DESKTOP_QUERY).matches
  )
  useEffect(() => {
    const mq = window.matchMedia(DESKTOP_QUERY)
    const onChange = () => setIsDesktop(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return isDesktop
}
