// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute } from '@tanstack/react-router'
import { motion } from 'framer-motion'
import { Construction, Clock, ArrowLeft } from 'lucide-react'
import { Link } from '@tanstack/react-router'
import { useHealth } from '../hooks/use-health'
import { formatDate } from '../lib/utils'

export const Route = createFileRoute('/maintenance')({
  component: MaintenancePage,
})

function MaintenancePage() {
  const { data: health } = useHealth()

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="max-w-md w-full text-center space-y-8"
      >
        <motion.div
          initial={{ scale: 0.8 }}
          animate={{ scale: 1 }}
          transition={{ delay: 0.2, type: 'spring' }}
          className="mx-auto w-24 h-24 rounded-2xl bg-amber-100 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/20 flex items-center justify-center"
        >
          <Construction className="w-12 h-12 text-amber-600 dark:text-amber-400" />
        </motion.div>

        <div className="space-y-3">
          <h1 className="text-3xl font-bold tracking-tight">Under Maintenance</h1>
          <p className="text-muted-foreground text-lg leading-relaxed">
            {health?.message || 'We are performing scheduled maintenance. Please check back soon.'}
          </p>
        </div>

        <div className="bubble p-6 space-y-4">
          <div className="flex items-center gap-3 text-sm">
            <Clock className="w-4 h-4 text-amber-600 dark:text-amber-400" />
            <span className="text-muted-foreground">Status:</span>
            <span className="font-medium text-amber-700 dark:text-amber-400">Maintenance Mode</span>
          </div>
          {health?.timestamp && (
            <div className="flex items-center gap-3 text-sm">
              <span className="text-muted-foreground">Last updated:</span>
              <span className="font-mono">{formatDate(health.timestamp)}</span>
            </div>
          )}
        </div>

        <Link
          to="/"
          className="inline-flex items-center gap-2 text-sm text-primary hover:text-primary/80 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </Link>
      </motion.div>
    </div>
  )
}
