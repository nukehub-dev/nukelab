// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute } from '@tanstack/react-router'
import { JobDetailView } from '../components/jobs/job-detail-view'

export const Route = createFileRoute('/jobs/$jobId')({
  component: JobDetailRoute,
})

function JobDetailRoute() {
  const { jobId } = Route.useParams()
  return <JobDetailView jobId={jobId} />
}
