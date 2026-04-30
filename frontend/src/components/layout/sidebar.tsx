import { useState } from 'react';
import { Link, useLocation } from '@tanstack/react-router';

import {
  LayoutDashboard,
  Server,
  Boxes,
  Image,
  Network,
  HardDrive,
  Users,
  Settings,
  FileText,
  CreditCard,
  Pin,
  Sun,
  Moon,
  Monitor,
  Palette,
  Command,
  LogOut,
  MoreHorizontal,
} from 'lucide-react';
import { useSidebarStore } from '../../stores/sidebar-store';
import { useThemeStore } from '../../stores/theme-store';
import { useAuthStore } from '../../stores/auth-store';
import { cn } from '../../lib/utils';
import { THEME_VALUES, THEME_PREVIEWS } from '../../types/theme';

interface NavItem {
  label: string;
  icon: React.ElementType;
  href: string;
  requiredRole?: 'admin' | 'moderator' | 'support' | 'user';
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    label: 'Platform',
    items: [
      { label: 'Dashboard', icon: LayoutDashboard, href: '/' },
      { label: 'Servers', icon: Server, href: '/servers' },
      { label: 'Environments', icon: Boxes, href: '/environments' },
    ],
  },
  {
    label: 'Resources',
    items: [
      { label: 'Images', icon: Image, href: '/images' },
      { label: 'Networks', icon: Network, href: '/networks' },
      { label: 'Volumes', icon: HardDrive, href: '/volumes' },
      { label: 'Plans', icon: CreditCard, href: '/plans' },
    ],
  },
  {
    label: 'Administration',
    items: [
      { label: 'Users', icon: Users, href: '/users', requiredRole: 'moderator' },
      { label: 'Settings', icon: Settings, href: '/settings', requiredRole: 'admin' },
      { label: 'Audit Logs', icon: FileText, href: '/audit-logs', requiredRole: 'admin' },
    ],
  },
];

const dockItems = [
  { label: 'Dashboard', icon: LayoutDashboard, href: '/' },
  { label: 'Servers', icon: Server, href: '/servers' },
  { label: 'Environments', icon: Boxes, href: '/environments' },
  { label: 'Plans', icon: CreditCard, href: '/plans' },
];

function getMinimumRoleLevel(role: string): number {
  const levels: Record<string, number> = {
    guest: 0,
    user: 1,
    support: 2,
    moderator: 3,
    admin: 4,
    super_admin: 5,
  };
  return levels[role] ?? 0;
}

function canAccessItem(item: NavItem, userRole: string): boolean {
  if (!item.requiredRole) return true;
  const required = getMinimumRoleLevel(item.requiredRole);
  const current = getMinimumRoleLevel(userRole);
  return current >= required;
}

export function Sidebar() {
  const location = useLocation();
  const { isOpen, isPinned, togglePin, setOpen } = useSidebarStore();
  const { theme, isDark, isOled, setTheme, setDarkMode, setOledMode } = useThemeStore();
  const user = useAuthStore((state) => state.user);
  const [showMore, setShowMore] = useState(false);
  const [showThemePicker, setShowThemePicker] = useState(false);

  const userRole = user?.role ?? 'guest';

  const isActive = (href: string) => {
    if (href === '/') return location.pathname === '/';
    return location.pathname.startsWith(href);
  };

  const visibleNavGroups = navGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => canAccessItem(item, userRole)),
    }))
    .filter((group) => group.items.length > 0);

  const visibleDockItems = dockItems.filter((item) => canAccessItem(item, userRole));

  return (
    <>
      {/* Desktop Sidebar */}
      <aside
        className={cn(
          "fixed top-3 left-3 bottom-3 z-40 hidden lg:flex flex-col",
          "bg-sidebar/95 backdrop-blur-xl rounded-2xl",
          "border border-sidebar-border/50 shadow-2xl shadow-black/20",
          "transition-[width] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] overflow-hidden"
        )}
        style={{ width: isOpen ? 256 : 64 }}
        onMouseEnter={() => { if (!isPinned) setOpen(true); }}
        onMouseLeave={() => { if (!isPinned) setOpen(false); }}
      >
        {/* Header */}
        <div className="flex items-center h-14 px-4 border-b border-sidebar-border/50 shrink-0">
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center shrink-0">
              <Command className="w-5 h-5 text-primary-foreground" />
            </div>
            <span 
              className="font-bold text-lg tracking-tight truncate whitespace-nowrap overflow-hidden transition-all duration-300"
              style={{ maxWidth: isOpen ? 200 : 0, opacity: isOpen ? 1 : 0 }}
            >
              NukeLab
            </span>
          </div>
          <button
            onClick={togglePin}
            className="p-1.5 rounded-md transition-colors hover:bg-sidebar-accent shrink-0"
            title={isPinned ? 'Unpin sidebar' : 'Pin sidebar'}
            style={{ marginLeft: isOpen ? 8 : 0, opacity: isOpen ? 1 : 0, transition: 'all 0.3s ease' }}
          >
            <Pin className={cn("w-4 h-4", isPinned && "fill-current")} />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-4 space-y-6 scrollbar-hide">
          {visibleNavGroups.map((group) => (
            <div key={group.label}>
              <h3 
                className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-3 mb-2 whitespace-nowrap overflow-hidden transition-all duration-300"
                style={{ maxHeight: isOpen ? 40 : 0, opacity: isOpen ? 1 : 0, marginBottom: isOpen ? 8 : 0 }}
              >
                {group.label}
              </h3>
              <ul className="space-y-1">
                {group.items.map((item) => (
                  <li key={item.href}>
                    <Link
                      to={item.href}
                      className={cn(
                        "flex items-center py-2 rounded-lg text-sm font-medium transition-all duration-300",
                        "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                        isActive(item.href)
                          ? "bg-sidebar-accent text-sidebar-accent-foreground"
                          : "text-sidebar-foreground/80"
                      )}
                      title={!isOpen ? item.label : undefined}
                      style={{
                        paddingLeft: isOpen ? 11 : 11,
                        paddingRight: isOpen ? 11 : 11,
                        marginLeft: isOpen ? 4 : 10,
                        marginRight: isOpen ? 4 : 10,
                      }}
                    >
                      <item.icon className={cn("w-5 h-5 shrink-0", isActive(item.href) && "text-primary")} />
                      <span
                        className="truncate whitespace-nowrap overflow-hidden transition-all duration-300"
                        style={{ maxWidth: isOpen ? 200 : 0, opacity: isOpen ? 1 : 0, marginLeft: isOpen ? 12 : 0 }}
                      >
                        {item.label}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="border-t border-sidebar-border/50 p-4 shrink-0">
          <div 
            className="space-y-3 transition-all duration-300"
            style={{ maxHeight: isOpen ? 300 : 0, opacity: isOpen ? 1 : 0, overflow: 'hidden' }}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm text-sidebar-foreground/80">Theme</span>
              <div className="flex items-center gap-1 bg-sidebar-accent rounded-lg p-1">
                <button onClick={() => setDarkMode(true)} className={cn("p-1.5 rounded-md transition-colors", isDark && !isOled && "bg-background text-foreground")}>
                  <Moon className="w-4 h-4" />
                </button>
                <button onClick={() => setDarkMode(false)} className={cn("p-1.5 rounded-md transition-colors", !isDark && "bg-background text-foreground")}>
                  <Sun className="w-4 h-4" />
                </button>
                <button onClick={() => { setDarkMode(true); setOledMode(!isOled); }} className={cn("p-1.5 rounded-md transition-colors", isOled && "bg-background text-foreground")}>
                  <Monitor className="w-4 h-4" />
                </button>
              </div>
            </div>

            <button
              onClick={() => {
                localStorage.removeItem('nukelab-token');
                document.cookie = 'nukelab_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
                window.location.href = '/login';
              }}
              className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm hover:bg-sidebar-accent transition-colors text-red-400"
            >
              <LogOut className="w-4 h-4" />
              <span className="flex-1 text-left">Log Out</span>
            </button>

            <div className="relative">
              <button
                onClick={() => setShowThemePicker(!showThemePicker)}
                className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm hover:bg-sidebar-accent transition-colors"
              >
                <Palette className="w-4 h-4" />
                <span className="flex-1 text-left capitalize">{theme} Theme</span>
              </button>
              {showThemePicker && (
                <div className="absolute bottom-full left-0 right-0 mb-2 p-3 bg-popover border border-border rounded-xl shadow-lg z-50">
                  <div className="grid grid-cols-4 gap-2">
                    {THEME_VALUES.map((t) => (
                      <button
                        key={t}
                        onClick={() => { setTheme(t); setShowThemePicker(false); }}
                        className={cn("p-2 rounded-lg border-2 transition-all", theme === t ? "border-primary" : "border-transparent hover:border-border")}
                      >
                        <div className="w-full h-6 rounded-md mb-1" style={{ backgroundColor: THEME_PREVIEWS[t].dark.primary }} />
                        <span className="text-[10px] capitalize block text-center">{t}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div 
            className="flex flex-col items-center gap-2 transition-all duration-300"
            style={{ maxHeight: !isOpen ? 100 : 0, opacity: !isOpen ? 1 : 0, overflow: 'hidden' }}
          >
            <button onClick={() => setDarkMode(!isDark)} className="p-2 rounded-lg hover:bg-sidebar-accent transition-colors">
              {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
            <button onClick={() => { const idx = THEME_VALUES.indexOf(theme); setTheme(THEME_VALUES[(idx + 1) % THEME_VALUES.length]); }} className="p-2 rounded-lg hover:bg-sidebar-accent transition-colors">
              <Palette className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Mobile Bottom Dock */}
      <nav className="fixed bottom-4 left-4 right-4 z-40 lg:hidden">
        <div className="bg-background/80 backdrop-blur-xl border border-border/50 rounded-2xl shadow-lg shadow-black/20 px-2 py-2">
          <div className="flex items-center justify-around">
            {visibleDockItems.map((item) => (
              <Link
                key={item.href}
                to={item.href}
                className={cn(
                  "flex flex-col items-center gap-1 px-3 py-2 rounded-xl transition-all duration-200",
                  isActive(item.href)
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <item.icon className="w-5 h-5" />
                <span className="text-[10px] font-medium">{item.label}</span>
              </Link>
            ))}
            <button
              onClick={() => setShowMore(true)}
              className={cn(
                "flex flex-col items-center gap-1 px-3 py-2 rounded-xl transition-all duration-200",
                showMore ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
              )}
            >
              <MoreHorizontal className="w-5 h-5" />
              <span className="text-[10px] font-medium">More</span>
            </button>
          </div>
        </div>
      </nav>

      {/* Mobile More Menu */}
      {showMore && (
        <>
          <div
            className="fixed inset-0 bg-black/60 z-50 lg:hidden backdrop-blur-sm"
            onClick={() => setShowMore(false)}
          />
          <div
            className="fixed bottom-0 left-0 right-0 z-[60] lg:hidden"
          >
            <div className="bg-background/95 backdrop-blur-xl rounded-t-3xl border border-border/50 shadow-2xl">
              <div className="flex justify-center pt-3 pb-1">
                <div className="w-12 h-1.5 rounded-full bg-muted-foreground/30" />
              </div>
              
              <div className="px-6 py-4 space-y-6 max-h-[60vh] overflow-y-auto scrollbar-hide">
                {visibleNavGroups.map((group) => (
                  <div key={group.label}>
                    <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-3 mb-3">
                      {group.label}
                    </h3>
                    <div className="space-y-1">
                      {group.items.map((item) => (
                        <Link
                          key={item.href}
                          to={item.href}
                          onClick={() => setShowMore(false)}
                          className={cn(
                            "flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200",
                            isActive(item.href)
                              ? "bg-muted text-foreground shadow-sm"
                              : "text-foreground/80 hover:bg-muted/50"
                          )}
                        >
                          <item.icon className={cn("w-5 h-5 shrink-0", isActive(item.href) && "text-primary")} />
                          <span>{item.label}</span>
                        </Link>
                      ))}
                    </div>
                  </div>
                ))}
                
                <div className="pt-4 border-t border-border/50 space-y-3">
                  <div className="flex items-center justify-between px-3">
                    <span className="text-sm text-muted-foreground">Theme</span>
                    <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
                      <button onClick={() => setDarkMode(true)} className={cn("p-1.5 rounded-md transition-colors", isDark && !isOled && "bg-background text-foreground")}><Moon className="w-4 h-4" /></button>
                      <button onClick={() => setDarkMode(false)} className={cn("p-1.5 rounded-md transition-colors", !isDark && "bg-background text-foreground")}><Sun className="w-4 h-4" /></button>
                      <button onClick={() => { setDarkMode(true); setOledMode(!isOled); }} className={cn("p-1.5 rounded-md transition-colors", isOled && "bg-background text-foreground")}><Monitor className="w-4 h-4" /></button>
                    </div>
                  </div>
                  
                  <button
                    onClick={() => {
                      localStorage.removeItem('nukelab-token');
                      document.cookie = 'nukelab_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
                      window.location.href = '/login';
                    }}
                    className="flex items-center gap-2 w-full px-4 py-3 rounded-xl text-sm hover:bg-muted transition-colors text-red-400"
                  >
                    <LogOut className="w-4 h-4" />
                    <span>Log Out</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      <style>{`
        .scrollbar-hide {
          -ms-overflow-style: none;
          scrollbar-width: none;
        }
        .scrollbar-hide::-webkit-scrollbar {
          display: none;
        }
      `}</style>
    </>
  );
}