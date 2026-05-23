import { createFileRoute, Link } from '@tanstack/react-router';
import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  BarChart3,
  Users,
  Server,
  CreditCard,
  TrendingUp,
  Activity,
  ArrowLeft,
} from 'lucide-react';
import {
  useGlobalUsage,
  useTopConsumers,
  useEnvironmentUsage,
  usePlanUsage,
} from '../hooks/use-analytics';
import { MetricsAreaChart, formatters } from '../components/charts/area-chart';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';
import { usePageGuard } from '../hooks/use-page-guard';
import { PERMISSIONS } from '../stores/auth-store';

export const Route = createFileRoute('/admin/analytics')({
  component: AnalyticsDashboard,
});

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ElementType;
  iconColor: string;
  bgColor: string;
}

function StatCard({ title, value, subtitle, icon: Icon, iconColor, bgColor }: StatCardProps) {
  return (
    <motion.div
      className="bubble p-5 hover-lift cursor-default"
      whileHover={{ y: -4, transition: springs.gentle }}
      initial={{ opacity: 0, scale: 0.95, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={springs.gentle}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className={cn("p-2 rounded-lg", bgColor)}>
            <Icon className={cn("w-4 h-4", iconColor)} />
          </div>
          <span className="text-sm font-medium text-muted-foreground">{title}</span>
        </div>
      </div>
      <div className="mt-3">
        <p className="text-2xl font-bold tabular-nums">{value}</p>
        {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
      </div>
    </motion.div>
  );
}

function AnalyticsDashboard() {
  const allowed = usePageGuard({ permission: PERMISSIONS.ANALYTICS_READ });
  if (!allowed) return null;

  const [days, setDays] = useState(30);
  const { data: globalUsage } = useGlobalUsage(days);
  const { data: topConsumers } = useTopConsumers(days, 10);
  const { data: environmentUsage } = useEnvironmentUsage();
  const { data: planUsage } = usePlanUsage();

  const serverCreationData = globalUsage?.server_creation_by_day?.map((d) => ({
    timestamp: d.date,
    count: d.count,
  })) || [];

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
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
                "px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                days === d
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              )}
            >
              {d}d
            </button>
          ))}
        </div>
      </motion.div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Active Users"
          value={globalUsage?.active_users || 0}
          subtitle={`Last ${days} days`}
          icon={Users}
          iconColor="text-chart-1"
          bgColor="bg-chart-1/10"
        />
        <StatCard
          title="Credits Consumed"
          value={globalUsage?.total_credits_consumed || 0}
          subtitle="NUKE credits"
          icon={CreditCard}
          iconColor="text-chart-2"
          bgColor="bg-chart-2/10"
        />
        <StatCard
          title="Servers Created"
          value={serverCreationData.reduce((sum, d) => sum + d.count, 0)}
          subtitle={`Last ${days} days`}
          icon={Server}
          iconColor="text-chart-3"
          bgColor="bg-chart-3/10"
        />
        <StatCard
          title="Top Consumer"
          value={topConsumers?.[0]?.username || 'N/A'}
          subtitle={topConsumers?.[0] ? `${topConsumers[0].credits_consumed} NUKE` : ''}
          icon={TrendingUp}
          iconColor="text-chart-4"
          bgColor="bg-chart-4/10"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <motion.div
          className="bubble p-5 overflow-hidden"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, ...springs.gentle }}
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold">Server Creation</h3>
              <p className="text-sm text-muted-foreground mt-0.5">New servers per day</p>
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
          transition={{ delay: 0.2, ...springs.gentle }}
        >
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="text-base font-semibold">Top Consumers</h3>
              <p className="text-sm text-muted-foreground mt-0.5">By NUKE credits consumed</p>
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
                  <span className="text-sm font-medium">{consumer.username}</span>
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

      {/* Environment & Plan Usage */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <motion.div
          className="bubble p-5"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, ...springs.gentle }}
        >
          <h3 className="text-base font-semibold mb-4">Environment Popularity</h3>
          <div className="space-y-2">
            {environmentUsage?.map((env) => (
              <div
                key={env.id}
                className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50"
              >
                <span className="text-sm font-medium">{env.name}</span>
                <div className="flex items-center gap-2">
                  <div className="w-24 h-2 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full"
                      style={{
                        width: `${Math.min(
                          ((env.server_count / (environmentUsage?.[0]?.server_count || 1)) * 100),
                          100
                        )}%`,
                      }}
                    />
                  </div>
                  <span className="text-xs text-muted-foreground w-8 text-right">
                    {env.server_count}
                  </span>
                </div>
              </div>
            ))}
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
            {planUsage?.map((plan) => (
              <div
                key={plan.id}
                className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50"
              >
                <span className="text-sm font-medium">{plan.name}</span>
                <div className="flex items-center gap-2">
                  <div className="w-24 h-2 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full bg-chart-2 rounded-full"
                      style={{
                        width: `${Math.min(
                          ((plan.server_count / (planUsage?.[0]?.server_count || 1)) * 100),
                          100
                        )}%`,
                      }}
                    />
                  </div>
                  <span className="text-xs text-muted-foreground w-8 text-right">
                    {plan.server_count}
                  </span>
                </div>
              </div>
            ))}
            {!planUsage?.length && (
              <div className="text-center py-8 text-muted-foreground">
                <p className="text-sm">No plan data available</p>
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
