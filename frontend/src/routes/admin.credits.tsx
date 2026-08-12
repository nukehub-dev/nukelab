// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, useSearch, useNavigate, Link } from '@tanstack/react-router'
import { motion } from 'framer-motion'
import { ArrowLeft, CreditCard, HandCoins, Settings, Users } from 'lucide-react'
import { usePageGuard } from '../hooks/use-page-guard'
import { PERMISSIONS } from '../stores/auth-store'
import { cn } from '../lib/utils'
import { RequestsTab } from '../components/admin/credits/requests-tab'
import { UsersTab } from '../components/admin/credits/users-tab'
import { SettingsTab } from '../components/admin/credits/settings-tab'

export const Route = createFileRoute('/admin/credits')({
  component: CreditsAdminPage,
})

type CreditsTab = 'requests' | 'users' | 'settings'

const TABS: { key: CreditsTab; label: string; icon: React.ElementType }[] = [
  { key: 'requests', label: 'Requests', icon: HandCoins },
  { key: 'users', label: 'Users', icon: Users },
  { key: 'settings', label: 'Settings', icon: Settings },
]

function CreditsAdminPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.CREDITS_READ_ALL })
  const navigate = useNavigate()
  const searchParams = useSearch({ from: '/admin/credits' }) as { user?: string; tab?: string }

  // The ?user=<id> deep-link always lands on the Users tab.
  const tabParam = searchParams.tab
  const activeTab: CreditsTab = searchParams.user
    ? 'users'
    : tabParam === 'users' || tabParam === 'settings' || tabParam === 'requests'
      ? tabParam
      : 'requests'

  const setTab = (tab: CreditsTab) => {
    // Replacing the whole search drops any stale ?user deep-link.
    navigate({ to: '/admin/credits', search: { tab } })
  }

  if (!allowed) return null

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3"
      >
        <Link
          to="/admin"
          className="p-2 rounded-lg hover:bg-accent transition-colors shrink-0 inline-flex"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="p-2 rounded-xl bg-primary/10">
          <CreditCard className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-bold">Credit Management</h1>
          <p className="text-sm text-muted-foreground">
            Manage user credits, view transaction history, and monitor low balances
          </p>
        </div>
      </motion.div>

      {/* Page Tabs */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05 }}
        className="flex items-center gap-2 flex-wrap"
      >
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setTab(tab.key)}
            data-testid={`credits-tab-${tab.key}`}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors border',
              activeTab === tab.key
                ? 'bg-primary/10 border-primary/30 text-primary'
                : 'bg-muted/50 border-border/50 text-muted-foreground hover:text-foreground hover:bg-muted'
            )}
          >
            <tab.icon className="w-3.5 h-3.5" />
            {tab.label}
          </button>
        ))}
      </motion.div>

      {/* Panels mount lazily so hidden tabs don't fire their queries */}
      {activeTab === 'requests' && <RequestsTab />}
      {activeTab === 'users' && <UsersTab focusUserId={searchParams.user} />}
      {activeTab === 'settings' && <SettingsTab />}
    </div>
  )
}
