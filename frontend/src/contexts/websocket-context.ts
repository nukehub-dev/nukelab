// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createContext } from 'react'
import type { WebSocketMessage } from '../hooks/use-websocket'

export interface WebSocketContextValue {
  isConnected: boolean
  isConnecting: boolean
  error: string | null
  subscribe: (scope: string, targetId?: string) => void
  unsubscribe: (scope: string, targetId?: string) => void
  onMessage: (handler: (message: WebSocketMessage) => void) => () => void
  send: (data: unknown) => boolean
}

export const WebSocketContext = createContext<WebSocketContextValue | null>(null)
