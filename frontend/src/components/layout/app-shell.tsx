import { useEffect } from 'react'
import { Outlet, useNavigate, useLocation } from '@tanstack/react-router'
import { AlertTriangle } from 'lucide-react'
import { useThemeStore } from '../../stores/theme-store'
import { useSidebarStore } from '../../stores/sidebar-store'
import { useCurrentUser } from '../../hooks/use-current-user'
import { useGlobalShortcuts } from '../../hooks/use-keyboard-shortcuts'
import { useFavicon } from '../../lib/favicon'
import { useNotificationToasts } from '../notifications/notification-toast-provider'
import { useHealth } from '../../hooks/use-health'
import { Sidebar } from './sidebar'
import { ToastProvider } from '../feedback/toast'
import { ShortcutsModal } from '../feedback/shortcuts-modal'
import { AmbientBackground } from '../animations/ambient-background'
import { ErrorBoundary } from '../error-boundary'
import { AnimatePresence, motion } from 'framer-motion'
import { cn } from '../../lib/utils'

export function AppShell() {
  const { isDark, isOled } = useThemeStore()
  const { isOpen } = useSidebarStore()
  const navigate = useNavigate()
  const location = useLocation()
  const isLoginPage = location.pathname === '/login'
  const isGatewayPage = location.pathname.startsWith('/user/')
  const isDashboard = location.pathname === '/'
  const { data: health } = useHealth()
  const isMaintenance = health?.status === 'maintenance'

  // Dynamic favicon with theme color
  useFavicon()

  // Global keyboard shortcuts
  useGlobalShortcuts()

  // Fetch current user when authenticated (skip on login page)
  const hasToken = !!localStorage.getItem('nukelab-token')
  useCurrentUser({ enabled: hasToken && !isLoginPage })

  // Global notification toast watcher
  useNotificationToasts()

  useEffect(() => {
    // Initialize theme on mount
    document.documentElement.classList.toggle('dark', isDark)
    if (!isDark) document.documentElement.classList.add('light')
    document.documentElement.classList.toggle('oled', isOled)
  }, [isDark, isOled])

  useEffect(() => {
    // Check auth — skip on login page
    if (isLoginPage) return

    const token = localStorage.getItem('nukelab-token')
    if (!token) {
      navigate({ to: '/login' })
    }
  }, [isLoginPage, navigate])

  // Login and gateway pages render without sidebar/layout
  if (isLoginPage || isGatewayPage) {
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
    )
  }

  return (
    <>
      <AmbientBackground variant={isDashboard ? 'dashboard' : 'default'} />
      <ToastProvider />
      <ShortcutsModal />

      {/* Maintenance banner */}
      {isMaintenance && (
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className={cn(
            'fixed top-0 z-[60] bg-amber-100 dark:bg-amber-500/10 border-b border-amber-300 dark:border-amber-500/20 backdrop-blur-sm',
            // Mobile: full width
            'left-0 right-0',
            // Desktop: respect sidebar width, curved left edge
            'lg:rounded-bl-xl',
            isOpen ? 'lg:left-[17rem]' : 'lg:left-[5.5rem]'
          )}
        >
          <div className="flex items-center justify-center gap-2 px-4 py-2 text-amber-800 dark:text-amber-400 text-sm">
            <AlertTriangle className="w-4 h-4" />
            <span className="font-medium">{health?.message || 'System under maintenance'}</span>
          </div>
        </motion.div>
      )}

      <div
        className={cn(
          'flex min-h-screen bg-background text-foreground relative z-10',
          isMaintenance && 'pt-9'
        )}
      >
        <Sidebar />

        <motion.main
          className={cn(
            'flex-1 min-h-screen transition-all duration-300 ease-out overflow-x-hidden',
            'pl-0 lg:pl-[5.5rem] pb-24 lg:pb-0',
            isOpen && 'lg:pl-[17rem]'
          )}
        >
          <ErrorBoundary>
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0, y: 20, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -20, scale: 0.98 }}
                transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
              >
                <Outlet />
              </motion.div>
            </AnimatePresence>
          </ErrorBoundary>
        </motion.main>
      </div>
    </>
  )
}
