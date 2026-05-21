import { createFileRoute, Link } from '@tanstack/react-router';
import {
  Users,
  Server,
  BarChart3,
  FileText,
  CreditCard,
  Boxes,
  Shield,
  Settings,
  ChevronRight,
  LayoutDashboard,
  Gauge,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { useAuthStore, PERMISSIONS } from '../stores/auth-store';
import { cn } from '../lib/utils';

interface AdminCategory {
  label: string;
  description: string;
  icon: React.ElementType;
  href: string;
  requiredPermission?: string;
  color: string;
}

const categories: AdminCategory[] = [
  {
    label: 'Users',
    description: 'Manage user accounts, roles, and access',
    icon: Users,
    href: '/admin/users',
    requiredPermission: PERMISSIONS.USERS_READ,
    color: 'bg-blue-500/10 text-blue-400',
  },
  {
    label: 'Servers',
    description: 'View and manage all platform servers',
    icon: Server,
    href: '/admin/servers',
    requiredPermission: PERMISSIONS.SERVERS_READ_ALL,
    color: 'bg-emerald-500/10 text-emerald-400',
  },
  {
    label: 'Analytics',
    description: 'Platform-wide usage statistics and trends',
    icon: BarChart3,
    href: '/admin/analytics',
    requiredPermission: PERMISSIONS.ANALYTICS_READ,
    color: 'bg-violet-500/10 text-violet-400',
  },
  {
    label: 'Audit Logs',
    description: 'Review system activity and changes',
    icon: FileText,
    href: '/admin/audit-logs',
    requiredPermission: PERMISSIONS.AUDIT_READ,
    color: 'bg-amber-500/10 text-amber-400',
  },
  {
    label: 'Credits',
    description: 'Manage user credits and balances',
    icon: CreditCard,
    href: '/admin/credits',
    requiredPermission: PERMISSIONS.CREDITS_READ,
    color: 'bg-rose-500/10 text-rose-400',
  },
  {
    label: 'Environments',
    description: 'Configure deployment environments',
    icon: Boxes,
    href: '/admin/environments',
    requiredPermission: PERMISSIONS.ENVIRONMENT_CREATE,
    color: 'bg-cyan-500/10 text-cyan-400',
  },
  {
    label: 'Plans',
    description: 'Manage server plans and pricing',
    icon: CreditCard,
    href: '/admin/plans',
    requiredPermission: PERMISSIONS.PLAN_CREATE,
    color: 'bg-orange-500/10 text-orange-400',
  },
  {
    label: 'Quotas',
    description: 'Manage per-user resource limits',
    icon: Gauge,
    href: '/admin/quotas',
    requiredPermission: PERMISSIONS.QUOTA_READ,
    color: 'bg-teal-500/10 text-teal-400',
  },
  {
    label: 'Permissions',
    description: 'Configure roles and access control',
    icon: Shield,
    href: '/admin/permissions',
    requiredPermission: PERMISSIONS.ADMIN_ACCESS,
    color: 'bg-purple-500/10 text-purple-400',
  },
  {
    label: 'Settings',
    description: 'Platform-wide system settings',
    icon: Settings,
    href: '/admin/settings',
    requiredPermission: PERMISSIONS.ADMIN_ACCESS,
    color: 'bg-primary/10 text-primary',
  },
];

export const Route = createFileRoute('/admin/')({
  component: AdminIndexPage,
});

function AdminIndexPage() {
  const hasPermission = useAuthStore((state) => state.hasPermission);

  const visibleCategories = categories.filter(
    (c) => !c.requiredPermission || hasPermission(c.requiredPermission)
  );

  return (
    <div className="min-h-screen p-6 lg:p-10 space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3"
      >
        <div className="p-2 rounded-xl bg-primary/10">
          <LayoutDashboard className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h1 className="text-2xl font-bold">Administration</h1>
          <p className="text-sm text-muted-foreground">
            Platform management and configuration
          </p>
        </div>
      </motion.div>

      {/* Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {visibleCategories.map((category, i) => (
          <motion.div
            key={category.label}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05, duration: 0.4 }}
            className="h-full"
          >
            <Link
              to={category.href}
              className="group flex items-start gap-4 p-5 rounded-xl bg-card/50 border border-border/50 hover:border-primary/30 hover:bg-card/80 transition-all duration-200 h-full"
            >
              <div
                className={cn(
                  'w-10 h-10 rounded-xl flex items-center justify-center shrink-0',
                  category.color
                )}
              >
                <category.icon className="w-5 h-5" />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-base group-hover:text-primary transition-colors">
                  {category.label}
                </h3>
                <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                  {category.description}
                </p>
              </div>
              <ChevronRight className="w-5 h-5 text-muted-foreground/50 group-hover:text-muted-foreground group-hover:translate-x-0.5 transition-all shrink-0 mt-1" />
            </Link>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
