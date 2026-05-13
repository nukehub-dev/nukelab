import { createFileRoute, Outlet, Link, useLocation } from '@tanstack/react-router';
import {
  LayoutDashboard,
  Users,
  Server,
  BarChart3,
  FileText,
  CreditCard,
  Boxes,
  CreditCard as PlanIcon,
  Shield,
  Settings,
  ChevronRight,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useAuthStore, PERMISSIONS } from '../stores/auth-store';

interface AdminNavItem {
  label: string;
  icon: React.ElementType;
  href: string;
  requiredPermission?: string;
}

const adminNavItems: AdminNavItem[] = [
  { label: 'Overview', icon: LayoutDashboard, href: '/admin' },
  { label: 'Users', icon: Users, href: '/admin/users', requiredPermission: PERMISSIONS.USERS_READ },
  { label: 'Servers', icon: Server, href: '/admin/servers', requiredPermission: PERMISSIONS.SERVERS_READ_ALL },
  { label: 'Analytics', icon: BarChart3, href: '/admin/analytics', requiredPermission: PERMISSIONS.ANALYTICS_READ },
  { label: 'Audit Logs', icon: FileText, href: '/admin/audit-logs', requiredPermission: PERMISSIONS.AUDIT_READ },
  { label: 'Credits', icon: CreditCard, href: '/admin/credits', requiredPermission: PERMISSIONS.CREDITS_READ },
  { label: 'Environments', icon: Boxes, href: '/admin/environments', requiredPermission: PERMISSIONS.ENVIRONMENT_CREATE },
  { label: 'Plans', icon: PlanIcon, href: '/admin/plans', requiredPermission: PERMISSIONS.PLAN_CREATE },
  { label: 'Permissions', icon: Shield, href: '/admin/permissions', requiredPermission: PERMISSIONS.ADMIN_ACCESS },
  { label: 'Settings', icon: Settings, href: '/admin/settings', requiredPermission: PERMISSIONS.ADMIN_ACCESS },
];

export const Route = createFileRoute('/admin')({
  component: AdminLayout,
});

function AdminLayout() {
  const location = useLocation();
  const hasPermission = useAuthStore((state) => state.hasPermission);

  const visibleItems = adminNavItems.filter(item => !item.requiredPermission || hasPermission(item.requiredPermission));

  const isActive = (href: string) => {
    if (href === '/admin') return location.pathname === '/admin';
    return location.pathname.startsWith(href);
  };

  return (
    <div className="flex flex-col lg:flex-row gap-6 h-full px-4 lg:px-0 pt-6 lg:pt-8">
      {/* Sidebar Navigation */}
      <aside className="lg:w-64 shrink-0">
        <div className="sticky top-6 space-y-1">
          <div className="flex items-center gap-3 px-4 py-3 mb-4">
            <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center">
              <Settings className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h1 className="font-semibold text-lg">Admin</h1>
              <p className="text-xs text-muted-foreground">Platform management</p>
            </div>
          </div>

          <nav className="space-y-0.5">
            {visibleItems.map((item) => (
              <Link
                key={item.href}
                to={item.href}
                className={cn(
                  "flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 group",
                  isActive(item.href)
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                )}
              >
                <item.icon className={cn("w-4 h-4", isActive(item.href) ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
                <span className="flex-1">{item.label}</span>
                <ChevronRight className={cn("w-4 h-4 opacity-0 group-hover:opacity-50 transition-opacity", isActive(item.href) && "opacity-50")} />
              </Link>
            ))}
          </nav>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 min-w-0 pr-4 lg:pr-8">
        <Outlet />
      </main>
    </div>
  );
}
