// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useCallback } from 'react'

export function useScrollPosition() {
  const getScrollPosition = useCallback(() => {
    if (typeof window === 'undefined') return { x: 0, y: 0 }
    return {
      x: window.scrollX || window.pageXOffset,
      y: window.scrollY || window.pageYOffset,
    }
  }, [])

  return { getScrollPosition }
}
