// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Outlet } from '@tanstack/react-router'

export const Route = createFileRoute('/servers')({
  component: ServersLayout,
})

function ServersLayout() {
  return <Outlet />
}
