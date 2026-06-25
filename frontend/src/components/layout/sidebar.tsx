import { useState } from 'react'
import { Link, useLocation } from '@tanstack/react-router'
import { AnimatePresence, motion } from 'framer-motion'

import {
  LayoutDashboard,
  Server,
  Boxes,
  HardDrive,
  Settings,
  CreditCard,
  Activity,
  Shield,
  FolderOpen,
  Sun,
  Moon,
  Monitor,
  LogOut,
  Pin,
  ArrowLeftFromLine,
  ArrowRightFromLine,
  UserCircle,
  Clock,
} from 'lucide-react'
import { NukeLabLogo } from '../logo'
import { useSidebarStore } from '../../stores/sidebar-store'
import { useThemeStore } from '../../stores/theme-store'
import { useAuthStore, PERMISSIONS } from '../../stores/auth-store'
import { logout } from '../../hooks/use-auth'
import { cn } from '../../lib/utils'
import { Tooltip } from '../ui/tooltip'
import { NotificationCenter } from '../notifications/notification-center'

interface NavItem {
  label: string
  icon: React.ElementType
  href: string
  requiredPermission?: string
}

interface NavGroup {
  label: string
  items: NavItem[]
}

const navGroups: NavGroup[] = [
  {
    label: 'Platform',
    items: [
      { label: 'Dashboard', icon: LayoutDashboard, href: '/' },
      { label: 'Servers', icon: Server, href: '/servers' },
      { label: 'Usage', icon: Activity, href: '/usage' },
      { label: 'Activity', icon: Clock, href: '/activity' },
    ],
  },
  {
    label: 'Resources',
    items: [
      {
        label: 'Environments',
        icon: Boxes,
        href: '/environments',
        requiredPermission: PERMISSIONS.ENVIRONMENT_READ,
      },
      { label: 'Volumes', icon: HardDrive, href: '/volumes' },
      { label: 'Workspaces', icon: FolderOpen, href: '/workspaces' },
      {
        label: 'Plans',
        icon: CreditCard,
        href: '/plans',
        requiredPermission: PERMISSIONS.PLAN_READ,
      },
    ],
  },
  {
    label: 'System',
    items: [
      { label: 'Settings', icon: Settings, href: '/settings' },
      { label: 'Administration', icon: Shield, href: '/admin' },
    ],
  },
]

const dockItems = [
  { label: 'Dashboard', icon: LayoutDashboard, href: '/' },
  { label: 'Servers', icon: Server, href: '/servers' },
  { label: 'Workspaces', icon: FolderOpen, href: '/workspaces' },
]

const leftDockItems = [
  { label: 'Dashboard', icon: LayoutDashboard, href: '/' },
  { label: 'Servers', icon: Server, href: '/servers' },
]

const rightDockItems = [{ label: 'Workspaces', icon: FolderOpen, href: '/workspaces' }]

function canAccessItem(
  item: NavItem,
  hasPermission: (p: string) => boolean,
  canAccessAdminPanel: () => boolean
): boolean {
  if (!item.requiredPermission) {
    // Administration link is special - check any admin permission
    if (item.href === '/admin') return canAccessAdminPanel()
    return true
  }
  return hasPermission(item.requiredPermission)
}

export function Sidebar() {
  const location = useLocation()
  const { isOpen, mode, setOpen, setMode } = useSidebarStore()
  const { isDark, isOled, setDarkMode, setOledMode } = useThemeStore()
  const [showMore, setShowMore] = useState(false)

  const hasPermission = useAuthStore((state) => state.hasPermission)
  const canAccessAdmin = useAuthStore((state) => state.canAccessAdmin)
  const user = useAuthStore((state) => state.user)
  const isAuto = mode === 'auto'

  const handleLogout = () => {
    logout()
  }

  const displayName =
    user?.first_name && user?.last_name
      ? `${user.first_name} ${user.last_name}`
      : user?.display_name || user?.username || 'User'
  const initials = displayName.charAt(0).toUpperCase()
  const avatarUrl = user?.avatar_url

  const isActive = (href: string) => {
    if (href === '/') return location.pathname === '/'
    return location.pathname.startsWith(href)
  }

  const visibleNavGroups = navGroups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => canAccessItem(item, hasPermission, canAccessAdmin)),
    }))
    .filter((group) => group.items.length > 0)

  const visibleDockItems = dockItems.filter((item) =>
    canAccessItem(item, hasPermission, canAccessAdmin)
  )

  return (
    <>
      {/* Desktop Sidebar */}
      <aside
        className={cn(
          'fixed top-3 left-3 bottom-3 z-40 hidden lg:flex flex-col',
          'bg-sidebar/95 backdrop-blur-xl rounded-2xl',
          'border border-sidebar-border/50 shadow-2xl shadow-black/20',
          'transition-[width] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]'
        )}
        style={{ width: isOpen ? 256 : 64 }}
        onMouseEnter={() => {
          if (isAuto) setOpen(true)
        }}
        onMouseLeave={() => {
          if (isAuto) setOpen(false)
        }}
      >
        {/* Header */}
        <div className="flex items-center h-14 px-4 border-b border-sidebar-border/50 shrink-0 gap-3">
          {!isOpen ? (
            <Tooltip
              content={
                mode === 'collapsed'
                  ? 'Enable auto-expand'
                  : mode === 'auto'
                    ? 'Expand sidebar'
                    : 'Collapse sidebar'
              }
              position="right"
            >
              <button
                onClick={() => {
                  const modes = ['collapsed', 'auto', 'expanded'] as const
                  const nextIndex = (modes.indexOf(mode) + 1) % modes.length
                  setMode(modes[nextIndex])
                }}
                className="w-8 h-8 flex items-center justify-center shrink-0 rounded-lg transition-colors relative group hover:bg-sidebar-accent cursor-pointer"
              >
                <span className="absolute inset-0 flex items-center justify-center group-hover:opacity-0 transition-opacity">
                  <NukeLabLogo size={32} className="text-primary" />
                </span>
                <span className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                  {mode === 'expanded' && <ArrowLeftFromLine className="w-5 h-5 text-primary" />}
                  {mode === 'auto' && <Pin className="w-5 h-5 text-primary" />}
                  {mode === 'collapsed' && <ArrowRightFromLine className="w-5 h-5 text-primary" />}
                </span>
              </button>
            </Tooltip>
          ) : (
            <div className="w-8 h-8 flex items-center justify-center shrink-0">
              <NukeLabLogo size={32} className="text-primary" />
            </div>
          )}
          <span
            className="font-bold text-lg tracking-tight truncate whitespace-nowrap overflow-hidden transition-all duration-300 flex-1"
            style={{ maxWidth: isOpen ? 200 : 0, opacity: isOpen ? 1 : 0 }}
          >
            NukeLab
          </span>
          <Tooltip
            content={
              mode === 'expanded'
                ? 'Collapse sidebar'
                : mode === 'auto'
                  ? 'Expand sidebar'
                  : 'Enable auto-expand'
            }
            position="right"
          >
            <button
              onClick={() => {
                const modes = ['collapsed', 'auto', 'expanded'] as const
                const nextIndex = (modes.indexOf(mode) + 1) % modes.length
                setMode(modes[nextIndex])
              }}
              className="p-1.5 rounded-md transition-colors hover:bg-sidebar-accent shrink-0"
              style={{ opacity: isOpen ? 1 : 0, transition: 'all 0.3s ease' }}
            >
              {mode === 'expanded' && <ArrowLeftFromLine className="w-4 h-4" />}
              {mode === 'auto' && <Pin className="w-4 h-4" />}
              {mode === 'collapsed' && <ArrowRightFromLine className="w-4 h-4" />}
            </button>
          </Tooltip>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-4 space-y-6 scrollbar-hide">
          {visibleNavGroups.map((group) => (
            <div key={group.label}>
              <h3
                className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-3 mb-2 whitespace-nowrap overflow-hidden transition-all duration-300"
                style={{
                  maxHeight: isOpen ? 40 : 0,
                  opacity: isOpen ? 1 : 0,
                  marginBottom: isOpen ? 8 : 0,
                }}
              >
                {group.label}
              </h3>
              <ul className="space-y-1">
                {group.items.map((item) => (
                  <li key={item.href}>
                    {isOpen ? (
                      <Link
                        to={item.href}
                        className={cn(
                          'flex items-center py-2 rounded-lg text-sm font-medium transition-all duration-300',
                          'hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                          isActive(item.href)
                            ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                            : 'text-sidebar-foreground/80'
                        )}
                        style={{
                          paddingLeft: 11,
                          paddingRight: 11,
                          marginLeft: 4,
                          marginRight: 4,
                        }}
                      >
                        <item.icon
                          className={cn(
                            'w-5 h-5 shrink-0',
                            item.label === 'Environments' && 'opacity-80',
                            isActive(item.href) && 'text-primary'
                          )}
                        />
                        <span
                          className="truncate whitespace-nowrap overflow-hidden transition-all duration-300"
                          style={{ maxWidth: 200, opacity: 1, marginLeft: 12 }}
                        >
                          {item.label}
                        </span>
                      </Link>
                    ) : (
                      <Tooltip content={item.label} position="right">
                        <Link
                          to={item.href}
                          className={cn(
                            'flex items-center py-2 rounded-lg text-sm font-medium transition-all duration-300',
                            'hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                            isActive(item.href)
                              ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                              : 'text-sidebar-foreground/80'
                          )}
                          style={{
                            paddingLeft: 11,
                            paddingRight: 11,
                            marginLeft: 10,
                            marginRight: 10,
                          }}
                        >
                          <item.icon
                            className={cn(
                              'w-5 h-5 shrink-0',
                              item.label === 'Environments' && 'opacity-80',
                              isActive(item.href) && 'text-primary'
                            )}
                          />
                        </Link>
                      </Tooltip>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="border-t border-sidebar-border/50 py-3 shrink-0">
          {/* Expanded footer */}
          <div
            className="space-y-3 transition-all duration-300"
            style={{ maxHeight: isOpen ? 300 : 0, opacity: isOpen ? 1 : 0, overflow: 'hidden' }}
          >
            {/* User */}
            <Link
              to="/settings/profile"
              className={cn(
                'flex items-center py-2 rounded-lg text-sm font-medium transition-all duration-300',
                'hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
                isActive('/settings/profile')
                  ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                  : 'text-sidebar-foreground/80'
              )}
              style={{ paddingLeft: 11, paddingRight: 11, marginLeft: 4, marginRight: 4 }}
            >
              {avatarUrl ? (
                <img
                  src={avatarUrl}
                  alt={displayName}
                  className={cn(
                    'w-5 h-5 rounded-full object-cover shrink-0',
                    isActive('/settings/profile') && 'ring-2 ring-primary/50'
                  )}
                />
              ) : (
                <div
                  className={cn(
                    'w-5 h-5 rounded-full bg-primary/20 flex items-center justify-center text-[10px] font-bold text-primary shrink-0',
                    isActive('/settings/profile') && 'bg-primary/30'
                  )}
                >
                  {initials}
                </div>
              )}
              <div className="min-w-0" style={{ marginLeft: 12 }}>
                <p className="text-sm font-medium truncate leading-tight">{displayName}</p>
                <p className="text-xs text-muted-foreground truncate">
                  @{user?.username || 'user'}
                </p>
              </div>
            </Link>

            {/* Theme + Actions */}
            <div className="flex items-center justify-between gap-2 mx-1">
              <div className="flex items-center gap-1 bg-sidebar-accent rounded-lg p-1">
                <button
                  onClick={() => setDarkMode(true)}
                  className={cn(
                    'p-1.5 rounded-md transition-colors',
                    isDark && !isOled && 'bg-background text-foreground'
                  )}
                >
                  <Moon className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setDarkMode(false)}
                  className={cn(
                    'p-1.5 rounded-md transition-colors',
                    !isDark && 'bg-background text-foreground'
                  )}
                >
                  <Sun className="w-4 h-4" />
                </button>
                <button
                  onClick={() => {
                    setDarkMode(true)
                    setOledMode(!isOled)
                  }}
                  className={cn(
                    'p-1.5 rounded-md transition-colors',
                    isOled && 'bg-background text-foreground'
                  )}
                >
                  <Monitor className="w-4 h-4" />
                </button>
              </div>
              <div className="flex items-center gap-1">
                <NotificationCenter />
                <Tooltip content="Log Out" position="right">
                  <button
                    onClick={handleLogout}
                    className="p-2 rounded-lg hover:bg-sidebar-accent transition-colors text-destructive"
                  >
                    <LogOut className="w-4 h-4" />
                  </button>
                </Tooltip>
              </div>
            </div>
          </div>

          {/* Collapsed footer */}
          <div
            className="flex flex-col items-center gap-2 transition-all duration-300 py-1"
            style={{ maxHeight: !isOpen ? 160 : 0, opacity: !isOpen ? 1 : 0, overflow: 'hidden' }}
          >
            <div className="p-0.5">
              <NotificationCenter />
            </div>
            <Tooltip
              content={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
              position="right"
            >
              <button
                onClick={() => setDarkMode(!isDark)}
                className="p-2 rounded-lg hover:bg-sidebar-accent transition-colors"
              >
                {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              </button>
            </Tooltip>
            <Tooltip content="Profile" position="right">
              <Link
                to="/settings/profile"
                className="rounded-lg hover:bg-sidebar-accent transition-colors"
              >
                {avatarUrl ? (
                  <img
                    src={avatarUrl}
                    alt={displayName}
                    className="w-5 h-5 rounded-full object-cover"
                  />
                ) : (
                  <UserCircle className="w-5 h-5" />
                )}
              </Link>
            </Tooltip>
            <Tooltip content="Log Out" position="right">
              <button
                onClick={handleLogout}
                className="p-2 rounded-lg hover:bg-sidebar-accent transition-colors text-destructive"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </Tooltip>
          </div>
        </div>
      </aside>

      {/* Mobile Bottom Dock */}
      <nav className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 lg:hidden">
        <div className="relative flex items-center bg-background/80 backdrop-blur-xl border border-border/50 rounded-full shadow-lg shadow-black/20 px-2 h-14 overflow-visible">
          {/* Left items */}
          {visibleDockItems
            .filter((item) => leftDockItems.some((l) => l.href === item.href))
            .map((item) => (
              <Link
                key={item.href}
                to={item.href}
                className={cn(
                  'flex items-center gap-1.5 px-3 h-full rounded-full transition-colors duration-150',
                  isActive(item.href)
                    ? 'text-primary'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <item.icon
                  className={cn('w-5 h-5', item.label === 'Environments' && 'opacity-80')}
                />
                <span className="text-[10px] font-medium hidden sm:inline">{item.label}</span>
              </Link>
            ))}

          {/* Center NukeLab Button - extends above dock */}
          <button
            onClick={() => setShowMore(true)}
            className="relative mx-1 flex items-center justify-center w-15 h-15 rounded-full bg-primary text-primary-foreground shadow-lg shadow-primary/40 transition-shadow duration-200 hover:shadow-primary/60 hover:shadow-xl"
          >
            <NukeLabLogo size={35} className="text-primary-foreground" />
            {/* Glow effect */}
            <div className="absolute inset-0 rounded-full bg-primary/20 blur-md -z-10" />
          </button>

          {/* Right items */}
          {visibleDockItems
            .filter((item) => rightDockItems.some((r) => r.href === item.href))
            .map((item) => (
              <Link
                key={item.href}
                to={item.href}
                className={cn(
                  'flex items-center gap-1.5 px-3 h-full rounded-full transition-colors duration-150',
                  isActive(item.href)
                    ? 'text-primary'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <item.icon className="w-5 h-5" />
                <span className="text-[10px] font-medium hidden sm:inline">{item.label}</span>
              </Link>
            ))}
          <NotificationCenter variant="dock" />
        </div>
      </nav>

      {/* Mobile More Menu */}
      <AnimatePresence>
        {showMore && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-0 bg-black/60 z-50 lg:hidden backdrop-blur-sm"
              onClick={() => setShowMore(false)}
            />
            <motion.div
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', damping: 25, stiffness: 300 }}
              drag="y"
              dragConstraints={{ top: 0, bottom: 0 }}
              dragElastic={{ top: 0, bottom: 0.35 }}
              onDragEnd={(_, info) => {
                if (info.offset.y > 80 || info.velocity.y > 500) {
                  setShowMore(false)
                }
              }}
              className="fixed bottom-0 left-0 right-0 z-[60] lg:hidden"
            >
              <div className="bg-background/95 backdrop-blur-xl rounded-t-3xl border border-border/50 shadow-2xl">
                {/* Drag handle */}
                <div className="flex justify-center pt-3 pb-1 cursor-grab active:cursor-grabbing">
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
                              'flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-100',
                              isActive(item.href)
                                ? 'bg-muted text-foreground shadow-sm'
                                : 'text-foreground/80 hover:bg-muted/50'
                            )}
                          >
                            <item.icon
                              className={cn(
                                'w-5 h-5 shrink-0',
                                item.label === 'Environments' && 'opacity-80',
                                isActive(item.href) && 'text-primary'
                              )}
                            />
                            <span>{item.label}</span>
                          </Link>
                        ))}
                      </div>
                    </div>
                  ))}

                  <div className="pt-4 border-t border-border/50">
                    <button
                      onClick={handleLogout}
                      className="flex items-center gap-2 w-full px-4 py-3 rounded-xl text-sm hover:bg-muted transition-colors text-destructive"
                    >
                      <LogOut className="w-4 h-4" />
                      <span>Log Out</span>
                    </button>
                  </div>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

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
  )
}
