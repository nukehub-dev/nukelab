// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Navigate } from '@tanstack/react-router'

export const Route = createFileRoute('/users')({
  component: () => <Navigate to="/admin/users" replace />,
})
