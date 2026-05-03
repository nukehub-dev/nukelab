import { useEffect } from 'react';
import { Outlet, useNavigate, useLocation } from '@tanstack/react-router';
import { useThemeStore } from '../../stores/theme-store';
import { useSidebarStore } from '../../stores/sidebar-store';
import { useCurrentUser } from '../../hooks/use-current-user';
import { useGlobalShortcuts } from '../../hooks/use-keyboard-shortcuts';
import { Sidebar } from './sidebar';
import { ToastProvider } from '../feedback/toast';
import { ShortcutsModal } from '../feedback/shortcuts-modal';
import { AmbientBackground } from '../animations/ambient-background';
import { AnimatePresence, motion } from 'framer-motion';
import { cn } from '../../lib/utils';

export function AppShell() {
  const { isDark, isOled } = useThemeStore();
  const { isOpen } = useSidebarStore();
  const navigate = useNavigate();
  const location = useLocation();
  const isLoginPage = location.pathname === '/login';
  const isDashboard = location.pathname === '/';

  // Global keyboard shortcuts
  useGlobalShortcuts();

  // Fetch current user when authenticated (skip on login page)
  const hasToken = !!localStorage.getItem('nukelab-token');
  useCurrentUser({ enabled: hasToken && !isLoginPage });

  useEffect(() => {
    // Initialize theme on mount
    document.documentElement.classList.toggle('dark', isDark);
    if (!isDark) document.documentElement.classList.add('light');
    document.documentElement.classList.toggle('oled', isOled);
  }, [isDark, isOled]);

  useEffect(() => {
    // Check auth — skip on login page
    if (isLoginPage) return;

    const token = localStorage.getItem('nukelab-token');
    if (!token) {
      navigate({ to: '/login' });
    }
  }, [isLoginPage, navigate]);

  // Login page renders without sidebar/layout
  if (isLoginPage) {
    return (
      <>
        <ToastProvider />
        <ShortcutsModal />
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
            className="min-h-screen bg-background relative z-10"
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </>
    );
  }

  return (
    <>
      <AmbientBackground variant={isDashboard ? 'dashboard' : 'default'} />
      <ToastProvider />
      <ShortcutsModal />

      <div className="flex min-h-screen bg-background text-foreground relative z-10">
        <Sidebar />

        <motion.main
          className={cn(
            'flex-1 min-h-screen transition-all duration-300 ease-out overflow-x-hidden',
            'pl-0 lg:pl-[5.5rem]',
            isOpen && 'lg:pl-[17rem]'
          )}
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 20, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -20, scale: 0.98 }}
              transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
              className="min-h-screen"
            >
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </motion.main>
      </div>
    </>
  );
}
