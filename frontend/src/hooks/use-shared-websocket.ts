// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useContext } from 'react'
import { WebSocketContext, type WebSocketContextValue } from '../contexts/websocket-context'

export type { WebSocketContextValue }

export function useSharedWebSocket(): WebSocketContextValue {
  const context = useContext(WebSocketContext)
  if (!context) {
    throw new Error('useSharedWebSocket must be used within a WebSocketProvider')
  }
  return context
}
