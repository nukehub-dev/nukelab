// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Link } from '@tanstack/react-router'
import { useMemo } from 'react'
import { motion } from 'framer-motion'
import {
  LayoutDashboard,
  Server,
  Boxes,
  Activity,
  Users,
  Zap,
  TrendingUp,
  HardDrive,
  Globe,
  FolderOpen,
  CreditCard,
  ArrowRight,
} from 'lucide-react'
import { FloatingHeader } from '../components/layout/floating-header'
import { StatCard } from '../components/data/stat-card'

import { useDashboard } from '../hooks/use-dashboard'
import { useServers } from '../hooks/use-servers'
import { useAuthStore, PERMISSIONS } from '../stores/auth-store'
import { SkeletonCard } from '../components/feedback/skeleton'
import { MetricsDashboard } from '../components/charts/metrics-dashboard'
import { UserServerMetrics } from '../components/charts/user-server-metrics'
import { formatDate } from '../lib/utils'

export const Route = createFileRoute('/')({
  component: DashboardPage,
})

function DashboardPage() {
  const { data: dashboard, isLoading, isError, error } = useDashboard()
  const { data: servers = [] } = useServers()
  const hasPermission = useAuthStore((state) => state.hasPermission)
  const canAccessAdmin = hasPermission(PERMISSIONS.ADMIN_ACCESS)
  const canViewSystemMetrics = hasPermission(PERMISSIONS.ADMIN_ACCESS)
  const currentUser = useAuthStore((state) => state.user)
  const userId = currentUser?.id

  // Filter servers by current user for "My Servers"
  const myServers = useMemo(
    () => (userId ? servers.filter((s) => s.user_id === userId) : servers),
    [servers, userId]
  )

  const myRunningServers = myServers.filter((s) => s.status === 'running')

  const platformStats = dashboard?.platform_stats

  return (
    <div className="min-h-screen">
      <FloatingHeader
        title="Dashboard"
        subtitle={
          canAccessAdmin ? 'System overview and monitoring' : 'Overview of your simulation servers'
        }
        icon={LayoutDashboard}
      />

      <div className="p-6 lg:p-10 space-y-8">
        {/* Ambient background */}
        <div className="fixed inset-0 overflow-hidden pointer-events-none -z-10">
          <div className="absolute top-20 right-20 w-[400px] h-[400px] rounded-full bg-primary/10 blur-[80px] blob-float" />
          <div
            className="absolute bottom-20 left-40 w-[300px] h-[300px] rounded-full bg-chart-2/10 blur-[80px] blob-float"
            style={{ animationDelay: '-5s' }}
          />
        </div>

        {/* Error State */}
        {isError && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bubble p-8 text-center space-y-4"
          >
            <p className="text-destructive font-medium">
              {error?.message || 'Failed to load dashboard data'}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
            >
              Retry
            </button>
          </motion.div>
        )}

        {/* Admin: Platform Overview */}
        {canAccessAdmin && platformStats && (
          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Globe className="w-4 h-4 text-primary" />
              <h2 className="text-base font-semibold">Platform Overview</h2>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                {
                  title: 'Total Users',
                  value: platformStats.total_users,
                  icon: Users,
                  iconColor: 'text-blue-400',
                  bgColor: 'bg-blue-500/10',
                },
                {
                  title: 'Active Servers',
                  value: platformStats.active_servers,
                  icon: Server,
                  iconColor: 'text-emerald-400',
                  bgColor: 'bg-emerald-500/10',
                },
                {
                  title: 'Total Servers',
                  value: platformStats.total_servers,
                  icon: Boxes,
                  iconColor: 'text-amber-400',
                  bgColor: 'bg-amber-500/10',
                },
                {
                  title: 'Total Nukes',
                  value: platformStats.total_nukes,
                  icon: Zap,
                  iconColor: 'text-violet-400',
                  bgColor: 'bg-violet-500/10',
                },
              ].map((stat) => (
                <StatCard key={stat.title} {...stat} variant="compact" />
              ))}
            </div>
          </section>
        )}

        {/* User Stats */}
        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-primary" />
            <h2 className="text-base font-semibold">
              {canAccessAdmin ? 'Your Resources' : 'Overview'}
            </h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {isLoading ? (
              Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={i} />)
            ) : dashboard ? (
              <>
                <StatCard
                  title="Active Servers"
                  value={dashboard.my_servers.running}
                  subtitle={`${dashboard.my_servers.stopped} stopped · ${dashboard.my_servers.total} total`}
                  icon={Server}
                  iconColor="text-emerald-400"
                  bgColor="bg-emerald-500/10"
                />
                <StatCard
                  title="Resource Usage"
                  value={`${myRunningServers.length}`}
                  subtitle={
                    myRunningServers.length > 0
                      ? `${myRunningServers.reduce((acc, s) => acc + (s.allocated_cpu || 0), 0)} CPU cores`
                      : 'No active servers'
                  }
                  icon={Boxes}
                  iconColor="text-blue-400"
                  bgColor="bg-blue-500/10"
                />
                <StatCard
                  title="Nuke Balance"
                  value={dashboard.my_nukes.balance}
                  subtitle={`${dashboard.my_nukes.daily_allowance} daily · ~${dashboard.my_nukes.estimated_hours_left}h remaining`}
                  icon={Zap}
                  iconColor="text-amber-400"
                  bgColor="bg-amber-500/10"
                />
              </>
            ) : null}
          </div>
        </section>

        {/* System Metrics (Admin Only) */}
        {canViewSystemMetrics && (
          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <HardDrive className="w-4 h-4 text-primary" />
              <h2 className="text-base font-semibold">System Metrics</h2>
            </div>
            <MetricsDashboard />
          </section>
        )}

        {/* My Running Servers */}
        {myRunningServers.length > 0 && (
          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Server className="w-4 h-4 text-primary" />
              <h2 className="text-base font-semibold">
                {canAccessAdmin ? 'Your Running Servers' : 'Running Servers'}
              </h2>
              <span className="text-xs text-muted-foreground ml-2">
                {myRunningServers.length} active
              </span>
            </div>
            <UserServerMetrics servers={myServers} />
          </section>
        )}

        {/* Quick Actions */}
        <section className="space-y-4">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-primary" />
            <h2 className="text-base font-semibold">Quick Actions</h2>
          </div>
          <div className="bubble p-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                {
                  label: 'Deploy Server',
                  icon: Server,
                  color: 'bg-primary/10 text-primary',
                  href: '/servers',
                },
                {
                  label: 'My Volumes',
                  icon: HardDrive,
                  color: 'bg-chart-2/10 text-chart-2',
                  href: '/volumes',
                },
                {
                  label: 'Workspaces',
                  icon: FolderOpen,
                  color: 'bg-chart-3/10 text-chart-3',
                  href: '/workspaces',
                },
                {
                  label: 'Browse Plans',
                  icon: CreditCard,
                  color: 'bg-chart-4/10 text-chart-4',
                  href: '/plans',
                },
              ].map((action) => (
                <Link
                  key={action.label}
                  to={action.href}
                  className="flex flex-col items-center gap-3 p-4 rounded-xl border border-border/50 hover:border-primary/50 hover:bg-primary/5 transition-all duration-100 group"
                >
                  <div className={`p-3 rounded-lg ${action.color}`}>
                    <action.icon className="w-5 h-5" />
                  </div>
                  <span className="text-sm font-medium">{action.label}</span>
                </Link>
              ))}
            </div>
          </div>
        </section>

        {/* Recent Activity */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-primary" />
              <h2 className="text-base font-semibold">Recent Activity</h2>
            </div>
            <Link
              to="/activity"
              className="inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors"
            >
              View all
              <ArrowRight className="w-3 h-3" />
            </Link>
          </div>
          <div className="bubble p-6">
            <div className="space-y-3">
              {isLoading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-4 p-3 rounded-lg">
                    <div className="w-2 h-2 rounded-full bg-muted" />
                    <div className="flex-1 space-y-1">
                      <div className="h-4 w-32 bg-muted rounded" />
                    </div>
                    <div className="h-4 w-16 bg-muted rounded" />
                  </div>
                ))
              ) : dashboard?.recent_activity.length === 0 ? (
                <p className="text-muted-foreground text-center py-8">No recent activity</p>
              ) : (
                dashboard?.recent_activity.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center gap-4 p-3 rounded-lg hover:bg-accent/50 transition-colors"
                  >
                    <div className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
                    {/* min-w-0 lets this flex child shrink below its content
                        width so long action/target strings truncate instead of
                        overflowing the card on narrow screens. */}
                    <div className="flex-1 min-w-0">
                      <p className="truncate">
                        <span className="font-medium">{item.action}</span>
                        {item.target_id && (
                          <>
                            <span className="text-muted-foreground mx-2">on</span>
                            <span className="font-mono text-sm">
                              {item.target_type}:{item.target_id}
                            </span>
                          </>
                        )}
                      </p>
                    </div>
                    <span className="shrink-0 text-sm text-muted-foreground">
                      {formatDate(item.timestamp)}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
