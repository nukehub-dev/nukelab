import { createFileRoute, Link } from '@tanstack/react-router';
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Users,
  Server,
  CreditCard,
  Activity,
  ArrowRight,
  Plus,
  TrendingUp,
  AlertTriangle,
} from 'lucide-react';
import { api } from '../lib/api';
import { useAuthStore } from '../stores/auth-store';
import { springs } from '../lib/animations';
import { cn } from '../lib/utils';
import { StatCard } from '../components/data/stat-card';

interface AdminStats {
  total_users: number;
  active_users: number;
  disabled_users: number;
  total_servers: number;
  running_servers: number;
  stopped_servers: number;
  total_credits_granted: number;
  total_credits_consumed: number;
  low_credit_users: number;
}

export const Route = createFileRoute('/admin/')({
  component: AdminDashboardPage,
});

function AdminDashboardPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const hasPermission = useAuthStore((state) => state.hasPermission);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const data = await api.get<AdminStats>('/admin/stats');
        setStats(data);
      } catch (err: any) {
        setError(err?.response?.data?.detail || 'Failed to load admin stats');
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
  }, []);

  const quickActions = [
    {
      label: 'Add User',
      href: '/admin/users',
      icon: Plus,
      color: 'bg-blue-500/10 text-blue-400',
      permission: 'users:create',
    },
    {
      label: 'Grant Credits',
      href: '/admin/credits',
      icon: CreditCard,
      color: 'bg-emerald-500/10 text-emerald-400',
      permission: 'credits:grant',
    },
    {
      label: 'New Environment',
      href: '/admin/environments',
      icon: TrendingUp,
      color: 'bg-violet-500/10 text-violet-400',
      permission: 'environment:create',
    },
    {
      label: 'New Plan',
      href: '/admin/plans',
      icon: Activity,
      color: 'bg-amber-500/10 text-amber-400',
      permission: 'plan:create',
    },
  ].filter((action) => hasPermission(action.permission));

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Admin Dashboard</h1>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 bg-muted/50 rounded-xl animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Admin Dashboard</h1>
        </div>
        <div className="p-6 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5" />
            <p>{error}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="flex items-center justify-between"
      >
        <div>
          <h1 className="text-2xl font-bold">Admin Dashboard</h1>
          <p className="text-muted-foreground mt-1">Overview of platform activity and management tools.</p>
        </div>
      </motion.div>

      {/* Quick Actions */}
      {quickActions.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, ...springs.gentle }}
          className="grid grid-cols-2 lg:grid-cols-4 gap-3"
        >
          {quickActions.map((action) => (
            <Link
              key={action.label}
              to={action.href}
              className={cn(
                "flex items-center gap-3 p-4 rounded-xl border border-border/50 hover:border-primary/30 transition-all hover:shadow-lg group",
                "bg-card/50 backdrop-blur-sm"
              )}
            >
              <div className={cn("p-2 rounded-lg", action.color)}>
                <action.icon className="w-5 h-5" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-medium text-sm truncate">{action.label}</p>
              </div>
              <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors" />
            </Link>
          ))}
        </motion.div>
      )}

      {/* Stats Grid */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2, ...springs.gentle }}
        className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4"
      >
        <StatCard
          title="Total Users"
          value={stats?.total_users ?? 0}
          icon={Users}
          iconColor="text-blue-400"
          bgColor="bg-blue-500/10"
          variant="compact"
        />
        <StatCard
          title="Active Servers"
          value={stats?.running_servers ?? 0}
          icon={Server}
          iconColor="text-emerald-400"
          bgColor="bg-emerald-500/10"
          variant="compact"
        />
        <StatCard
          title="Total Servers"
          value={stats?.total_servers ?? 0}
          icon={Server}
          iconColor="text-violet-400"
          bgColor="bg-violet-500/10"
          variant="compact"
        />
        <StatCard
          title="Credits Granted"
          value={stats?.total_credits_granted ?? 0}
          icon={CreditCard}
          iconColor="text-amber-400"
          bgColor="bg-amber-500/10"
          variant="compact"
        />
      </motion.div>

      {/* Secondary Stats */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3, ...springs.gentle }}
        className="grid grid-cols-1 md:grid-cols-3 gap-4"
      >
        <div className="p-5 rounded-xl bg-card/50 border border-border/50">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium text-sm">User Breakdown</h3>
            <Users className="w-4 h-4 text-muted-foreground" />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Active</span>
              <span className="font-medium">{stats?.active_users ?? 0}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Disabled</span>
              <span className="font-medium">{stats?.disabled_users ?? 0}</span>
            </div>
          </div>
        </div>

        <div className="p-5 rounded-xl bg-card/50 border border-border/50">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium text-sm">Server Status</h3>
            <Server className="w-4 h-4 text-muted-foreground" />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Running</span>
              <span className="font-medium text-emerald-400">{stats?.running_servers ?? 0}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Stopped</span>
              <span className="font-medium">{stats?.stopped_servers ?? 0}</span>
            </div>
          </div>
        </div>

        <div className="p-5 rounded-xl bg-card/50 border border-border/50">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium text-sm">Credit Overview</h3>
            <CreditCard className="w-4 h-4 text-muted-foreground" />
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Granted</span>
              <span className="font-medium">{stats?.total_credits_granted ?? 0}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Consumed</span>
              <span className="font-medium">{stats?.total_credits_consumed ?? 0}</span>
            </div>
            {((stats?.low_credit_users ?? 0) > 0) && (
              <div className="flex items-center justify-between text-sm pt-1 border-t border-border/30">
                <span className="text-amber-400 flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" />
                  Low Balance
                </span>
                <span className="font-medium text-amber-400">{stats?.low_credit_users}</span>
              </div>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
