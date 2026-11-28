// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
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
import { useEnvironments } from '../hooks/use-environments'
import { usePageGuard } from '../hooks/use-page-guard'
import { usePlanActions, usePlans } from '../hooks/use-plans'
import { PERMISSIONS } from '../stores/auth-store'
import { cn, formatPlanResource } from '../lib/utils'
import { isServerPlan } from '../lib/plan-availability'
import type { Environment, Plan } from '../types/api'

export const Route = createFileRoute('/admin/setup')({
  component: AdminSetupPage,
})

const manageLinkClass = cn(
  buttonVariants({ variant: 'ghost', size: 'sm' }),
  'h-8 px-2 text-muted-foreground hover:text-foreground'
)

function isPlanAvailableToUsers(plan: Plan): boolean {
  return (
    plan.is_active &&
    plan.allow_servers !== false &&
    (plan.is_public || (plan.visible_to_roles || []).includes('user'))
  )
}

function planResourceSummary(plan: Plan): string {
  return [
    `${plan.cpu_limit} CPU`,
    `${formatPlanResource(plan.memory_limit)} RAM`,
    `${formatPlanResource(plan.disk_limit)} disk`,
    `${plan.cost_per_hour} nukes/hr`,
    plan.gpu_limit > 0 ? `${plan.gpu_limit} GPU` : null,
  ]
    .filter(Boolean)
    .join(' · ')
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

function SetupStatusLabel({ ready, children }: { ready: boolean; children: ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 text-xs',
        ready ? 'text-muted-foreground' : 'text-amber-400'
      )}
    >
      {ready ? (
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" aria-hidden="true" />
      ) : (
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      )}
      {children}
    </span>
  )
}

function InlineNotice({
  tone = 'warning',
  title,
  children,
  action,
}: {
  tone?: 'warning' | 'info'
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  const Icon = tone === 'warning' ? AlertTriangle : Info

  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-start sm:justify-between',
        tone === 'warning'
          ? 'border-amber-500/20 bg-amber-500/10'
          : 'border-sky-500/20 bg-sky-500/5'
      )}
    >
      <div className="flex items-start gap-2">
        <Icon
          className={cn(
            'mt-0.5 h-4 w-4 shrink-0',
            tone === 'warning' ? 'text-amber-400' : 'text-sky-400'
          )}
          aria-hidden="true"
        />
        <div className="space-y-0.5">
          <p
            className={cn(
              'text-sm font-medium',
              tone === 'warning' ? 'text-amber-400' : 'text-foreground'
            )}
          >
            {title}
          </p>
          {children && <div className="text-xs text-muted-foreground">{children}</div>}
        </div>
      </div>
      {action && <div className="shrink-0 sm:pl-4">{action}</div>}
    </div>
  )
}

interface SetupStepProps {
  id: string
  index: number
  title: string
  description: string
  icon: LucideIcon
  complete?: boolean
  action?: ReactNode
  children?: ReactNode
}

function SetupStep({
  id,
  index,
  title,
  description,
  icon: Icon,
  complete,
  action,
  children,
}: SetupStepProps) {
  return (
    <li
      id={id}
      className={cn(
        'bubble overflow-hidden scroll-mt-28',
        complete === false && 'ring-1 ring-amber-500/20'
      )}
    >
      <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:gap-4 lg:p-5">
        <div
          className={cn(
            'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border text-sm font-semibold',
            complete === true
              ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
              : complete === false
                ? 'border-amber-500/20 bg-amber-500/10 text-amber-400'
                : 'border-border/50 bg-muted/30 text-muted-foreground'
          )}
        >
          {complete === true ? (
            <CheckCircle2 className="h-5 w-5" aria-hidden="true" />
          ) : (
            <span>{index}</span>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="flex items-center gap-2 text-base font-semibold">
                  <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                  {title}
                </h3>
                {complete !== undefined && (
                  <StatusBadge
                    status={complete ? 'healthy' : 'warning'}
                    label={complete ? 'Ready' : 'Action needed'}
                    size="sm"
                  />
                )}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{description}</p>
            </div>
            {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
          </div>
          {children && <div className="mt-3 space-y-3">{children}</div>}
        </div>
      </div>
    </li>
  )
}

function EnvironmentStep({ index, environments }: { index: number; environments: Environment[] }) {
  const activeEnvironments = environments.filter((env) => env.is_active)
  const activePublicEnvironments = activeEnvironments.filter((env) => env.is_public)
  const privateCount = activeEnvironments.length - activePublicEnvironments.length
  const ready = activePublicEnvironments.length > 0
  const shown = activePublicEnvironments.slice(0, 4)
  const remaining = activePublicEnvironments.length - shown.length

  return (
    <SetupStep
      id="setup-environment"
      index={index}
      title="Public environment"
      description="Users need at least one environment that is active and public."
      icon={Boxes}
      complete={ready}
      action={
        <Link to="/admin/environments" className={manageLinkClass}>
          Manage environments
          <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      }
    >
      {ready ? (
        <div className="space-y-1.5">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            User-visible environments
          </p>
          <div className="flex flex-wrap gap-1.5">
            {shown.map((env) => (
              <span
                key={env.id}
                className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-300"
              >
                <Boxes className="h-3.5 w-3.5" aria-hidden="true" />
                {env.name}
              </span>
            ))}
            {remaining > 0 && (
              <span className="inline-flex items-center rounded-full border border-border/50 bg-muted/30 px-2.5 py-1 text-xs text-muted-foreground">
                +{remaining} more
              </span>
            )}
          </div>
          {privateCount > 0 && (
            <p className="text-xs text-muted-foreground">
              {privateCount} other active environment{privateCount === 1 ? ' is' : 's are'} private
              and not shown to users.
            </p>
          )}
        </div>
      ) : (
        <InlineNotice
          title={
            activeEnvironments.length === 0 ? 'No environments exist yet' : 'No public environment'
          }
        >
          {activeEnvironments.length === 0
            ? 'Create an environment in environment administration, then return here to publish it.'
            : 'Activate or publish an existing environment, or create a new one.'}
        </InlineNotice>
      )}
    </SetupStep>
  )
}

function PlansStep({
  index,
  plans,
  inactiveCount,
}: {
  index: number
  plans: Plan[]
  inactiveCount: number
}) {
  const { updatePlan } = usePlanActions()
  const availablePlans = plans.filter(isPlanAvailableToUsers)
  const needsAttention = plans.filter((plan) => !isPlanAvailableToUsers(plan))
  const ready = availablePlans.length > 0
  const shownPlans = availablePlans.slice(0, 6)
  const remainingPlans = availablePlans.length - shownPlans.length

  const makeAvailableToUsers = (plan: Plan) => {
    updatePlan.mutate({
      planId: plan.id,
      data: {
        visible_to_roles: Array.from(new Set([...(plan.visible_to_roles || []), 'user'])),
        is_active: true,
      },
    })
  }

  const noticeTitle =
    plans.length === 0
      ? inactiveCount > 0
        ? 'No active plans'
        : 'No plans exist yet'
      : 'No plan available to users'

  const noticeBody =
    plans.length === 0
      ? inactiveCount > 0
        ? 'Activate an existing plan in plan administration, or create a new one.'
        : 'Create a plan in plan administration, then return here to publish it.'
      : 'Publish one of the active plans below, or create a new one in plan administration.'

  return (
    <SetupStep
      id="setup-plans"
      index={index}
      title="Plan available to users"
      description="Users need at least one active plan that is public or shared with the user role."
      icon={CreditCard}
      complete={ready}
      action={
        <Link to="/admin/plans" className={manageLinkClass}>
          Manage plans
          <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      }
    >
      {!ready && <InlineNotice title={noticeTitle}>{noticeBody}</InlineNotice>}

      {availablePlans.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            User-visible plans
          </p>
          <div className="flex flex-wrap gap-1.5">
            {shownPlans.map((plan) => (
              <span
                key={plan.id}
                className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-300"
              >
                <CreditCard className="h-3.5 w-3.5" aria-hidden="true" />
                {plan.name}
              </span>
            ))}
            {remainingPlans > 0 && (
              <span className="inline-flex items-center rounded-full border border-border/50 bg-muted/30 px-2.5 py-1 text-xs text-muted-foreground">
                +{remainingPlans} more
              </span>
            )}
          </div>
        </div>
      )}

      {needsAttention.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Needs attention
          </p>
          <div className="space-y-2">
            {needsAttention.map((plan) => {
              const isUpdating = updatePlan.isPending && updatePlan.variables?.planId === plan.id

              return (
                <div
                  key={plan.id}
                  className="flex flex-col gap-2 rounded-lg border border-border/50 bg-background/30 p-3 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{plan.name}</span>
                      <PlanVisibilityBadge plan={plan} />
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {planResourceSummary(plan)}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => makeAvailableToUsers(plan)}
                    disabled={updatePlan.isPending}
                    loading={isUpdating}
                    className="w-full shrink-0 sm:w-auto"
                  >
                    <UserPlus className="h-4 w-4" aria-hidden="true" />
                    Make available to users
                  </Button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-sky-400" aria-hidden="true" />
          One active plan for users is always kept.
        </span>
        {inactiveCount > 0 && (
          <span>
            {inactiveCount} inactive plan{inactiveCount === 1 ? '' : 's'} hidden.
          </span>
        )}
      </div>
    </SetupStep>
  )
}

function UsersStep({ index }: { index: number }) {
  return (
    <SetupStep
      id="setup-users"
      index={index}
      title="Invite your team"
      description="Add teammates and assign roles. The user role can see plans shared with that role."
      icon={Users}
      action={
        <Link to="/admin/users" className={manageLinkClass}>
          Manage users
          <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
      }
    />
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
  const serverPlans = plans.filter(isServerPlan)
  const activePlans = serverPlans.filter((plan) => plan.is_active)
  const inactivePlanCount = serverPlans.length - activePlans.length
  const environments = environmentsData?.data ?? []
  const activePublicEnvironments = environments.filter((env) => env.is_active && env.is_public)
  const activeUserVisiblePlans = activePlans.filter(isPlanAvailableToUsers)
  const environmentReady = activePublicEnvironments.length > 0
  const plansReady = activeUserVisiblePlans.length > 0
  const ready = environmentReady && plansReady
  const completed = Number(environmentReady) + Number(plansReady)

  const isLoading = plansLoading || environmentsLoading
  const loadFailed =
    !isLoading && ((plansError && !plansData) || (environmentsError && !environmentsData))
  const partialError = !loadFailed && (plansError || environmentsError)

  const bannerDescription = ready
    ? 'An active public environment and a plan available to users are in place. Launch a test server or review the checklist below.'
    : !environmentReady && !plansReady
      ? 'Users cannot deploy until a public environment and a plan for users are published.'
      : !environmentReady
        ? 'Users cannot deploy until an active public environment is published.'
        : 'Users cannot deploy until an active plan is made available to users.'

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
        <div className="space-y-5">
          {partialError && (
            <InlineNotice
              title="Some setup information could not be refreshed"
              action={
                <Button variant="outline" size="sm" onClick={retry}>
                  Retry
                </Button>
              }
            >
              The status below may be out of date.
            </InlineNotice>
          )}

          <section
            aria-labelledby="setup-summary-heading"
            className={cn(
              'bubble relative overflow-hidden ring-1',
              ready ? 'ring-emerald-500/15' : 'ring-amber-500/20'
            )}
          >
            <div
              aria-hidden="true"
              className={cn(
                'pointer-events-none absolute inset-0 bg-gradient-to-br via-transparent to-transparent',
                ready ? 'from-emerald-500/10' : 'from-amber-500/10'
              )}
            />
            <div className="relative flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between lg:p-6">
              <div className="flex items-start gap-3">
                <div
                  className={cn(
                    'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ring-1',
                    ready
                      ? 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20'
                      : 'bg-amber-500/10 text-amber-400 ring-amber-500/20'
                  )}
                >
                  {ready ? (
                    <CheckCircle2 className="h-5 w-5" aria-hidden="true" />
                  ) : (
                    <ListChecks className="h-5 w-5" aria-hidden="true" />
                  )}
                </div>
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 id="setup-summary-heading" className="text-lg font-semibold">
                      {ready ? 'NukeLab is ready for first launches' : 'Finish setting up NukeLab'}
                    </h2>
                    <StatusBadge
                      status={ready ? 'healthy' : 'warning'}
                      label={`${completed} of 2 prerequisites`}
                      size="sm"
                    />
                  </div>
                  <p className="max-w-2xl text-sm text-muted-foreground">{bannerDescription}</p>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
                    <SetupStatusLabel ready={environmentReady}>
                      {environmentReady
                        ? `${activePublicEnvironments.length} public environment${activePublicEnvironments.length === 1 ? '' : 's'}`
                        : 'No public environment'}
                    </SetupStatusLabel>
                    <SetupStatusLabel ready={plansReady}>
                      {plansReady
                        ? `${activeUserVisiblePlans.length} plan${activeUserVisiblePlans.length === 1 ? '' : 's'} available to users`
                        : 'No plan available to users'}
                    </SetupStatusLabel>
                  </div>
                </div>
              </div>

              <div className="flex shrink-0 flex-col gap-2 sm:flex-row lg:pl-6">
                {ready ? (
                  <Link
                    to="/servers"
                    search={{ deploy: true }}
                    className={cn(buttonVariants({ size: 'sm' }), 'w-full sm:w-auto')}
                  >
                    <Rocket className="h-4 w-4" aria-hidden="true" />
                    Launch test server
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Link>
                ) : !environmentReady ? (
                  <Link
                    to="/admin/environments"
                    className={cn(buttonVariants({ size: 'sm' }), 'w-full sm:w-auto')}
                  >
                    <Boxes className="h-4 w-4" aria-hidden="true" />
                    Publish an environment
                  </Link>
                ) : (
                  <Link
                    to="/admin/plans"
                    className={cn(buttonVariants({ size: 'sm' }), 'w-full sm:w-auto')}
                  >
                    <CreditCard className="h-4 w-4" aria-hidden="true" />
                    Publish a plan
                  </Link>
                )}
              </div>
            </div>
          </section>

          <section aria-labelledby="setup-checklist-heading" className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <h2
                id="setup-checklist-heading"
                className="text-xs font-semibold uppercase tracking-widest text-muted-foreground"
              >
                Setup checklist
              </h2>
              <p className="text-xs text-muted-foreground">
                Launch prerequisites must be complete before users can deploy.
              </p>
            </div>

            <ol className="space-y-3">
              <EnvironmentStep index={1} environments={environments} />
              <PlansStep index={2} plans={activePlans} inactiveCount={inactivePlanCount} />
              <UsersStep index={3} />
            </ol>
          </section>

          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            This checklist stays available so you can review catalog readiness whenever environments
            or plans change.
          </p>
        </div>
      )}
    </ResourcePageLayout>
  )
}
