import { useState, useEffect } from 'react';
import { Link, useLocation } from '@tanstack/react-router';
import { motion, AnimatePresence } from 'framer-motion';
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
  ChevronLeft,
  Pin,
  Sun,
  Moon,
  Monitor,
  Palette,
  Command,
  Menu,
  X,
  LogOut,
} from 'lucide-react';
import { useSidebarStore } from '../../stores/sidebar-store';
import { useThemeStore } from '../../stores/theme-store';
import { cn } from '../../lib/utils';
import { THEME_VALUES, THEME_PREVIEWS } from '../../types/theme';

import { drawerVariants } from '../../lib/animations';

interface NavItem {
  label: string;
  icon: React.ElementType;
  href: string;
  shortcut?: string;
  badge?: number;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    label: 'Platform',
    items: [
      { label: 'Dashboard', icon: LayoutDashboard, href: '/', shortcut: 'gd' },
      { label: 'Servers', icon: Server, href: '/servers', shortcut: 'gs' },
      { label: 'Environments', icon: Boxes, href: '/environments', shortcut: 'ge' },
    ],
  },
  {
    label: 'Resources',
    items: [
      { label: 'Images', icon: Image, href: '/images' },
      { label: 'Networks', icon: Network, href: '/networks' },
      { label: 'Volumes', icon: HardDrive, href: '/volumes' },
    ],
  },
  {
    label: 'Administration',
    items: [
      { label: 'Users', icon: Users, href: '/users' },
      { label: 'Settings', icon: Settings, href: '/settings' },
      { label: 'Audit Logs', icon: FileText, href: '/audit-logs' },
    ],
  },
];

export function Sidebar() {
  const location = useLocation();
  const { isOpen, isPinned, isMobileOpen, toggle, togglePin, setOpen, setMobileOpen, closeMobile } = useSidebarStore();
  const { theme, isDark, isOled, setTheme, setDarkMode, setOledMode } = useThemeStore();
  const [showThemePicker, setShowThemePicker] = useState(false);

  // Close mobile sidebar on route change
  useEffect(() => {
    closeMobile();
  }, [location.pathname, closeMobile]);

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        closeMobile();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [closeMobile]);

  const isActive = (href: string) => {
    if (href === '/') return location.pathname === '/';
    return location.pathname.startsWith(href);
  };

  const sidebarContent = (
    <>
      {/* Header */}
      <div className={cn(
        "flex items-center h-16 px-4 border-b border-sidebar-border/50",
        !isOpen && "justify-center px-2"
      )}>
        {isOpen ? (
          <>
            <div className="flex items-center gap-3 flex-1">
              <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
                <Command className="w-5 h-5 text-primary-foreground" />
              </div>
              <span className="font-bold text-lg tracking-tight">NukeLab</span>
            </div>
            <button
              onClick={togglePin}
              className={cn(
                "p-1.5 rounded-md transition-colors hover:bg-sidebar-accent",
                isPinned && "text-primary"
              )}
              title={isPinned ? 'Unpin sidebar' : 'Pin sidebar'}
            >
              <Pin className={cn("w-4 h-4", isPinned && "fill-current")} />
            </button>
            <button
              onClick={toggle}
              className="p-1.5 rounded-md transition-colors hover:bg-sidebar-accent lg:hidden"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          </>
        ) : (
          <button
            onClick={() => setOpen(true)}
            className="p-2 rounded-md transition-colors hover:bg-sidebar-accent"
          >
            <Command className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-4 px-3 space-y-6">
        {navGroups.map((group) => (
          <div key={group.label}>
            <AnimatePresence>
              {isOpen && (
                <motion.h3
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-3 mb-2"
                >
                  {group.label}
                </motion.h3>
              )}
            </AnimatePresence>
            <ul className="space-y-1">
              {group.items.map((item) => (
                <li key={item.href}>
                  <Link
                    to={item.href}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200",
                      "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                      isActive(item.href)
                        ? "bg-sidebar-accent text-sidebar-accent-foreground"
                        : "text-sidebar-foreground/80",
                      !isOpen && "justify-center px-2"
                    )}
                    title={!isOpen ? item.label : undefined}
                  >
                    <item.icon className={cn("w-5 h-5 shrink-0", isActive(item.href) && "text-primary")} />
                    <AnimatePresence>
                      {isOpen && (
                        <motion.span
                          initial={{ opacity: 0, width: 0 }}
                          animate={{ opacity: 1, width: 'auto' }}
                          exit={{ opacity: 0, width: 0 }}
                          className="truncate flex-1"
                        >
                          {item.label}
                        </motion.span>
                      )}
                    </AnimatePresence>
                    {item.badge && isOpen && (
                      <span className="bg-primary text-primary-foreground text-xs px-2 py-0.5 rounded-full">
                        {item.badge}
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {/* Theme Controls */}
      <div className={cn(
        "border-t border-sidebar-border/50 p-4 space-y-3",
        !isOpen && "px-2"
      )}>
        <AnimatePresence>
          {isOpen ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="space-y-3"
            >
              {/* Dark mode toggle */}
              <div className="flex items-center justify-between">
                <span className="text-sm text-sidebar-foreground/80">Theme</span>
                <div className="flex items-center gap-1 bg-sidebar-accent rounded-lg p-1">
                  <button
                    onClick={() => setDarkMode(true)}
                    className={cn(
                      "p-1.5 rounded-md transition-colors",
                      isDark && !isOled && "bg-background text-foreground"
                    )}
                  >
                    <Moon className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => setDarkMode(false)}
                    className={cn(
                      "p-1.5 rounded-md transition-colors",
                      !isDark && "bg-background text-foreground"
                    )}
                  >
                    <Sun className="w-4 h-4" />
                  </button>
                  <button
                    onClick={() => {
                      setDarkMode(true);
                      setOledMode(!isOled);
                    }}
                    className={cn(
                      "p-1.5 rounded-md transition-colors",
                      isOled && "bg-background text-foreground"
                    )}
                  >
                    <Monitor className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Theme picker */}
              {/* Logout */}
              <button
                onClick={() => {
                  localStorage.removeItem('nukelab-token');
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

                <AnimatePresence>
                  {showThemePicker && (
                    <motion.div
                      initial={{ opacity: 0, y: 10, scale: 0.95 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 10, scale: 0.95 }}
                      className="absolute bottom-full left-0 right-0 mb-2 p-3 bg-popover border border-border rounded-xl shadow-lg z-50"
                    >
                      <div className="grid grid-cols-4 gap-2">
                        {THEME_VALUES.map((t) => (
                          <button
                            key={t}
                            onClick={() => {
                              setTheme(t);
                              setShowThemePicker(false);
                            }}
                            className={cn(
                              "p-2 rounded-lg border-2 transition-all",
                              theme === t
                                ? "border-primary"
                                : "border-transparent hover:border-border"
                            )}
                            title={t}
                          >
                            <div
                              className="w-full h-6 rounded-md mb-1"
                              style={{ backgroundColor: THEME_PREVIEWS[t].dark.primary }}
                            />
                            <span className="text-[10px] capitalize block text-center">{t}</span>
                          </button>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </motion.div>
          ) : (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-2"
            >
              <button
                onClick={() => setDarkMode(!isDark)}
                className="p-2 rounded-lg hover:bg-sidebar-accent transition-colors"
                title={isDark ? 'Light mode' : 'Dark mode'}
              >
                {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              </button>
              <button
                onClick={() => {
                  const idx = THEME_VALUES.indexOf(theme);
                  const next = THEME_VALUES[(idx + 1) % THEME_VALUES.length];
                  setTheme(next);
                }}
                className="p-2 rounded-lg hover:bg-sidebar-accent transition-colors"
                title="Next theme"
              >
                <Palette className="w-4 h-4" />
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </>
  );

  return (
    <>
      {/* Desktop Sidebar */}
      <motion.aside
        className={cn(
          "fixed top-0 left-0 h-screen z-40 hidden lg:flex flex-col",
          "bg-sidebar/80 backdrop-blur-xl border-r border-sidebar-border/50",
          !isPinned && "hover:w-64"
        )}
        initial={false}
        animate={{ width: isOpen ? 256 : 64 }}
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
        onMouseEnter={() => {
          if (!isPinned) setOpen(true);
        }}
        onMouseLeave={() => {
          if (!isPinned) setOpen(false);
        }}
      >
        {sidebarContent}
      </motion.aside>

      {/* Mobile Toggle */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed top-4 left-4 z-40 lg:hidden p-2 rounded-lg bg-sidebar/80 backdrop-blur-xl border border-sidebar-border/50"
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Mobile Sidebar */}
      <AnimatePresence>
        {isMobileOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/50 z-40 lg:hidden backdrop-blur-sm"
              onClick={closeMobile}
            />
            <motion.aside
              variants={drawerVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="fixed top-0 left-0 h-screen w-64 z-50 lg:hidden flex flex-col bg-sidebar border-r border-sidebar-border/50"
            >
              <div className="flex items-center justify-end h-16 px-4 border-b border-sidebar-border/50">
                <button
                  onClick={closeMobile}
                  className="p-2 rounded-md transition-colors hover:bg-sidebar-accent"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              {sidebarContent}
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
