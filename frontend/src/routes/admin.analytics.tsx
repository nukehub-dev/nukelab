import { createFileRoute, Link } from '@tanstack/react-router';
import { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  BarChart3,
  Users,
  Server,
  CreditCard,
  TrendingUp,
  Activity,
  ArrowLeft,
  Zap,
  UserPlus,
  Clock,
  Cpu,
  HardDrive,
  FolderOpen,
  Layers,
  ActivitySquare,
} from 'lucide-react';
import {
  useGlobalUsage,
  useTopConsumers,
  useEnvironmentUsage,
  usePlanUsage,
  useCreditFlow,
  useUserGrowth,
  usePlatformMetrics,
  useVolumeAnalytics,
  useWorkspaceAnalytics,
} from '../hooks/use-analytics';
import { StatCard } from '../components/data/stat-card';
import { MetricsAreaChart, formatters } from '../components/charts/area-chart';
import { TimeSeriesBarChart } from '../components/charts/time-series-bar-chart';
import { GaugeChart } from '../components/charts/gauge-chart';
import { SegmentedBar } from '../components/charts/segmented-bar';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';
import { usePageGuard } from '../hooks/use-page-guard';
import { PERMISSIONS } from '../stores/auth-store';

export const Route = createFileRoute('/admin/analytics')({
  component: AnalyticsDashboard,
});

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function SectionHeader({
  icon: Icon,
  title,
  subtitle,
  delay = 0,
}: {
  icon: React.ElementType;
  title: string;
  subtitle?: string;
  delay?: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, ...springs.gentle }}
      className="flex items-center gap-3 mb-4"
    >
      <div className="p-1.5 rounded-lg bg-primary/10">
        <Icon className="w-4 h-4 text-primary" />
      </div>
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </h2>
        {subtitle && (
          <p className="text-xs text-muted-foreground/70 mt-0.5">{subtitle}</p>
        )}
      </div>
    </motion.div>
  );
}

function SkeletonCard() {
  return (
    <div className="bubble p-5 animate-pulse">
      <div className="flex items-start justify-between">
        <div className="space-y-3 flex-1">
          <div className="h-4 w-24 bg-muted rounded" />
          <div className="h-8 w-16 bg-muted rounded" />
          <div className="h-3 w-32 bg-muted rounded" />
        </div>
        <div className="w-10 h-10 rounded-full bg-muted" />
      </div>
    </div>
  );
}

function SkeletonChart() {
  return (
    <div className="bubble p-5 animate-pulse space-y-4">
      <div className="h-5 w-40 bg-muted rounded" />
      <div className="h-3 w-24 bg-muted rounded" />
      <div className="h-[200px] bg-muted rounded-lg" />
    </div>
  );
}

function formatHours(hours: number): string {
  if (hours >= 1000) return `${(hours / 1000).toFixed(1)}K hrs`;
  return `${Math.round(hours)} hrs`;
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

function AnalyticsDashboard() {
  const allowed = usePageGuard({ permission: PERMISSIONS.ANALYTICS_READ });
  if (!allowed) return null;

  const [days, setDays] = useState(30);

  /* Data hooks */
  const { data: globalUsage, isLoading: globalLoading } = useGlobalUsage(days);
  const { data: topConsumers } = useTopConsumers(days, 10);
  const { data: environmentUsage } = useEnvironmentUsage();
  const { data: planUsage } = usePlanUsage();
  const { data: creditFlow, isLoading: creditLoading } = useCreditFlow(days);
  const { data: userGrowth, isLoading: growthLoading } = useUserGrowth(days);
  const { data: platformMetrics, isLoading: metricsLoading } = usePlatformMetrics(days);
  const { data: volumeAnalytics, isLoading: volumeLoading } = useVolumeAnalytics();
  const { data: workspaceAnalytics, isLoading: workspaceLoading } = useWorkspaceAnalytics();

  /* Derived data */
  const serverCreationData = useMemo(
    () =>
      globalUsage?.server_creation_by_day?.map((d) => ({
        timestamp: d.date,
        count: d.count,
      })) || [],
    [globalUsage]
  );

  const creditFlowData = useMemo(
    () =>
      creditFlow?.map((d) => ({
        timestamp: d.date,
        consumed: d.credits_consumed,
        granted: d.credits_granted,
      })) || [],
    [creditFlow]
  );

  const userGrowthData = useMemo(
    () =>
      userGrowth?.map((d) => ({
        label: new Date(d.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        value: d.count,
      })) || [],
    [userGrowth]
  );

  const platformMetricsData = useMemo(
    () =>
      platformMetrics?.map((d) => ({
        timestamp: d.date,
        cpu: d.avg_cpu,
        memory: d.avg_memory,
      })) || [],
    [platformMetrics]
  );

  const serverStatusSegments = useMemo(() => {
    const breakdown = globalUsage?.server_status_breakdown || {};
    const colors: Record<string, string> = {
      running: 'var(--chart-2)',
      stopped: 'var(--muted)',
      pending: 'var(--chart-3)',
      error: 'var(--destructive)',
      unknown: 'var(--border)',
    };
    return Object.entries(breakdown)
      .map(([status, value]) => ({
        label: status.charAt(0).toUpperCase() + status.slice(1),
        value,
        color: colors[status] || colors.unknown,
      }))
      .sort((a, b) => b.value - a.value);
  }, [globalUsage]);

  /* Sparkline data for stat cards */
  const activeUsersSparkline = useMemo(
    () => globalUsage?.server_creation_by_day?.map((d) => d.count) || [],
    [globalUsage]
  );

  const signupSparkline = useMemo(
    () => userGrowth?.map((d) => d.count) || [],
    [userGrowth]
  );

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-10">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="flex flex-col md:flex-row md:items-center md:justify-between gap-4"
      >
        <div className="flex items-center gap-3">
          <Link
            to="/admin"
            className="p-2 rounded-lg hover:bg-accent transition-colors shrink-0 inline-flex"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="p-2 rounded-lg bg-primary/10">
            <BarChart3 className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Analytics Dashboard</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Platform-wide usage statistics and trends
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={cn(
                'px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
                days === d
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:bg-muted/80'
              )}
            >
              {d}d
            </button>
          ))}
        </div>
      </motion.div>

      {/* ── Platform Overview ── */}
      <section>
        <SectionHeader icon={Layers} title="Platform Overview" delay={0.05} />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {globalLoading ? (
            <>
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </>
          ) : (
            <>
              <StatCard
                title="Total Users"
                value={globalUsage?.total_users ?? 0}
                subtitle={`${globalUsage?.new_users ?? 0} new in last ${days}d`}
                icon={Users}
                iconColor="text-chart-1"
                bgColor="bg-chart-1/10"
                variant="compact"
              />
              <StatCard
                title="Active Users"
                value={globalUsage?.active_users ?? 0}
                subtitle={`Last ${days} days`}
                icon={Activity}
                iconColor="text-chart-2"
                bgColor="bg-chart-2/10"
                variant="compact"
                sparkline={activeUsersSparkline.length > 1 ? activeUsersSparkline : undefined}
              />
              <StatCard
                title="Total Servers"
                value={globalUsage?.total_servers ?? 0}
                subtitle={`${globalUsage?.running_servers ?? 0} currently running`}
                icon={Server}
                iconColor="text-chart-3"
                bgColor="bg-chart-3/10"
                variant="compact"
              />
              <StatCard
                title="Credits Consumed"
                value={globalUsage?.total_credits_consumed ?? 0}
                subtitle="NUKE credits"
                icon={CreditCard}
                iconColor="text-chart-4"
                bgColor="bg-chart-4/10"
                variant="compact"
              />
              <StatCard
                title="Running Servers"
                value={globalUsage?.running_servers ?? 0}
                subtitle="Live compute instances"
                icon={Zap}
                iconColor="text-emerald-400"
                bgColor="bg-emerald-500/10"
                variant="compact"
              />
              <StatCard
                title="New Signups"
                value={globalUsage?.new_users ?? 0}
                subtitle={`Last ${days} days`}
                icon={UserPlus}
                iconColor="text-chart-5"
                bgColor="bg-chart-5/10"
                variant="compact"
                sparkline={signupSparkline.length > 1 ? signupSparkline : undefined}
              />
              <StatCard
                title="Total Runtime"
                value={formatHours(globalUsage?.total_runtime_hours ?? 0)}
                subtitle="Cumulative server hours"
                icon={Clock}
                iconColor="text-amber-400"
                bgColor="bg-amber-500/10"
                variant="compact"
              />
              <StatCard
                title="Avg Platform CPU"
                value={`${globalUsage?.avg_platform_cpu ?? 0}%`}
                subtitle={`Avg over last ${days}d`}
                icon={Cpu}
                iconColor="text-cyan-400"
                bgColor="bg-cyan-500/10"
                variant="compact"
              />
            </>
          )}
        </div>
      </section>

      {/* ── Financial Flow ── */}
      <section>
        <SectionHeader icon={TrendingUp} title="Financial Flow" delay={0.1} />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {creditLoading || growthLoading ? (
            <>
              <SkeletonChart />
              <SkeletonChart />
            </>
          ) : (
            <>
              <motion.div
                className="bubble p-5 overflow-hidden"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.15, ...springs.gentle }}
              >
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="text-base font-semibold">Credits Flow</h3>
                    <p className="text-sm text-muted-foreground mt-0.5">
                      Consumed vs granted per day
                    </p>
                  </div>
                  <CreditCard className="w-4 h-4 text-muted-foreground mt-1" />
                </div>
                <MetricsAreaChart
                  data={creditFlowData}
                  series={[
                    { key: 'consumed', name: 'Consumed', color: 'var(--destructive)' },
                    { key: 'granted', name: 'Granted', color: 'var(--chart-2)' },
                  ]}
                  height={240}
                  yTickFormatter={(v) => String(Math.round(v))}
                  xTickFormatter={formatters.date}
                />
              </motion.div>

              <motion.div
                className="bubble p-5 overflow-hidden"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2, ...springs.gentle }}
              >
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="text-base font-semibold">User Growth</h3>
                    <p className="text-sm text-muted-foreground mt-0.5">
                      New signups per day
                    </p>
                  </div>
                  <UserPlus className="w-4 h-4 text-muted-foreground mt-1" />
                </div>
                <TimeSeriesBarChart
                  data={userGrowthData}
                  height={240}
                  name="Signups"
                  color="var(--chart-1)"
                />
              </motion.div>
            </>
          )}
        </div>
      </section>

      {/* ── Resource Utilization ── */}
      <section>
        <SectionHeader icon={ActivitySquare} title="Resource Utilization" delay={0.15} />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {metricsLoading || globalLoading ? (
            <>
              <SkeletonChart />
              <SkeletonChart />
            </>
          ) : (
            <>
              <motion.div
                className="bubble p-5 overflow-hidden"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2, ...springs.gentle }}
              >
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="text-base font-semibold">
                      Platform Resource Usage
                    </h3>
                    <p className="text-sm text-muted-foreground mt-0.5">
                      Average CPU & Memory across all servers
                    </p>
                  </div>
                  <Cpu className="w-4 h-4 text-muted-foreground mt-1" />
                </div>
                <MetricsAreaChart
                  data={platformMetricsData}
                  series={[
                    { key: 'cpu', name: 'CPU %', color: 'var(--chart-1)' },
                    { key: 'memory', name: 'Memory %', color: 'var(--chart-2)' },
                  ]}
                  height={240}
                  yTickFormatter={(v) => `${Math.round(v)}%`}
                  xTickFormatter={formatters.date}
                />
              </motion.div>

              <motion.div
                className="bubble p-5"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.25, ...springs.gentle }}
              >
                <div className="flex items-start justify-between mb-4">
                  <div>
                    <h3 className="text-base font-semibold">
                      Server Status Distribution
                    </h3>
                    <p className="text-sm text-muted-foreground mt-0.5">
                      Breakdown by current state
                    </p>
                  </div>
                  <Server className="w-4 h-4 text-muted-foreground mt-1" />
                </div>
                {serverStatusSegments.length > 0 &&
                serverStatusSegments.some((s) => s.value > 0) ? (
                  <SegmentedBar
                    segments={serverStatusSegments}
                    total={globalUsage?.total_servers}
                    height={28}
                  />
                ) : (
                  <div className="text-center py-10 text-muted-foreground">
                    <p className="text-sm">No server status data available</p>
                  </div>
                )}

                {/* Mini status grid */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
                  {serverStatusSegments.map((seg) => (
                    <div
                      key={seg.label}
                      className="flex flex-col items-center p-3 rounded-lg bg-surface/50 border border-border/50 relative overflow-hidden"
                    >
                      {/* Color tint background */}
                      <div
                        className="absolute inset-0 opacity-10"
                        style={{ backgroundColor: seg.color }}
                      />
                      <div className="relative flex flex-col items-center">
                        <div className="flex items-center gap-1.5 mb-1">
                          <div
                            className="w-2 h-2 rounded-full"
                            style={{ backgroundColor: seg.color }}
                          />
                          <span className="text-lg font-bold text-foreground">
                            {seg.value}
                          </span>
                        </div>
                        <span className="text-xs text-muted-foreground">
                          {seg.label}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </motion.div>
            </>
          )}
        </div>
      </section>

      {/* ── Storage & Collaboration ── */}
      <section>
        <SectionHeader
          icon={FolderOpen}
          title="Storage & Collaboration"
          delay={0.2}
        />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {volumeLoading ? (
            <SkeletonChart />
          ) : (
            <motion.div
              className="bubble p-5"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.25, ...springs.gentle }}
            >
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-base font-semibold">Storage Overview</h3>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    Volume utilization & distribution
                  </p>
                </div>
                <HardDrive className="w-4 h-4 text-muted-foreground mt-1" />
              </div>

              <div className="space-y-4">
                {/* Capacity bar */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Capacity</span>
                    <span className="font-medium">
                      {volumeAnalytics?.total_storage_used_gb ?? 0} GB /{' '}
                      {volumeAnalytics?.total_storage_capacity_gb ?? 0} GB
                    </span>
                  </div>
                  <div className="w-full h-2.5 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary transition-all duration-500"
                      style={{
                        width: `${Math.min(volumeAnalytics?.storage_utilization_percent ?? 0, 100)}%`,
                      }}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground text-right">
                    {volumeAnalytics?.storage_utilization_percent ?? 0}% utilized
                  </p>
                </div>

                {/* Volume counts */}
                <div className="grid grid-cols-2 gap-3">
                  <div className="p-3 rounded-lg bg-surface/50 border border-border/50 text-center">
                    <span className="text-xl font-bold text-foreground">
                      {volumeAnalytics?.total_volumes ?? 0}
                    </span>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Total Volumes
                    </p>
                  </div>
                  <div className="p-3 rounded-lg bg-surface/50 border border-border/50 text-center">
                    <span className="text-xl font-bold text-foreground">
                      {volumeAnalytics?.total_storage_used_gb ?? 0} GB
                    </span>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Storage Used
                    </p>
                  </div>
                </div>

                {/* Visibility breakdown */}
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    By Visibility
                  </p>
                  {volumeAnalytics?.volumes_by_visibility?.map((item) => (
                    <div
                      key={item.visibility}
                      className="flex items-center justify-between p-2 rounded-lg bg-surface/50 border border-border/50"
                    >
                      <span className="text-sm capitalize">{item.visibility}</span>
                      <span className="text-sm font-medium">{item.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            </motion.div>
          )}

          {workspaceLoading ? (
            <SkeletonChart />
          ) : (
            <motion.div
              className="bubble p-5"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3, ...springs.gentle }}
            >
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-base font-semibold">Workspace Adoption</h3>
                  <p className="text-sm text-muted-foreground mt-0.5">
                    Collaboration metrics
                  </p>
                </div>
                <FolderOpen className="w-4 h-4 text-muted-foreground mt-1" />
              </div>

              <div className="flex flex-col items-center py-2">
                <GaugeChart
                  value={workspaceAnalytics?.workspace_adoption_rate ?? 0}
                  size={140}
                  strokeWidth={10}
                  label="Adoption"
                />
              </div>

              <div className="grid grid-cols-3 gap-3 mt-4">
                <div className="p-3 rounded-lg bg-surface/50 border border-border/50 text-center">
                  <span className="text-lg font-bold text-foreground">
                    {workspaceAnalytics?.total_workspaces ?? 0}
                  </span>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Workspaces
                  </p>
                </div>
                <div className="p-3 rounded-lg bg-surface/50 border border-border/50 text-center">
                  <span className="text-lg font-bold text-foreground">
                    {workspaceAnalytics?.total_members ?? 0}
                  </span>
                  <p className="text-xs text-muted-foreground mt-0.5">Members</p>
                </div>
                <div className="p-3 rounded-lg bg-surface/50 border border-border/50 text-center">
                  <span className="text-lg font-bold text-foreground">
                    {workspaceAnalytics?.avg_members_per_workspace ?? 0}
                  </span>
                  <p className="text-xs text-muted-foreground mt-0.5">Avg/WS</p>
                </div>
              </div>
            </motion.div>
          )}
        </div>
      </section>

      {/* ── Charts Row: Server Creation + Top Consumers ── */}
      <section>
        <SectionHeader icon={BarChart3} title="Activity & Consumption" delay={0.25} />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <motion.div
            className="bubble p-5 overflow-hidden"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, ...springs.gentle }}
          >
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-base font-semibold">Server Creation</h3>
                <p className="text-sm text-muted-foreground mt-0.5">
                  New servers per day
                </p>
              </div>
              <Activity className="w-4 h-4 text-muted-foreground mt-1" />
            </div>
            <MetricsAreaChart
              data={serverCreationData}
              series={[{ key: 'count', name: 'Servers', color: 'var(--chart-1)' }]}
              height={240}
              yTickFormatter={(v) => String(Math.round(v))}
              xTickFormatter={formatters.date}
            />
          </motion.div>

          <motion.div
            className="bubble p-5 overflow-hidden"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.35, ...springs.gentle }}
          >
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-base font-semibold">Top Consumers</h3>
                <p className="text-sm text-muted-foreground mt-0.5">
                  By NUKE credits consumed
                </p>
              </div>
              <TrendingUp className="w-4 h-4 text-muted-foreground mt-1" />
            </div>
            <div className="space-y-2">
              {topConsumers?.slice(0, 5).map((consumer, index) => (
                <div
                  key={consumer.user_id}
                  className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-medium text-muted-foreground w-6">
                      #{index + 1}
                    </span>
                    <span className="text-sm font-medium">
                      {consumer.username}
                    </span>
                  </div>
                  <span className="text-sm font-medium tabular-nums">
                    {consumer.credits_consumed} NUKE
                  </span>
                </div>
              ))}
              {!topConsumers?.length && (
                <div className="text-center py-8 text-muted-foreground">
                  <p className="text-sm">No consumption data available</p>
                </div>
              )}
            </div>
          </motion.div>
        </div>
      </section>

      {/* ── Distribution ── */}
      <section>
        <SectionHeader icon={Layers} title="Distribution" delay={0.3} />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <motion.div
            className="bubble p-5"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.35, ...springs.gentle }}
          >
            <h3 className="text-base font-semibold mb-4">Environment Popularity</h3>
            <div className="space-y-2">
              {(() => {
                const maxCount =
                  environmentUsage && environmentUsage.length > 0
                    ? Math.max(...environmentUsage.map((e) => e.server_count))
                    : 1;
                return environmentUsage?.map((env) => {
                  const pct =
                    maxCount > 0 ? (env.server_count / maxCount) * 100 : 0;
                  return (
                    <div
                      key={env.id}
                      className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50"
                    >
                      <span className="text-sm font-medium">{env.name}</span>
                      <div className="flex items-center gap-3">
                        <div className="w-24 h-2 rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full bg-primary rounded-full transition-all duration-500"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-xs text-muted-foreground w-10 text-right">
                          {env.server_count}
                          {environmentUsage &&
                            env.server_count > 0 &&
                            ` (${Math.round(
                              (env.server_count /
                                environmentUsage.reduce(
                                  (s, e) => s + e.server_count,
                                  0
                                )) *
                                100
                            )}%)`}
                        </span>
                      </div>
                    </div>
                  );
                });
              })()}
              {!environmentUsage?.length && (
                <div className="text-center py-8 text-muted-foreground">
                  <p className="text-sm">No environment data available</p>
                </div>
              )}
            </div>
          </motion.div>

          <motion.div
            className="bubble p-5"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.4, ...springs.gentle }}
          >
            <h3 className="text-base font-semibold mb-4">Plan Distribution</h3>
            <div className="space-y-2">
              {(() => {
                const maxCount =
                  planUsage && planUsage.length > 0
                    ? Math.max(...planUsage.map((p) => p.server_count))
                    : 1;
                return planUsage?.map((plan) => {
                  const pct =
                    maxCount > 0 ? (plan.server_count / maxCount) * 100 : 0;
                  return (
                    <div
                      key={plan.id}
                      className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50"
                    >
                      <span className="text-sm font-medium">{plan.name}</span>
                      <div className="flex items-center gap-3">
                        <div className="w-24 h-2 rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full bg-chart-2 rounded-full transition-all duration-500"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-xs text-muted-foreground w-10 text-right">
                          {plan.server_count}
                          {planUsage &&
                            plan.server_count > 0 &&
                            ` (${Math.round(
                              (plan.server_count /
                                planUsage.reduce((s, p) => s + p.server_count, 0)) *
                                100
                            )}%)`}
                        </span>
                      </div>
                    </div>
                  );
                });
              })()}
              {!planUsage?.length && (
                <div className="text-center py-8 text-muted-foreground">
                  <p className="text-sm">No plan data available</p>
                </div>
              )}
            </div>
          </motion.div>
        </div>
      </section>
    </div>
  );
}
