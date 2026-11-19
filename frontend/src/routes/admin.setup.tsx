// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  CheckCircle2,
  CreditCard,
  Info,
  ListChecks,
  Rocket,
  ShieldCheck,
  UserPlus,
  Users,
} from 'lucide-react'
import { ResourcePageLayout } from '../components/layout/resource-page-layout'
import { StatusBadge } from '../components/data/status-badge'
import { Button } from '../components/ui/button'
import { buttonVariants } from '../components/ui/button-variants'
import { Tooltip } from '../components/ui/tooltip'
import { useEnvironments } from '../hooks/use-environments'
import { usePageGuard } from '../hooks/use-page-guard'
import { usePlanActions, usePlans } from '../hooks/use-plans'
import { PERMISSIONS } from '../stores/auth-store'
import { cn, formatPlanResource } from '../lib/utils'
import type { Environment, Plan } from '../types/api'

export const Route = createFileRoute('/admin/setup')({
  component: AdminSetupPage,
})

function isPlanAvailableToUsers(plan: Plan): boolean {
  return plan.is_active && (plan.is_public || (plan.visible_to_roles || []).includes('user'))
}

function PlanVisibilityBadge({ plan }: { plan: Plan }) {
  const roles = plan.visible_to_roles || []

  if (plan.is_public) {
    return (
      <span className="inline-flex items-center rounded-full border border-sky-500/20 bg-sky-500/10 px-2 py-0.5 text-xs font-medium text-sky-400">
        Public
      </span>
    )
  }

  if (roles.includes('user')) {
    return (
      <span className="inline-flex items-center rounded-full border border-violet-500/20 bg-violet-500/10 px-2 py-0.5 text-xs font-medium text-violet-400">
        Includes user role
      </span>
    )
  }

  return (
    <span className="inline-flex items-center rounded-full border border-border/50 bg-muted/50 px-2 py-0.5 text-xs font-medium text-muted-foreground">
      {roles.length > 0 ? `Roles: ${roles.join(', ')}` : 'Private'}
    </span>
  )
}

function SetupStatusRow({ label, ready }: { label: string; ready: boolean }) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-border/50 bg-background/40 p-3">
      {ready ? (
        <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
      ) : (
        <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
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

interface SetupStepProps {
  index: number
  title: string
  description: string
  icon: LucideIcon
  complete?: boolean
  children: ReactNode
}

function SetupStep({ index, title, description, icon: Icon, complete, children }: SetupStepProps) {
  return (
    <li
      className={cn(
        'bubble overflow-hidden',
        complete === true && 'border-emerald-500/20',
        complete === false && 'border-amber-500/20'
      )}
    >
      <div className="flex flex-col gap-4 p-5 sm:flex-row lg:p-6">
        <div
          className={cn(
            'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border text-sm font-semibold',
            complete === true
              ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
              : complete === false
                ? 'border-amber-500/20 bg-amber-500/10 text-amber-400'
                : 'border-primary/20 bg-primary/10 text-primary'
          )}
        >
          {complete === true ? (
            <CheckCircle2 className="h-5 w-5" aria-hidden="true" />
          ) : (
            <span>{index}</span>
          )}
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-2">
              <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <h3 className="text-base font-semibold">{title}</h3>
            </div>
            {complete !== undefined && (
              <StatusBadge
                status={complete ? 'healthy' : 'warning'}
                label={complete ? 'Complete' : 'Action needed'}
                size="sm"
              />
            )}
          </div>
          <p className="text-sm text-muted-foreground">{description}</p>
          {children}
        </div>
      </div>
    </li>
  )
}

function EnvironmentStep({ environments }: { environments: Environment[] }) {
  const activeEnvironments = environments.filter((env) => env.is_active)
  const activePublicEnvironments = activeEnvironments.filter((env) => env.is_public)

  return (
    <SetupStep
      index={1}
      title="Environment"
      description="Publish at least one environment that is both active and public."
      icon={Boxes}
      complete={activePublicEnvironments.length > 0}
    >
      {activePublicEnvironments.length === 0 && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4">
          <div className="flex gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
            <div className="space-y-2">
              <p className="text-sm font-medium text-amber-400">No active public environment</p>
              <p className="text-sm text-muted-foreground">
                Create a new environment or activate and publish an existing one.
              </p>
              <Link
                to="/admin/environments"
                className="inline-flex items-center gap-1 text-sm font-medium text-amber-400 hover:text-amber-300 hover:underline"
              >
                Create or publish an environment
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </div>
          </div>
        </div>
      )}

      {activeEnvironments.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Active environments
          </p>
          <div className="flex flex-wrap gap-2">
            {activeEnvironments.map((env) => (
              <span
                key={env.id}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs',
                  env.is_public
                    ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
                    : 'border-border/50 bg-muted/50 text-muted-foreground'
                )}
              >
                <Boxes className="h-3.5 w-3.5" aria-hidden="true" />
                {env.name}
                <span
                  className={cn(
                    'rounded-full px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide',
                    env.is_public
                      ? 'bg-emerald-500/15 text-emerald-300'
                      : 'bg-background/60 text-muted-foreground'
                  )}
                >
                  {env.is_public ? 'Public' : 'Private'}
                </span>
              </span>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No active environments exist yet.</p>
      )}

      <Link
        to="/admin/environments"
        className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'w-fit')}
      >
        <Boxes className="h-4 w-4" aria-hidden="true" />
        Manage environments
      </Link>
    </SetupStep>
  )
}

function PlansStep({ plans, inactiveCount }: { plans: Plan[]; inactiveCount: number }) {
  const { updatePlan } = usePlanActions()
  const activeUserVisiblePlans = plans.filter(isPlanAvailableToUsers)

  const makeAvailableToUsers = (plan: Plan) => {
    updatePlan.mutate({
      planId: plan.id,
      data: {
        visible_to_roles: Array.from(new Set([...(plan.visible_to_roles || []), 'user'])),
        is_active: true,
      },
    })
  }

  return (
    <SetupStep
      index={2}
      title="Plans"
      description="Users need at least one active plan that is public or shared with the user role."
      icon={CreditCard}
      complete={activeUserVisiblePlans.length > 0}
    >
      {activeUserVisiblePlans.length === 0 && (
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-4">
          <div className="flex gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
            <div className="space-y-1">
              <p className="text-sm font-medium text-amber-400">No plan available to users</p>
              <p className="text-sm text-muted-foreground">
                Private plans are only visible to administrators. Make one available below or create
                a new plan.
              </p>
            </div>
          </div>
        </div>
      )}

      {plans.length > 0 ? (
        <div className="divide-y divide-border/50 overflow-hidden rounded-xl border border-border/50">
          {plans.map((plan) => {
            const available = isPlanAvailableToUsers(plan)
            const isUpdating = updatePlan.isPending && updatePlan.variables?.planId === plan.id

            return (
              <div
                key={plan.id}
                className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{plan.name}</span>
                    <StatusBadge
                      status={plan.is_active ? 'running' : 'stopped'}
                      label={plan.is_active ? 'Active' : 'Inactive'}
                      size="sm"
                    />
                    <PlanVisibilityBadge plan={plan} />
                    {available && (
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400">
                        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                        Available
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {plan.cpu_limit} CPU · {formatPlanResource(plan.memory_limit)} RAM ·{' '}
                    {formatPlanResource(plan.disk_limit)} disk · {plan.cost_per_hour} nukes/hr
                    {plan.gpu_limit > 0 ? ` · ${plan.gpu_limit} GPU` : ''}
                  </p>
                </div>
                {!available && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => makeAvailableToUsers(plan)}
                    disabled={updatePlan.isPending}
                    loading={isUpdating}
                    className="shrink-0"
                  >
                    <UserPlus className="h-4 w-4" aria-hidden="true" />
                    Make available to users
                  </Button>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">
          No active plans exist yet. Create or activate one from the plans administration page.
        </p>
      )}
      {inactiveCount > 0 && (
        <p className="text-xs text-muted-foreground">
          {inactiveCount} inactive plan{inactiveCount === 1 ? '' : 's'} hidden. Use Manage plans to
          review or activate {inactiveCount === 1 ? 'it' : 'them'}.
        </p>
      )}

      <div className="flex items-start gap-2 rounded-lg border border-sky-500/20 bg-sky-500/5 p-3">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-sky-400" aria-hidden="true" />
        <p className="text-sm text-muted-foreground">
          <span className="font-medium text-foreground">
            At least one active plan available to users must remain.
          </span>{' '}
          Changes that would leave users without a deployable plan are blocked.
        </p>
      </div>

      <Link
        to="/admin/plans"
        className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'w-fit')}
      >
        <CreditCard className="h-4 w-4" aria-hidden="true" />
        Manage plans
      </Link>
    </SetupStep>
  )
}

function UsersStep() {
  return (
    <SetupStep
      index={3}
      title="Users"
      description="Invite teammates and assign roles. Users need the user role to see plans shared with that role."
      icon={Users}
    >
      <Link
        to="/admin/users"
        className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'w-fit')}
      >
        <Users className="h-4 w-4" aria-hidden="true" />
        Manage users
      </Link>
    </SetupStep>
  )
}

function TestLaunchStep({ ready, reason }: { ready: boolean; reason: string }) {
  return (
    <SetupStep
      index={4}
      title="Test launch"
      description="Open the normal deployment dialog to confirm a user can choose a plan and environment."
      icon={Rocket}
      complete={ready}
    >
      {ready ? (
        <Link
          to="/servers"
          search={{ deploy: true }}
          className={cn(buttonVariants({ size: 'sm' }), 'w-fit')}
        >
          <Rocket className="h-4 w-4" aria-hidden="true" />
          Launch a test server
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      ) : (
        <div className="space-y-2">
          <Tooltip content={reason}>
            <span className="inline-flex">
              <Button type="button" disabled>
                <Rocket className="h-4 w-4" aria-hidden="true" />
                Launch a test server
              </Button>
            </span>
          </Tooltip>
          <p className="text-xs text-muted-foreground">{reason}</p>
        </div>
      )}
    </SetupStep>
  )
}

function AdminSetupPage() {
  const allowed = usePageGuard({ permission: PERMISSIONS.ADMIN_ACCESS })
  const {
    data: plansData,
    isPending: plansLoading,
    isError: plansError,
    error: plansQueryError,
    refetch: refetchPlans,
  } = usePlans({ limit: 100 })
  const {
    data: environmentsData,
    isPending: environmentsLoading,
    isError: environmentsError,
    error: environmentsQueryError,
    refetch: refetchEnvironments,
  } = useEnvironments({ limit: 100 })

  if (!allowed) return null

  const plans = plansData?.data ?? []
  const activePlans = plans.filter((plan) => plan.is_active)
  const inactivePlanCount = plans.length - activePlans.length
  const environments = environmentsData?.data ?? []
  const activePublicEnvironments = environments.filter((env) => env.is_active && env.is_public)
  const activeUserVisiblePlans = activePlans.filter(isPlanAvailableToUsers)
  const environmentReady = activePublicEnvironments.length > 0
  const plansReady = activeUserVisiblePlans.length > 0
  const ready = environmentReady && plansReady

  const isLoading = plansLoading || environmentsLoading
  const loadFailed =
    !isLoading && ((plansError && !plansData) || (environmentsError && !environmentsData))
  const partialError = !loadFailed && (plansError || environmentsError)

  const blockedReason =
    !environmentReady && !plansReady
      ? 'Publish an active public environment and make a plan available to users first.'
      : !environmentReady
        ? 'Publish an active public environment first.'
        : !plansReady
          ? 'Make at least one active plan available to users first.'
          : 'All deployment prerequisites are ready.'

  const stats = [
    {
      title: 'Public environments',
      value: activePublicEnvironments.length,
      icon: Boxes,
      iconColor: 'text-blue-400',
      bgColor: 'bg-blue-500/10',
    },
    {
      title: 'Plans for users',
      value: activeUserVisiblePlans.length,
      icon: CreditCard,
      iconColor: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
    },
  ]

  const retry = () => {
    void refetchPlans()
    void refetchEnvironments()
  }

  return (
    <ResourcePageLayout
      title="Set up NukeLab"
      subtitle="Publish the catalog so users can deploy their first server"
      icon={Rocket}
      backTo="/admin"
      stats={isLoading ? undefined : stats}
    >
      {isLoading ? (
        <div
          role="status"
          aria-live="polite"
          className="bubble flex items-center gap-3 p-6 text-sm text-muted-foreground"
        >
          <span
            aria-hidden="true"
            className="h-4 w-4 animate-spin rounded-full border-2 border-primary/30 border-t-primary"
          />
          Checking environments and plans…
        </div>
      ) : loadFailed ? (
        <div role="alert" className="bubble space-y-4 p-6">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
            <div className="space-y-1">
              <p className="font-medium">Could not load setup information</p>
              <p className="text-sm text-muted-foreground">
                {plansQueryError?.message ||
                  environmentsQueryError?.message ||
                  'The environment and plan catalogs are unavailable right now.'}
              </p>
            </div>
          </div>
          <Button variant="outline" onClick={retry}>
            Retry
          </Button>
        </div>
      ) : (
        <div className="space-y-6">
          {partialError && (
            <div role="alert" className="bubble flex items-start gap-2 p-4">
              <AlertTriangle
                className="mt-0.5 h-4 w-4 shrink-0 text-amber-400"
                aria-hidden="true"
              />
              <div className="flex flex-1 flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted-foreground">
                  Some setup information could not be refreshed. The status below may be out of
                  date.
                </p>
                <Button variant="outline" size="sm" onClick={retry}>
                  Retry
                </Button>
              </div>
            </div>
          )}

          <section
            aria-labelledby="setup-summary-heading"
            className={cn(
              'bubble relative overflow-hidden p-6 lg:p-8',
              ready ? 'border-emerald-500/20' : 'border-amber-500/20'
            )}
          >
            <div
              aria-hidden="true"
              className={cn(
                'pointer-events-none absolute inset-0 bg-gradient-to-br via-transparent to-transparent',
                ready ? 'from-emerald-500/10' : 'from-amber-500/10'
              )}
            />
            <div className="relative space-y-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <div
                      className={cn(
                        'flex h-9 w-9 items-center justify-center rounded-xl ring-1',
                        ready
                          ? 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20'
                          : 'bg-amber-500/10 text-amber-400 ring-amber-500/20'
                      )}
                    >
                      <ListChecks className="h-4 w-4" aria-hidden="true" />
                    </div>
                    <span
                      className={cn(
                        'text-xs font-semibold uppercase tracking-widest',
                        ready ? 'text-emerald-400' : 'text-amber-400'
                      )}
                    >
                      {ready ? 'Ready' : 'Setup required'}
                    </span>
                  </div>
                  <h2 id="setup-summary-heading" className="text-xl font-semibold lg:text-2xl">
                    {ready ? 'NukeLab is ready for first launches' : 'Finish setting up NukeLab'}
                  </h2>
                  <p className="max-w-2xl text-sm text-muted-foreground">
                    {ready
                      ? 'An active public environment and a plan available to users are in place. You can revisit this checklist whenever the catalog changes.'
                      : 'Users cannot deploy until an active public environment and at least one plan available to users are in place.'}
                  </p>
                </div>
                <StatusBadge
                  status={ready ? 'healthy' : 'warning'}
                  label={ready ? 'Ready for first launches' : 'Action required'}
                />
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:max-w-xl">
                <SetupStatusRow label="Active public environment" ready={environmentReady} />
                <SetupStatusRow label="Active plan available to users" ready={plansReady} />
              </div>
            </div>
          </section>

          <ol className="space-y-4">
            <EnvironmentStep environments={environments} />
            <PlansStep plans={activePlans} inactiveCount={inactivePlanCount} />
            <UsersStep />
            <TestLaunchStep ready={ready} reason={blockedReason} />
          </ol>

          <div className="flex items-start gap-2 rounded-lg border border-border/50 bg-muted/30 p-3">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <p className="text-xs text-muted-foreground">
              This checklist stays available after setup so you can review catalog readiness
              whenever you publish, activate, or hide an environment or plan.
            </p>
          </div>
        </div>
      )}
    </ResourcePageLayout>
  )
}
