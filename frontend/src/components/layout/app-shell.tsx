import { useEffect } from 'react';
import { Outlet } from '@tanstack/react-router';
import { useThemeStore } from '../../stores/theme-store';
import { useSidebarStore } from '../../stores/sidebar-store';
import { Sidebar } from './sidebar';
import { AnimatePresence, motion } from 'framer-motion';
import { pageTransition } from '../../lib/animations';

export function AppShell() {
  const { isDark, isOled } = useThemeStore();
  const { isOpen, isPinned, setOpen } = useSidebarStore();

  useEffect(() => {
    // Initialize theme on mount
    document.documentElement.classList.toggle('dark', isDark);
    if (!isDark) document.documentElement.classList.add('light');
    document.documentElement.classList.toggle('oled', isOled);
  }, [isDark, isOled]);

  const sidebarWidth = isOpen ? '16rem' : '4rem';

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
