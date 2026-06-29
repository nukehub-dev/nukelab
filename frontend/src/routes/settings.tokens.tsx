// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Link } from '@tanstack/react-router'
import { ArrowLeft, KeyRound } from 'lucide-react'
import { motion } from 'framer-motion'
import { TokensPage } from '../components/settings/tokens-page'

export const Route = createFileRoute('/settings/tokens')({
  component: TokensSettingsPage,
})

function TokensSettingsPage() {
  return (
    <div className="min-h-screen space-y-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3 px-6 lg:px-10 pt-6 lg:pt-8"
      >
        <Link
          to="/settings"
          className="p-2 rounded-lg hover:bg-accent transition-colors shrink-0 inline-flex"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="p-2 rounded-xl bg-primary/10">
          <KeyRound className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-bold">API Tokens</h1>
          <p className="text-sm text-muted-foreground">
            Manage personal access tokens for API and CLI access
          </p>
        </div>
      </motion.div>
      <div className="px-6 lg:px-10 pb-10">
        <TokensPage />
      </div>
    </div>
  )
}
