// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createRootRoute } from '@tanstack/react-router'
import { AppShell } from '../components/layout/app-shell'
import { WebSocketProvider } from '../contexts/websocket-provider'

export const Route = createRootRoute({
  component: () => (
    <WebSocketProvider>
      <AppShell />
    </WebSocketProvider>
  ),
})
