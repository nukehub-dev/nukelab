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
  Rocket,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  ListChecks,
} from 'lucide-react'
import { FloatingHeader } from '../components/layout/floating-header'
import { StatCard } from '../components/data/stat-card'

import { useDashboard } from '../hooks/use-dashboard'
import { useServers } from '../hooks/use-servers'
import { usePlans } from '../hooks/use-plans'
import { useEnvironments } from '../hooks/use-environments'
import { useAuthStore, PERMISSIONS } from '../stores/auth-store'
import { SkeletonCard } from '../components/feedback/skeleton'
import { MetricsDashboard } from '../components/charts/metrics-dashboard'
import { UserServerMetrics } from '../components/charts/user-server-metrics'
import { Button } from '../components/ui/button'
import { buttonVariants } from '../components/ui/button-variants'
import {
  describeDeployCost,
  resolveDeployDefaults,
  summarizeDeployEnvironment,
  summarizeDeployPlan,
} from '../lib/deploy-defaults'
import { cn, formatDate } from '../lib/utils'

export const Route = createFileRoute('/')({
  component: DashboardPage,
})

function DashboardPage() {
  const { data: dashboard, isLoading, isError, error } = useDashboard()
  const { data: servers = [], isLoading: serversLoading, isError: serversError } = useServers()
  const {
    data: plansData,
    isPending: plansLoading,
    isError: plansError,
    refetch: refetchPlans,
  } = usePlans({ is_active: true, limit: 100 })
  const {
    data: environmentsData,
    isPending: environmentsLoading,
    isError: environmentsError,
    refetch: refetchEnvironments,
  } = useEnvironments({
    is_active: true,
    limit: 100,
  })
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

  const plans = plansData?.data ?? []
  const environments = environmentsData?.data ?? []
  // Admins see the whole catalog, so guidance still resolves the baseline
  // user-visible entries. Normal users only receive plans/environments the API
  // already filtered for their access, including direct/workspace grants.
  const deployDefaults = resolveDeployDefaults({
    plans,
    environments,
    savedPlanId:
      typeof currentUser?.preferences?.default_plan === 'string'
        ? currentUser.preferences.default_plan
        : undefined,
    savedEnvironmentId:
      typeof currentUser?.preferences?.default_environment === 'string'
        ? currentUser.preferences.default_environment
        : undefined,
    canAccessAdmin,
  })
  const hasAvailablePlan = deployDefaults.plans.length > 0
  const hasPublicEnvironment = deployDefaults.environments.length > 0
  const catalogLoading = plansLoading || environmentsLoading
  const catalogError = !catalogLoading && (plansError || environmentsError)
  const catalogReady = !catalogLoading && !catalogError && hasAvailablePlan && hasPublicEnvironment

  const hasNoServers = Boolean(userId) && !serversLoading && !serversError && myServers.length === 0
  const showFirstRun = hasNoServers && catalogReady
  const showCatalogError = hasNoServers && catalogError
  const showSetupIncomplete = hasNoServers && !catalogLoading && !catalogError && !catalogReady
  const missingSetup = [
    !hasPublicEnvironment ? 'publish a public deployment environment' : null,
    !hasAvailablePlan ? 'make an active plan available to users' : null,
  ].filter((item): item is string => item !== null)
  const userSetupMessage =
    missingSetup.length === 2
      ? 'A NukeLab administrator still needs to publish a public deployment environment and make an active plan available to users.'
      : missingSetup.length === 1
        ? `A NukeLab administrator still needs to ${missingSetup[0]} before servers can be deployed.`
        : 'NukeLab is ready to deploy.'

  const savedDefaultNotice =
    deployDefaults.savedPlanStale || deployDefaults.savedEnvironmentStale
      ? `Your saved default ${
          deployDefaults.savedPlanStale ? 'plan' : ''
        }${deployDefaults.savedPlanStale && deployDefaults.savedEnvironmentStale ? ' and ' : ''}${
          deployDefaults.savedEnvironmentStale ? 'environment' : ''
        } is no longer available. ${
          deployDefaults.plan || deployDefaults.environment
            ? 'The current recommendation is shown below.'
            : 'Choose a current option when you launch.'
        }`
      : null
  const starterPlanSummary = summarizeDeployPlan(deployDefaults.plan, deployDefaults.plans.length)
  const starterEnvironmentSummary = summarizeDeployEnvironment(
    deployDefaults.environment,
    deployDefaults.environments.length
  )
  const starterCostSummary = describeDeployCost(deployDefaults.plan)
  const starterStorageSummary = 'Private volume, created or reused when you launch'

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

        {/* Setup incomplete: guide admins to the checklist and tell users why deploy is unavailable */}
        {showSetupIncomplete && (
          <motion.section
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
            aria-labelledby="setup-incomplete-heading"
            className="bubble relative overflow-hidden p-6 lg:p-8"
          >
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 bg-gradient-to-br from-amber-500/10 via-transparent to-transparent"
            />
            <div className="relative flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
              <div className="max-w-xl space-y-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/20">
                    <ListChecks className="h-5 w-5" aria-hidden="true" />
                  </div>
                  <span className="text-xs font-semibold uppercase tracking-widest text-amber-400">
                    {canAccessAdmin ? 'Setup required' : 'Deployment unavailable'}
                  </span>
                </div>
                <div className="space-y-2">
                  <h2 id="setup-incomplete-heading" className="text-xl font-semibold lg:text-2xl">
                    {canAccessAdmin ? 'Finish setting up NukeLab' : 'NukeLab setup is not complete'}
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    {canAccessAdmin
                      ? 'Users cannot deploy until an active public environment and at least one plan available to users are in place.'
                      : userSetupMessage}
                  </p>
                </div>
                {canAccessAdmin ? (
                  <div className="flex flex-wrap items-center gap-3">
                    <Link
                      to="/admin/setup"
                      className={cn(
                        buttonVariants({ size: 'lg' }),
                        'group shadow-lg shadow-primary/20'
                      )}
                    >
                      <ListChecks className="h-4 w-4" aria-hidden="true" />
                      Open setup checklist
                      <ArrowRight
                        className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                        aria-hidden="true"
                      />
                    </Link>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center gap-3">
                    <Link
                      to="/support"
                      className={cn(buttonVariants({ variant: 'outline' }), 'group')}
                    >
                      Contact support
                      <ArrowRight
                        className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                        aria-hidden="true"
                      />
                    </Link>
                  </div>
                )}
              </div>
              {canAccessAdmin && (
                <div className="grid w-full gap-2 sm:grid-cols-2 lg:max-w-md">
                  <SetupStatusRow label="Active public environment" ready={hasPublicEnvironment} />
                  <SetupStatusRow label="Active plan for users" ready={hasAvailablePlan} />
                </div>
              )}
            </div>
          </motion.section>
        )}

        {/* Catalog query failure must not masquerade as a missing catalog. */}
        {showCatalogError && (
          <motion.section
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
            aria-labelledby="catalog-error-heading"
            className="bubble relative overflow-hidden p-6 lg:p-8"
          >
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 bg-gradient-to-br from-destructive/10 via-transparent to-transparent"
            />
            <div className="relative max-w-xl space-y-4">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-destructive/10 text-destructive ring-1 ring-destructive/20">
                  <AlertTriangle className="h-5 w-5" aria-hidden="true" />
                </div>
                <span className="text-xs font-semibold uppercase tracking-widest text-destructive">
                  Catalog unavailable
                </span>
              </div>
              <div className="space-y-2">
                <h2 id="catalog-error-heading" className="text-xl font-semibold lg:text-2xl">
                  Deployment catalog could not be loaded
                </h2>
                <p className="text-sm text-muted-foreground">
                  Plans or environments are unavailable right now, so setup cannot be confirmed. No
                  deployment action is available until the catalog is reachable.
                </p>
              </div>
              <Button
                variant="outline"
                onClick={() => {
                  void refetchPlans()
                  void refetchEnvironments()
                }}
              >
                Retry catalog
              </Button>
            </div>
          </motion.section>
        )}

        {/* First-run onboarding */}
        {showFirstRun && (
          <motion.section
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
            aria-labelledby="first-run-heading"
            className="bubble relative overflow-hidden p-6 lg:p-8"
          >
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary/10 via-transparent to-transparent"
            />
            <div className="relative flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
              <div className="max-w-xl space-y-4">
                <div className="flex items-center gap-3">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/20">
                    <Rocket className="h-5 w-5" />
                  </div>
                  <span className="text-xs font-semibold uppercase tracking-widest text-primary">
                    Get started
                  </span>
                </div>
                <div className="space-y-2">
                  <h2 id="first-run-heading" className="text-xl font-semibold lg:text-2xl">
                    Create your first simulation server
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    Review the starting setup below and change anything you need before launching.
                    Capacity is confirmed when you submit.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Link
                    to="/servers"
                    search={{ deploy: true }}
                    className={cn(
                      buttonVariants({ size: 'lg' }),
                      'group shadow-lg shadow-primary/20'
                    )}
                  >
                    <Rocket className="h-4 w-4" aria-hidden="true" />
                    Review your first server
                    <ArrowRight
                      className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                      aria-hidden="true"
                    />
                  </Link>
                  <Link
                    to="/plans"
                    className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
                  >
                    Browse plans
                  </Link>
                </div>
              </div>
              <div className="w-full space-y-2 lg:max-w-md">
                <dl className="grid gap-2 sm:grid-cols-2">
                  <StarterFact label="Plan">{starterPlanSummary}</StarterFact>
                  <StarterFact label="Environment">{starterEnvironmentSummary}</StarterFact>
                  <StarterFact label="Storage">{starterStorageSummary}</StarterFact>
                  <StarterFact label="Cost">{starterCostSummary}</StarterFact>
                </dl>
                {savedDefaultNotice && (
                  <p role="status" className="text-xs text-amber-400">
                    {savedDefaultNotice}
                  </p>
                )}
                <p className="text-xs text-muted-foreground">
                  You can change the preselected plan, environment and storage in the deploy dialog.
                </p>
              </div>
            </div>
          </motion.section>
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
              ].map((action) => {
                const content = (
                  <>
                    <div className={`p-3 rounded-lg ${action.color}`}>
                      <action.icon className="w-5 h-5" />
                    </div>
                    <span className="text-sm font-medium">{action.label}</span>
                  </>
                )
                const className =
                  'flex flex-col items-center gap-3 p-4 rounded-xl border border-border/50 hover:border-primary/50 hover:bg-primary/5 transition-all duration-100 group'

                return action.label === 'Deploy Server' ? (
                  <Link
                    key={action.label}
                    to="/servers"
                    search={{ deploy: true }}
                    className={className}
                  >
                    {content}
                  </Link>
                ) : (
                  <Link key={action.label} to={action.href} className={className}>
                    {content}
                  </Link>
                )
              })}
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

function StarterFact({ label, children }: { label: string; children: string }) {
  return (
    <div className="rounded-xl border border-border/50 bg-background/40 p-3">
      <dt className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 text-xs font-medium break-words">{children}</dd>
    </div>
  )
}

function SetupStatusRow({ label, ready }: { label: string; ready: boolean }) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-border/50 bg-background/40 p-3">
      {ready ? (
        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
      ) : (
        <AlertCircle className="h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
      )}
      <div className="min-w-0">
        <p className="text-xs font-medium">{label}</p>
        <p className={cn('text-xs', ready ? 'text-emerald-400' : 'text-amber-400')}>
          {ready ? 'Ready' : 'Missing'}
        </p>
      </div>
    </div>
  )
}
