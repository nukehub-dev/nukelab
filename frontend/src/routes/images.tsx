// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute } from '@tanstack/react-router'
import { Image, Layers, HardDrive, Tag, Construction } from 'lucide-react'
import { ResourcePageLayout } from '../components/layout/resource-page-layout'

export const Route = createFileRoute('/images')({
  component: ImagesPage,
})

function ImagesPage() {
  return (
    <ResourcePageLayout
      title="Images"
      subtitle="Manage container images"
      icon={Image}
      stats={[
        {
          title: 'Total Images',
          value: 0,
          icon: Image,
          iconColor: 'text-blue-400',
          bgColor: 'bg-blue-500/10',
        },
        {
          title: 'Layers',
          value: '0',
          icon: Layers,
          iconColor: 'text-amber-400',
          bgColor: 'bg-amber-500/10',
        },
        {
          title: 'Storage',
          value: '0 GB',
          icon: HardDrive,
          iconColor: 'text-rose-400',
          bgColor: 'bg-rose-500/10',
        },
        {
          title: 'Versions',
          value: 0,
          icon: Tag,
          iconColor: 'text-violet-400',
          bgColor: 'bg-violet-500/10',
        },
      ]}
    >
      <div className="bubble p-12 text-center">
        <Construction className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
        <h2 className="text-lg font-semibold mb-2">Coming Soon</h2>
        <p className="text-muted-foreground">
          Image registry management is under development. Check back soon for updates.
        </p>
      </div>
    </ResourcePageLayout>
  )
}
