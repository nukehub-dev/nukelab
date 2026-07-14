// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { Link } from '@tanstack/react-router'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Bell,
  Check,
  CheckCheck,
  Trash2,
  Info,
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
  Settings,
  Inbox,
  X,
} from 'lucide-react'
import {
  useNotifications,
  useUnreadCount,
  useMarkAsRead,
  useMarkAllAsRead,
  useDeleteNotification,
  type Notification,
} from '../../hooks/use-notifications'
import { cn, formatDate } from '../../lib/utils'
import { Tooltip } from '../ui/tooltip'

const severityIcons = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
}

const severityColors = {
  info: 'text-blue-400 bg-blue-400/10',
  success: 'text-emerald-400 bg-emerald-400/10',
  warning: 'text-amber-400 bg-amber-400/10',
  error: 'text-destructive bg-destructive/10',
}

const MAX_DROPDOWN_ITEMS = 6
const MAX_DROPDOWN_HEIGHT = 480

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth < 1024 : false
  )
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 1024)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return isMobile
}

interface NotificationPanelProps {
  unreadCount: number
  notifications: Notification[]
  totalCount: number
  onClose: () => void
  markAsRead: ReturnType<typeof useMarkAsRead>
  markAllAsRead: ReturnType<typeof useMarkAllAsRead>
  deleteNotification: ReturnType<typeof useDeleteNotification>
  isMobile?: boolean
}

function NotificationPanel({
  unreadCount,
  notifications,
  totalCount,
  onClose,
  markAsRead,
  markAllAsRead,
  deleteNotification,
  isMobile,
}: NotificationPanelProps) {
  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/50 bg-muted/30 backdrop-blur-sm shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-primary/10">
            <Bell className="w-4 h-4 text-primary" />
          </div>
          <div>
            <h3 className="font-semibold text-sm">Notifications</h3>
            <p className="text-[11px] text-muted-foreground">
              {unreadCount > 0 ? `${unreadCount} unread` : 'No new notifications'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-0.5">
          {unreadCount > 0 && (
            <Tooltip content="Mark all as read">
              <button
                onClick={() => markAllAsRead.mutate()}
                className="p-2 rounded-lg hover:bg-accent transition-colors"
              >
                <CheckCheck className="w-4 h-4 text-muted-foreground" />
              </button>
            </Tooltip>
          )}
          <Tooltip content="Notification settings">
            <Link
              to="/settings/notifications"
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-accent transition-colors inline-flex"
            >
              <Settings className="w-4 h-4 text-muted-foreground" />
            </Link>
          </Tooltip>
          {!isMobile && (
            <button onClick={onClose} className="p-2 rounded-lg hover:bg-accent transition-colors">
              <X className="w-4 h-4 text-muted-foreground" />
            </button>
          )}
        </div>
      </div>

      {/* Notification List */}
      <div className="overflow-y-auto flex-1 min-h-0">
        {notifications.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-muted-foreground">
            <div className="p-3 rounded-full bg-muted mb-3">
              <Inbox className="w-6 h-6 opacity-50" />
            </div>
            <p className="text-sm font-medium">No notifications yet</p>
            <p className="text-xs mt-0.5">We'll notify you when something happens.</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {notifications.map((notification) => {
              const Icon =
                severityIcons[notification.severity as keyof typeof severityIcons] || Info
              return (
                <div
                  key={notification.id}
                  className={cn(
                    'flex items-start gap-3 px-4 py-3 hover:bg-accent/40 transition-colors group cursor-pointer',
                    !notification.read && 'bg-primary/[0.03]'
                  )}
                  onClick={() => {
                    if (!notification.read) {
                      markAsRead.mutate(notification.id)
                    }
                  }}
                >
                  <div className="mt-2 shrink-0">
                    {!notification.read ? (
                      <div className="w-2 h-2 rounded-full bg-primary" />
                    ) : (
                      <div className="w-2 h-2 rounded-full border border-border" />
                    )}
                  </div>

                  <div
                    className={cn(
                      'p-1.5 rounded-lg shrink-0',
                      severityColors[notification.severity as keyof typeof severityColors]
                    )}
                  >
                    <Icon className="w-3.5 h-3.5" />
                  </div>

                  <div className="flex-1 min-w-0">
                    {notification.action_url ? (
                      <Link
                        to={notification.action_url}
                        onClick={() => {
                          if (!notification.read) {
                            markAsRead.mutate(notification.id)
                          }
                          onClose()
                        }}
                        className="block hover:underline"
                      >
                        <p
                          className={cn(
                            'text-sm leading-snug',
                            !notification.read && 'font-medium'
                          )}
                        >
                          {notification.title}
                        </p>
                      </Link>
                    ) : (
                      <p
                        className={cn('text-sm leading-snug', !notification.read && 'font-medium')}
                      >
                        {notification.title}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                      {notification.message}
                    </p>
                    <p className="text-[10px] text-muted-foreground/70 mt-1">
                      {formatDate(notification.created_at)}
                    </p>
                  </div>

                  <div className="flex flex-col items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    {!notification.read && (
                      <Tooltip content="Mark as read">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            markAsRead.mutate(notification.id)
                          }}
                          className="p-1 rounded hover:bg-accent transition-colors"
                        >
                          <Check className="w-3 h-3 text-muted-foreground" />
                        </button>
                      </Tooltip>
                    )}
                    <Tooltip content="Delete">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          deleteNotification.mutate(notification.id)
                        }}
                        className="p-1 rounded hover:bg-destructive/10 transition-colors"
                      >
                        <Trash2 className="w-3 h-3 text-muted-foreground hover:text-destructive" />
                      </button>
                    </Tooltip>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between px-4 py-2.5 border-t border-border/50 bg-muted/30 backdrop-blur-sm shrink-0">
        <Link
          to="/notifications"
          onClick={onClose}
          className="text-xs font-medium text-primary hover:text-primary/80 transition-colors"
        >
          View all notifications
          {totalCount > MAX_DROPDOWN_ITEMS && (
            <span className="ml-1 text-muted-foreground">({totalCount})</span>
          )}
        </Link>
        <span className="text-[10px] text-muted-foreground">
          {isMobile ? 'Tap outside to close' : 'Press Esc to close'}
        </span>
      </div>
    </>
  )
}

interface NotificationCenterProps {
  variant?: 'default' | 'dock'
}

export function NotificationCenter({ variant = 'default' }: NotificationCenterProps) {
  const [isOpen, setIsOpen] = useState(false)
  const bellRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const isMobile = useIsMobile()
  const isDock = variant === 'dock'

  const { data: unreadCount = 0, refetch: refetchUnread } = useUnreadCount()
  const { data: notificationsData, refetch: refetchNotifications } = useNotifications(
    false,
    1,
    MAX_DROPDOWN_ITEMS
  )
  const markAsRead = useMarkAsRead()
  const markAllAsRead = useMarkAllAsRead()
  const deleteNotification = useDeleteNotification()

  const notifications = notificationsData?.notifications || []
  const totalCount = notificationsData?.total || 0

  // Position dropdown when opened (desktop only)
  useEffect(() => {
    if (!isOpen || isMobile || !bellRef.current || !dropdownRef.current) return

    const positionDropdown = () => {
      if (!bellRef.current || !dropdownRef.current) return
      const bell = bellRef.current
      const dropdown = dropdownRef.current
      const rect = bell.getBoundingClientRect()

      const gap = 8
      const dropdownWidth = 360
      const actualHeight = Math.min(dropdown.offsetHeight, MAX_DROPDOWN_HEIGHT)

      let left = rect.right + gap
      let top: number
      let originX: 'left' | 'right' = 'left'
      let originY: 'top' | 'bottom'

      if (left + dropdownWidth > window.innerWidth - gap) {
        left = rect.left - dropdownWidth - gap
        originX = 'right'
      }

      const spaceBelow = window.innerHeight - rect.bottom - gap
      const spaceAbove = rect.top - gap

      if (actualHeight <= spaceBelow) {
        top = rect.bottom + gap
        originY = 'top'
      } else if (actualHeight <= spaceAbove) {
        top = rect.top - actualHeight - gap
        originY = 'bottom'
      } else {
        top = rect.bottom + gap
        originY = 'top'
        if (top + actualHeight > window.innerHeight - gap) {
          top = Math.max(gap, window.innerHeight - actualHeight - gap)
        }
      }

      left = Math.max(gap, Math.min(left, window.innerWidth - dropdownWidth - gap))
      top = Math.max(gap, top)

      dropdown.style.position = 'fixed'
      dropdown.style.top = `${top}px`
      dropdown.style.left = `${left}px`
      dropdown.style.zIndex = '9999'
      dropdown.style.width = `${dropdownWidth}px`
      dropdown.style.maxHeight = `${MAX_DROPDOWN_HEIGHT}px`
      dropdown.style.transformOrigin = `${originY} ${originX}`
    }

    positionDropdown()
    const raf = requestAnimationFrame(positionDropdown)

    window.addEventListener('resize', positionDropdown)
    window.addEventListener('scroll', positionDropdown, true)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', positionDropdown)
      window.removeEventListener('scroll', positionDropdown, true)
    }
  }, [isOpen, isMobile])

  // Close on escape
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false)
    }
    if (isOpen) {
      document.addEventListener('keydown', handleEscape)
      return () => document.removeEventListener('keydown', handleEscape)
    }
  }, [isOpen])

  // Close on click outside (desktop only — mobile uses backdrop)
  useEffect(() => {
    if (isMobile) return
    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node
      if (
        bellRef.current &&
        !bellRef.current.contains(target) &&
        dropdownRef.current &&
        !dropdownRef.current.contains(target)
      ) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClick)
      return () => document.removeEventListener('mousedown', handleClick)
    }
  }, [isOpen, isMobile])

  const toggleDropdown = useCallback(() => {
    setIsOpen((prev) => {
      const next = !prev
      if (next) {
        refetchUnread()
        refetchNotifications()
      }
      return next
    })
  }, [refetchUnread, refetchNotifications])

  const handleClose = useCallback(() => {
    setIsOpen(false)
  }, [])

  const panelProps = {
    unreadCount,
    notifications,
    totalCount,
    onClose: handleClose,
    markAsRead,
    markAllAsRead,
    deleteNotification,
    isMobile,
  }

  return (
    <>
      {isDock ? (
        /* Dock variant: matches nav link styling */
        <button
          ref={bellRef}
          onClick={toggleDropdown}
          className={cn(
            'flex items-center gap-1.5 px-3 h-full rounded-full transition-colors duration-150 overflow-visible',
            isOpen ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
          )}
          aria-label="Notifications"
          aria-expanded={isOpen}
        >
          <span className="relative">
            <Bell className="w-5 h-5" />
            {unreadCount > 0 && (
              <span className="absolute -top-2 -right-2 min-w-[16px] px-1 bg-destructive text-destructive-foreground text-[10px] font-bold rounded-full flex items-center justify-center border-2 border-background">
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </span>
          <span className="text-[10px] font-medium hidden sm:inline">Alerts</span>
        </button>
      ) : isOpen ? (
        <button
          ref={bellRef}
          onClick={toggleDropdown}
          className={cn(
            'relative p-2 rounded-xl transition-all duration-200 shrink-0',
            'bg-primary/10 text-primary'
          )}
          aria-label="Notifications"
          aria-expanded={isOpen}
        >
          <Bell className="w-5 h-5" />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 bg-destructive text-destructive-foreground text-[10px] font-bold rounded-full flex items-center justify-center border-2 border-sidebar">
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </button>
      ) : (
        <Tooltip content="Notifications" position="right">
          <button
            ref={bellRef}
            onClick={toggleDropdown}
            className={cn(
              'relative p-2 rounded-xl transition-all duration-200 shrink-0',
              'hover:bg-sidebar-accent text-sidebar-foreground'
            )}
            aria-label="Notifications"
            aria-expanded={isOpen}
          >
            <Bell className="w-5 h-5" />
            {unreadCount > 0 && (
              <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 bg-destructive text-destructive-foreground text-[10px] font-bold rounded-full flex items-center justify-center border-2 border-sidebar">
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </button>
        </Tooltip>
      )}

      {/* Desktop: floating dropdown */}
      {!isMobile &&
        createPortal(
          <AnimatePresence>
            {isOpen && (
              <motion.div
                ref={dropdownRef}
                className="bg-popover/80 backdrop-blur-xl border border-border/50 rounded-2xl shadow-2xl shadow-black/20 overflow-hidden flex flex-col"
                style={{
                  position: 'fixed',
                  zIndex: 9999,
                  width: '360px',
                  maxWidth: 'calc(100vw - 2rem)',
                  maxHeight: `${MAX_DROPDOWN_HEIGHT}px`,
                }}
                initial={{ opacity: 0, scale: 0.82 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                transition={{ type: 'spring', stiffness: 450, damping: 28 }}
              >
                <NotificationPanel {...panelProps} />
              </motion.div>
            )}
          </AnimatePresence>,
          document.body
        )}

      {/* Mobile: bottom sheet */}
      {isMobile &&
        createPortal(
          <AnimatePresence>
            {isOpen && (
              <motion.div
                key="mobile-sheet"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="fixed inset-0 z-50"
              >
                {/* Dark overlay */}
                <div
                  className="absolute inset-0 bg-black/60 backdrop-blur-sm"
                  onPointerDown={handleClose}
                />

                {/* Sheet */}
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
                      handleClose()
                    }
                  }}
                  onClick={(e) => e.stopPropagation()}
                  className="absolute bottom-0 left-0 right-0 z-[60]"
                >
                  <div
                    data-notification-sheet
                    className="mx-auto w-full max-w-[75vw] max-h-[85vh] bg-popover/95 backdrop-blur-xl rounded-t-3xl border border-border/50 shadow-2xl overflow-hidden flex flex-col"
                  >
                    {/* Drag handle */}
                    <div className="flex justify-center pt-3 pb-1 shrink-0 cursor-grab active:cursor-grabbing">
                      <div className="w-12 h-1.5 rounded-full bg-muted-foreground/30" />
                    </div>
                    <NotificationPanel {...panelProps} />
                  </div>
                </motion.div>
              </motion.div>
            )}
          </AnimatePresence>,
          document.body
        )}
    </>
  )
}
