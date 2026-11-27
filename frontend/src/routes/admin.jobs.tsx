// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute } from '@tanstack/react-router'
import { AdminJobsPage } from '../components/admin/jobs-page'

export const Route = createFileRoute('/admin/jobs')({
  component: AdminJobsPage,
})
