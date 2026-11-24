// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute } from '@tanstack/react-router'
import { AdminQueuePage } from '../components/admin/queue-page'

export const Route = createFileRoute('/admin/queue')({
  component: AdminQueuePage,
})
