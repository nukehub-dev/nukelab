import { useEffect } from 'react';
import { Outlet, useNavigate, useLocation } from '@tanstack/react-router';
import { useThemeStore } from '../../stores/theme-store';
import { useSidebarStore } from '../../stores/sidebar-store';
import { Sidebar } from './sidebar';
import { AnimatePresence, motion } from 'framer-motion';
import { pageTransition } from '../../lib/animations';

export function AppShell() {
  const { isDark, isOled } = useThemeStore();
  const { isOpen, isPinned, setOpen } = useSidebarStore();
  const navigate = useNavigate();
  const location = useLocation();
  const isLoginPage = location.pathname === '/login';

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

  const sidebarWidth = isOpen ? '16rem' : '4rem';

  // Login page renders without sidebar/layout
  if (isLoginPage) {
    return (
      <AnimatePresence mode="wait">
        <motion.div
          key={location.pathname}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="min-h-screen bg-background"
        >
          <Outlet />
        </motion.div>
      </AnimatePresence>
    );
  }

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Sidebar />
      
      <motion.main
        className="flex-1 min-h-screen transition-all duration-300 ease-out"
        style={{ marginLeft: isPinned ? sidebarWidth : '4rem' }}
        onMouseEnter={() => {
          if (!isPinned && !isOpen) setOpen(true);
        }}
      >
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 20, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.98 }}
            transition={pageTransition}
            className="min-h-screen"
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </motion.main>
    </div>
  );
}
