import { createFileRoute, Outlet, Link, useLocation } from '@tanstack/react-router';
import { 
  Settings, 
  Palette, 
  Shield, 
  Bell, 
  Users,
  UserCircle,
  ChevronRight
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useAuthStore, PERMISSIONS } from '../stores/auth-store';

interface SettingsNavItem {
  label: string;
  icon: React.ElementType;
  href: string;
  requiredPermission?: string;
}

const settingsNavItems: SettingsNavItem[] = [
  { label: 'Profile', icon: UserCircle, href: '/settings/profile' },
  { label: 'Appearance', icon: Palette, href: '/settings/appearance' },
  { label: 'Notifications', icon: Bell, href: '/settings/notifications' },
  { label: 'Authentication', icon: Shield, href: '/settings/authentication', requiredPermission: PERMISSIONS.ADMIN_ACCESS },
  { label: 'Users', icon: Users, href: '/settings/users', requiredPermission: PERMISSIONS.USERS_READ },
];

export const Route = createFileRoute('/settings')({
  component: SettingsLayout,
});

function SettingsLayout() {
  const location = useLocation();
  const hasPermission = useAuthStore((state) => state.hasPermission);

  const visibleItems = settingsNavItems.filter(item => !item.requiredPermission || hasPermission(item.requiredPermission));

  const isActive = (href: string) => {
    return location.pathname === href || location.pathname.startsWith(href + '/');
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
              <h1 className="font-semibold text-lg">Settings</h1>
              <p className="text-xs text-muted-foreground">Manage preferences</p>
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
