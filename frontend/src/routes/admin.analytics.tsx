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
  Download,
  GitCommit,
  ToggleLeft,
  ToggleRight,
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
  useLoginEvents,
  useRequestMetrics,
} from '../hooks/use-analytics';
import { StatCard } from '../components/data/stat-card';
import { MetricsAreaChart } from '../components/charts/area-chart';
import { formatters } from '../components/charts/chart-formatters';
import { TimeSeriesBarChart } from '../components/charts/time-series-bar-chart';
import { GaugeChart } from '../components/charts/gauge-chart';
import { SegmentedBar } from '../components/charts/segmented-bar';
import { CalendarHeatmap } from '../components/charts/calendar-heatmap';
import { DateRangePicker, type DateRange } from '../components/ui/date-range-picker';
import { exportToCSV, exportToJSON } from '../lib/export';
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

function getDefaultDateRange(): DateRange {
  const to = new Date().toISOString().split('T')[0];
  const from = new Date();
  from.setDate(from.getDate() - 29);
  return { from: from.toISOString().split('T')[0], to };
}

function getPreviousPeriod(range: DateRange): DateRange {
  const from = new Date(range.from);
  const to = new Date(range.to);
  const diff = to.getTime() - from.getTime();
  return {
    from: new Date(from.getTime() - diff - 86400000).toISOString().split('T')[0],
    to: new Date(from.getTime() - 86400000).toISOString().split('T')[0],
  };
}

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

function ExportButton({ data, filename }: { data: unknown[]; filename: string }) {
  const [open, setOpen] = useState(false);
  if (!data.length) return null;
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((s) => !s)}
        className="p-1.5 rounded-md hover:bg-accent transition-colors text-muted-foreground"
      >
        <Download className="w-3.5 h-3.5" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 min-w-[100px] rounded-lg border bg-popover shadow-lg p-1">
            <button
              onClick={() => {
                exportToCSV(data as Record<string, unknown>[], filename);
                setOpen(false);
              }}
              className="w-full text-left px-2.5 py-1.5 rounded-md text-sm hover:bg-accent transition-colors"
            >
              CSV
            </button>
            <button
              onClick={() => {
                exportToJSON(data, filename);
                setOpen(false);
              }}
              className="w-full text-left px-2.5 py-1.5 rounded-md text-sm hover:bg-accent transition-colors"
            >
              JSON
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

function AnalyticsDashboard() {
  const allowed = usePageGuard({ permission: PERMISSIONS.ANALYTICS_READ });
  const [dateRange, setDateRange] = useState<DateRange>(getDefaultDateRange);
  const [compareMode, setCompareMode] = useState(false);
  const [heatmapTab, setHeatmapTab] = useState<'signups' | 'credits' | 'servers' | 'logins'>('signups');

  const dateParams = { from: dateRange.from, to: dateRange.to };
  const prevParams = compareMode ? getPreviousPeriod(dateRange) : undefined;

  /* Data hooks */
  const { data: globalUsage, isLoading: globalLoading } = useGlobalUsage(dateParams);
  const { data: globalUsagePrev } = useGlobalUsage(prevParams ?? {});
  const { data: topConsumers } = useTopConsumers({ ...dateParams, limit: 100 });
  const { data: environmentUsage } = useEnvironmentUsage();
  const { data: planUsage } = usePlanUsage();
  const { data: creditFlow, isLoading: creditLoading } = useCreditFlow(dateParams);
  const { data: creditFlowPrev } = useCreditFlow(prevParams ?? {});
  const { data: userGrowth, isLoading: growthLoading } = useUserGrowth(dateParams);
  const { data: loginEvents } = useLoginEvents(dateParams);
  const { data: platformMetrics, isLoading: metricsLoading } = usePlatformMetrics(dateParams);
  const { data: platformMetricsPrev } = usePlatformMetrics(prevParams ?? {});
  const { data: volumeAnalytics, isLoading: volumeLoading } = useVolumeAnalytics();
  const { data: workspaceAnalytics, isLoading: workspaceLoading } = useWorkspaceAnalytics();
  const { data: requestMetrics, isLoading: requestMetricsLoading } = useRequestMetrics(dateParams);

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

  const creditFlowDataPrev = useMemo(
    () =>
      creditFlowPrev?.map((d) => ({
        timestamp: d.date,
        consumedPrev: d.credits_consumed,
        grantedPrev: d.credits_granted,
      })) || [],
    [creditFlowPrev]
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

  const platformMetricsDataPrev = useMemo(
    () =>
      platformMetricsPrev?.map((d) => ({
        timestamp: d.date,
        cpuPrev: d.avg_cpu,
        memoryPrev: d.avg_memory,
      })) || [],
    [platformMetricsPrev]
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

  /* Comparison helpers */
  const comparePct = (curr: number, prev: number) => {
    if (!prev) return curr > 0 ? 100 : 0;
    return ((curr - prev) / prev) * 100;
  };

  const heatmapData = useMemo(() => {
    if (heatmapTab === 'signups') {
      return (
        userGrowth?.map((d) => ({ date: d.date, value: d.count })) || []
      );
    }
    if (heatmapTab === 'credits') {
      return (
        creditFlow?.map((d) => ({ date: d.date, value: d.credits_consumed })) || []
      );
    }
    if (heatmapTab === 'logins') {
      return (
        loginEvents?.map((d) => ({ date: d.date, value: d.count })) || []
      );
    }
    return (
      globalUsage?.server_creation_by_day?.map((d) => ({
        date: d.date,
        value: d.count,
      })) || []
    );
  }, [heatmapTab, userGrowth, creditFlow, loginEvents, globalUsage]);

  if (!allowed) return null;

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

        <div className="flex items-center gap-3 flex-wrap">
          <DateRangePicker value={dateRange} onChange={setDateRange} />
          <button
            onClick={() => setCompareMode((v) => !v)}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border',
              compareMode
                ? 'bg-primary text-primary-foreground border-primary'
                : 'bg-background text-muted-foreground hover:bg-accent'
            )}
          >
            {compareMode ? (
              <ToggleRight className="w-4 h-4" />
            ) : (
              <ToggleLeft className="w-4 h-4" />
            )}
            Compare
          </button>
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
                subtitle={`${globalUsage?.new_users ?? 0} new in period`}
                icon={Users}
                iconColor="text-chart-1"
                bgColor="bg-chart-1/10"
                variant="compact"
                trend={
                  compareMode && globalUsagePrev
                    ? {
                        value: Math.abs(
                          comparePct(globalUsage?.new_users ?? 0, globalUsagePrev?.new_users ?? 0)
                        ),
                        direction:
                          (globalUsage?.new_users ?? 0) >= (globalUsagePrev?.new_users ?? 0)
                            ? 'up'
                            : 'down',
                      }
                    : undefined
                }
              />
              <StatCard
                title="Active Users"
                value={globalUsage?.active_users ?? 0}
                subtitle="In selected period"
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
                trend={
                  compareMode && globalUsagePrev
                    ? {
                        value: Math.abs(
                          comparePct(
                            globalUsage?.total_credits_consumed ?? 0,
                            globalUsagePrev?.total_credits_consumed ?? 0
                          )
                        ),
                        direction:
                          (globalUsage?.total_credits_consumed ?? 0) >=
                          (globalUsagePrev?.total_credits_consumed ?? 0)
                            ? 'up'
                            : 'down',
                      }
                    : undefined
                }
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
                subtitle="In selected period"
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
                subtitle="Avg over period"
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
                  <div className="flex items-center gap-2">
                    <ExportButton
                      data={creditFlow || []}
                      filename={`credit-flow-${dateRange.from}-to-${dateRange.to}`}
                    />
                    <CreditCard className="w-4 h-4 text-muted-foreground mt-1" />
                  </div>
                </div>
                <MetricsAreaChart
                  data={
                    compareMode && creditFlowPrev
                      ? creditFlowData.map((d) => {
                          const prev = creditFlowDataPrev.find(
                            (p) => p.timestamp === d.timestamp
                          );
                          return {
                            ...d,
                            consumedPrev: prev?.consumedPrev ?? 0,
                            grantedPrev: prev?.grantedPrev ?? 0,
                          };
                        })
                      : creditFlowData
                  }
                  series={[
                    { key: 'consumed', name: 'Consumed', color: 'var(--destructive)' },
                    { key: 'granted', name: 'Granted', color: 'var(--chart-2)' },
                    ...(compareMode
                      ? [
                          {
                            key: 'consumedPrev' as const,
                            name: 'Consumed (prev)',
                            color: 'var(--destructive)',
                          },
                          {
                            key: 'grantedPrev' as const,
                            name: 'Granted (prev)',
                            color: 'var(--chart-2)',
                          },
                        ]
                      : []),
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
                  <div className="flex items-center gap-2">
                    <ExportButton
                      data={userGrowth || []}
                      filename={`user-growth-${dateRange.from}-to-${dateRange.to}`}
                    />
                    <UserPlus className="w-4 h-4 text-muted-foreground mt-1" />
                  </div>
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
                  <div className="flex items-center gap-2">
                    <ExportButton
                      data={platformMetrics || []}
                      filename={`platform-metrics-${dateRange.from}-to-${dateRange.to}`}
                    />
                    <Cpu className="w-4 h-4 text-muted-foreground mt-1" />
                  </div>
                </div>
                <MetricsAreaChart
                  data={
                    compareMode && platformMetricsPrev
                      ? platformMetricsData.map((d) => {
                          const prev = platformMetricsDataPrev.find(
                            (p) => p.timestamp === d.timestamp
                          );
                          return {
                            ...d,
                            cpuPrev: prev?.cpuPrev ?? 0,
                            memoryPrev: prev?.memoryPrev ?? 0,
                          };
                        })
                      : platformMetricsData
                  }
                  series={[
                    { key: 'cpu', name: 'CPU %', color: 'var(--chart-1)' },
                    { key: 'memory', name: 'Memory %', color: 'var(--chart-2)' },
                    ...(compareMode
                      ? [
                          {
                            key: 'cpuPrev' as const,
                            name: 'CPU % (prev)',
                            color: 'var(--chart-1)',
                          },
                          {
                            key: 'memoryPrev' as const,
                            name: 'Memory % (prev)',
                            color: 'var(--chart-2)',
                          },
                        ]
                      : []),
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

      {/* ── Activity Patterns (Calendar Heatmap) ── */}
      <section>
        <SectionHeader icon={GitCommit} title="Activity Patterns" delay={0.18} />
        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.22, ...springs.gentle }}
        >
          <div className="flex items-center gap-2 mb-4">
            {(['signups', 'credits', 'servers', 'logins'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setHeatmapTab(tab)}
                className={cn(
                  'px-3 py-1 rounded-lg text-sm font-medium transition-colors',
                  heatmapTab === tab
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-muted-foreground hover:bg-muted/80'
                )}
              >
                {tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>
          <CalendarHeatmap
            data={heatmapData}
            from={dateRange.from || getDefaultDateRange().from}
            to={dateRange.to || getDefaultDateRange().to}
            metric={heatmapTab}
          />
        </motion.div>
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
              <div className="flex items-center gap-2">
                <ExportButton
                  data={globalUsage?.server_creation_by_day || []}
                  filename={`server-creation-${dateRange.from}-to-${dateRange.to}`}
                />
                <Activity className="w-4 h-4 text-muted-foreground mt-1" />
              </div>
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
            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
              {topConsumers?.map((consumer, index) => (
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

      {/* ── API Performance ── */}
      <section>
        <SectionHeader icon={Zap} title="API Performance" delay={0.3} />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
          <motion.div
            className="bubble p-4"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.35, ...springs.gentle }}
          >
            <h3 className="text-sm font-semibold text-muted-foreground mb-1">Total Requests</h3>
            <p className="text-2xl font-bold">
              {requestMetricsLoading ? '—' : (requestMetrics?.summary.total_requests ?? 0).toLocaleString()}
            </p>
          </motion.div>
          <motion.div
            className="bubble p-4"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.4, ...springs.gentle }}
          >
            <h3 className="text-sm font-semibold text-muted-foreground mb-1">Avg Duration</h3>
            <p className="text-2xl font-bold">
              {requestMetricsLoading ? '—' : `${(requestMetrics?.summary.avg_duration_ms ?? 0).toFixed(1)} ms`}
            </p>
          </motion.div>
          <motion.div
            className="bubble p-4"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.45, ...springs.gentle }}
          >
            <h3 className="text-sm font-semibold text-muted-foreground mb-1">Error Rate</h3>
            <p className="text-2xl font-bold">
              {requestMetricsLoading ? '—' : `${(requestMetrics?.summary.error_rate ?? 0).toFixed(2)}%`}
            </p>
          </motion.div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <motion.div
            className="bubble p-5"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.35, ...springs.gentle }}
          >
            <h3 className="text-base font-semibold mb-4">Endpoints by P95 Latency</h3>
            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
              {requestMetrics?.endpoints?.map((ep) => (
                <div
                  key={`${ep.method}:${ep.path}`}
                  className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      {ep.method}
                    </span>
                    <span className="text-sm font-medium truncate">{ep.path}</span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-muted-foreground shrink-0">
                    <span className="tabular-nums">{ep.count} req</span>
                    <span className="tabular-nums">p95: {ep.p95_ms.toFixed(0)}ms</span>
                    {ep.error_rate > 0 && (
                      <span className="text-destructive tabular-nums">{ep.error_rate.toFixed(1)}% err</span>
                    )}
                  </div>
                </div>
              ))}
              {!requestMetrics?.endpoints?.length && (
                <div className="text-center py-8 text-muted-foreground">
                  <p className="text-sm">No API metrics available yet</p>
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
            <h3 className="text-base font-semibold mb-4">Recent Requests</h3>
            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
              {requestMetrics?.recent?.map((req) => (
                <div
                  key={req.id}
                  className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className={`text-xs font-mono px-1.5 py-0.5 rounded ${
                      req.status_code < 400
                        ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400'
                        : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                    }`}>
                      {req.status_code}
                    </span>
                    <span className="text-xs font-mono text-muted-foreground">{req.method}</span>
                    <span className="text-sm truncate">{req.path}</span>
                  </div>
                  <span className="text-xs text-muted-foreground tabular-nums shrink-0">
                    {req.duration_ms.toFixed(1)} ms
                  </span>
                </div>
              ))}
              {!requestMetrics?.recent?.length && (
                <div className="text-center py-8 text-muted-foreground">
                  <p className="text-sm">No recent requests</p>
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
