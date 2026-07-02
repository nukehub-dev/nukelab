// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { type ReactNode } from 'react'
import { useWebSocket } from '../hooks/use-websocket'
import { useAuthStore } from '../stores/auth-store'
import { isAuthenticated } from '../hooks/use-auth'
import { WebSocketContext } from './websocket-context'

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const user = useAuthStore((state) => state.user)
  const canConnect = !!(user && isAuthenticated())
  const ws = useWebSocket({ autoConnect: canConnect })

  return <WebSocketContext.Provider value={ws}>{children}</WebSocketContext.Provider>
}
