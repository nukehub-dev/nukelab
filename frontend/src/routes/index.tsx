import { createFileRoute } from '@tanstack/react-router';
import { motion } from 'framer-motion';
import {
  LayoutDashboard,
  Server,
  Boxes,
  Activity,
  Network,
  Users,
  Zap,
} from 'lucide-react';
import { staggerContainerVariants, staggerItemVariants } from '../lib/animations';
import { FloatingHeader } from '../components/layout/floating-header';
import { StatCard } from '../components/data/stat-card';

import { useDashboard } from '../hooks/use-dashboard';
import { SkeletonCard } from '../components/feedback/skeleton';
import { MetricsDashboard } from '../components/charts/metrics-dashboard';
import { formatDate } from '../lib/utils';

export const Route = createFileRoute('/')({
  component: DashboardPage,
});

function DashboardPage() {
  const { data: dashboard, isLoading, isError, error } = useDashboard();

  const stats = dashboard ? [
    { 
      title: 'Active Servers', 
      value: dashboard.my_servers.running, 
      subtitle: `${dashboard.my_servers.stopped} stopped`, 
      icon: Server, 
      iconColor: 'text-emerald-400', 
      bgColor: 'bg-emerald-500/10' 
    },
    { 
      title: 'Total Servers', 
      value: dashboard.my_servers.total, 
      subtitle: `${dashboard.my_servers.pending} pending`, 
      icon: Boxes, 
      iconColor: 'text-blue-400', 
      bgColor: 'bg-blue-500/10' 
    },
    { 
      title: 'Nuke Balance', 
      value: dashboard.my_nukes.balance, 
      subtitle: `${dashboard.my_nukes.daily_allowance} daily`, 
      icon: Zap, 
      iconColor: 'text-amber-400', 
      bgColor: 'bg-amber-500/10' 
    },
  ] : [
    { title: 'Active Servers', value: 0, subtitle: '0 stopped', icon: Server, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
    { title: 'Total Servers', value: 0, subtitle: '0 pending', icon: Boxes, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
    { title: 'Nuke Balance', value: 0, subtitle: '0 daily', icon: Zap, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
  ];

  const platformStats = dashboard?.platform_stats;

  return (
    <div className="min-h-screen">
      <FloatingHeader
        title="Dashboard"
        subtitle="Overview of your nuclear engineering simulation infrastructure"
        icon={LayoutDashboard}
        stats={stats}
      />

      <div className="p-6 lg:p-10 space-y-8">
        {/* Ambient background blobs */}
        <div className="fixed inset-0 overflow-hidden pointer-events-none -z-10">
          <div className="absolute top-20 right-20 w-[400px] h-[400px] rounded-full bg-primary/10 blur-[80px] blob-float" />
          <div className="absolute bottom-20 left-40 w-[300px] h-[300px] rounded-full bg-chart-2/10 blur-[80px] blob-float" style={{ animationDelay: '-5s' }} />
        </div>

        {/* Error State */}
        {isError && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bubble p-8 text-center space-y-4"
          >
            <p className="text-destructive font-medium">{error?.message || 'Failed to load dashboard data'}</p>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
            >
              Retry
            </button>
          </motion.div>
        )}

        {/* Platform Stats (Admin) */}
        {platformStats && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="grid grid-cols-2 lg:grid-cols-4 gap-4"
          >
            {[
              { title: 'Total Users', value: platformStats.total_users, icon: Users, iconColor: 'text-blue-400', bgColor: 'bg-blue-500/10' },
              { title: 'Active Servers', value: platformStats.active_servers, icon: Server, iconColor: 'text-emerald-400', bgColor: 'bg-emerald-500/10' },
              { title: 'Total Servers', value: platformStats.total_servers, icon: Boxes, iconColor: 'text-amber-400', bgColor: 'bg-amber-500/10' },
              { title: 'Total Nukes', value: platformStats.total_nukes, icon: Zap, iconColor: 'text-violet-400', bgColor: 'bg-violet-500/10' },
            ].map((stat) => (
              <StatCard key={stat.title} {...stat} variant="compact" />
            ))}
          </motion.div>
        )}

        {/* Stats Grid */}
        <motion.div
          variants={staggerContainerVariants}
          initial="hidden"
          animate="visible"
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4"
        >
          {isLoading
            ? Array.from({ length: 4 }).map((_, i) => (
                <SkeletonCard key={i} />
              ))
            : stats.map((stat) => (
                <motion.div key={stat.title} variants={staggerItemVariants}>
                  <StatCard {...stat} />
                </motion.div>
              ))}
        </motion.div>

        {/* Real-Time Metrics Dashboard */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.35 }}
        >
          <MetricsDashboard />
        </motion.div>

        {/* Quick Actions */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="bubble p-6"
        >
          <h2 className="text-lg font-semibold mb-4">Quick Actions</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Deploy Server', icon: Server, color: 'bg-primary/10 text-primary' },
              { label: 'New Environment', icon: Boxes, color: 'bg-chart-2/10 text-chart-2' },
              { label: 'View Logs', icon: Activity, color: 'bg-chart-3/10 text-chart-3' },
              { label: 'Manage Network', icon: Network, color: 'bg-chart-4/10 text-chart-4' },
            ].map((action) => (
              <button
                key={action.label}
                className="flex flex-col items-center gap-3 p-4 rounded-xl border border-border/50 hover:border-primary/50 hover:bg-primary/5 transition-all duration-200 group"
              >
                <div className={`p-3 rounded-lg ${action.color}`}>
                  <action.icon className="w-5 h-5" />
                </div>
                <span className="text-sm font-medium">{action.label}</span>
              </button>
            ))}
          </div>
        </motion.div>

        {/* Recent Activity */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
          className="bubble p-6"
        >
          <h2 className="text-lg font-semibold mb-4">Recent Activity</h2>
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
                <div key={item.id} className="flex items-center gap-4 p-3 rounded-lg hover:bg-accent/50 transition-colors">
                  <div className="w-2 h-2 rounded-full bg-emerald-400" />
                  <div className="flex-1">
                    <span className="font-medium">{item.action}</span>
                    {item.target_id && (
                      <>
                        <span className="text-muted-foreground mx-2">on</span>
                        <span className="font-mono text-sm">{item.target_type}:{item.target_id}</span>
                      </>
                    )}
                  </div>
                  <span className="text-sm text-muted-foreground">{formatDate(item.timestamp)}</span>
                </div>
              ))
            )}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
