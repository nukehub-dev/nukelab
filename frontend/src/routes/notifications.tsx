// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import {
  Bell,
  Check,
  CheckCheck,
  Trash2,
  Settings,
  Info,
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react'
import { motion } from 'framer-motion'
import { useState } from 'react'
import { PageHeader } from '../components/layout/page-header'
import { Checkbox } from '../components/ui/checkbox'
import {
  useNotifications,
  useMarkAsRead,
  useMarkAllAsRead,
  useDeleteNotification,
  useDeleteNotifications,
} from '../hooks/use-notifications'
import { cn, formatDate } from '../lib/utils'
import { springs } from '../lib/animations'
import { Tooltip } from '../components/ui/tooltip'
import { useConfirmDialog } from '../components/ui/confirm-dialog'

const severityIcons = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
}

const severityColors = {
  info: 'text-blue-400 bg-blue-400/10 border-blue-400/20',
  success: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
  warning: 'text-amber-400 bg-amber-400/10 border-amber-400/20',
  error: 'text-destructive bg-destructive/10 border-destructive/20',
}

export const Route = createFileRoute('/notifications')({
  component: NotificationsPage,
})

function NotificationsPage() {
  const { confirm, dialog } = useConfirmDialog()
  const [filter, setFilter] = useState<'all' | 'unread'>('all')
  const { data, isLoading } = useNotifications(filter === 'unread', 1, 50)
  const markAsRead = useMarkAsRead()
  const markAllAsRead = useMarkAllAsRead()
  const deleteNotification = useDeleteNotification()
  const deleteNotifications = useDeleteNotifications()
  const navigate = useNavigate()
  const [selectedIds, setSelectedIds] = useState<Record<string, boolean>>({})

  const notifications = data?.notifications || []
  const unreadCount = data?.unread_count || 0
  const selectedCount = Object.keys(selectedIds).filter((id) => selectedIds[id]).length
  const hasRead = notifications.some((n) => n.read)

  const handleToggleSelected = (id: string, checked: boolean) => {
    setSelectedIds((prev) => ({ ...prev, [id]: checked }))
  }

  const handleDeleteSelected = () => {
    const ids = Object.keys(selectedIds).filter((id) => selectedIds[id])
    if (ids.length === 0) return
    deleteNotifications.mutate({ notification_ids: ids }, { onSuccess: () => setSelectedIds({}) })
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Notifications" subtitle="View and manage your notifications" icon={Bell} />

      {/* Controls */}
      <motion.div
        className="flex items-center justify-between px-6 lg:px-10"
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
      >
        <div className="flex items-center gap-2">
          <button
            onClick={() => setFilter('all')}
            className={cn(
              'px-3 py-1.5 rounded-lg text-sm font-medium transition-colors',
              filter === 'all'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent'
            )}
          >
            All
          </button>
          <button
            onClick={() => setFilter('unread')}
            className={cn(
              'px-3 py-1.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5',
              filter === 'unread'
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-accent'
            )}
          >
            Unread
            {unreadCount > 0 && (
              <span className="text-xs bg-primary/20 text-primary-foreground px-1.5 py-0.5 rounded-full">
                {unreadCount}
              </span>
            )}
          </button>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {selectedCount > 0 && (
            <button
              onClick={handleDeleteSelected}
              disabled={deleteNotifications.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Delete selected ({selectedCount})
            </button>
          )}
          {unreadCount > 0 && (
            <button
              onClick={() => markAllAsRead.mutate()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:bg-accent transition-colors"
            >
              <CheckCheck className="w-3.5 h-3.5" />
              Mark all as read
            </button>
          )}
          {notifications.length > 0 && (
            <>
              <button
                onClick={() => deleteNotifications.mutate({ read_only: true })}
                disabled={deleteNotifications.isPending || !hasRead}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:bg-accent transition-colors disabled:opacity-50"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Clear read
              </button>
              <button
                onClick={async () => {
                  const confirmed = await confirm({
                    title: 'Delete all notifications?',
                    description: 'This action cannot be undone.',
                    variant: 'danger',
                  })
                  if (confirmed) {
                    deleteNotifications.mutate({ all: true })
                  }
                }}
                disabled={deleteNotifications.isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:bg-accent transition-colors disabled:opacity-50"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Clear all
              </button>
            </>
          )}
          <Link
            to="/settings/notifications"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:bg-accent transition-colors"
          >
            <Settings className="w-3.5 h-3.5" />
            Settings
          </Link>
        </div>
      </motion.div>

      {/* Notification List */}
      <div className="px-6 lg:px-10 pb-10">
        {isLoading ? (
          <div className="space-y-3">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="bubble p-4 animate-pulse">
                <div className="flex items-start gap-3">
                  <div className="w-9 h-9 rounded-lg bg-muted" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 bg-muted rounded w-1/3" />
                    <div className="h-3 bg-muted rounded w-2/3" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : notifications.length === 0 ? (
          <motion.div
            className="bubble p-12 text-center"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={springs.gentle}
          >
            <Bell className="w-12 h-12 text-muted-foreground mx-auto mb-4 opacity-50" />
            <h3 className="text-lg font-semibold mb-1">
              {filter === 'unread' ? 'No unread notifications' : 'No notifications yet'}
            </h3>
            <p className="text-sm text-muted-foreground">
              {filter === 'unread'
                ? "You're all caught up!"
                : 'When you receive notifications, they will appear here.'}
            </p>
          </motion.div>
        ) : (
          <motion.div className="space-y-2" initial="hidden" animate="visible">
            {notifications.map((notification, index) => {
              const Icon = severityIcons[notification.severity] || Info
              return (
                <motion.div
                  key={notification.id}
                  className={cn(
                    'bubble p-4 group relative',
                    notification.action_url && 'cursor-pointer',
                    !notification.read && 'border-primary/20 bg-primary/[0.02]'
                  )}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.03, ...springs.gentle }}
                  onClick={() => {
                    if (notification.action_url) {
                      navigate({ to: notification.action_url })
                    }
                    if (!notification.read) {
                      markAsRead.mutate(notification.id)
                    }
                  }}
                >
                  <div className="flex items-start gap-4">
                    <span onClick={(e) => e.stopPropagation()} className="shrink-0 pt-1">
                      <Checkbox
                        checked={!!selectedIds[notification.id]}
                        onChange={(checked) => handleToggleSelected(notification.id, checked)}
                      />
                    </span>

                    {/* Icon */}
                    <div
                      className={cn(
                        'p-2 rounded-lg border shrink-0',
                        severityColors[notification.severity]
                      )}
                    >
                      <Icon className="w-4 h-4" />
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <h4 className="text-sm font-medium truncate">
                            {notification.title}
                            {!notification.read && (
                              <span className="ml-2 inline-block w-1.5 h-1.5 rounded-full bg-primary" />
                            )}
                          </h4>
                          <p className="text-sm text-muted-foreground mt-1">
                            {notification.message}
                          </p>
                          <div className="flex items-center gap-3 mt-2">
                            <span className="text-xs text-muted-foreground">
                              {formatDate(notification.created_at)}
                            </span>
                            {notification.action_url && (
                              <Link
                                to={notification.action_url}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  if (!notification.read) {
                                    markAsRead.mutate(notification.id)
                                  }
                                }}
                                className="text-xs text-primary hover:underline"
                              >
                                View details
                              </Link>
                            )}
                          </div>
                        </div>

                        {/* Actions */}
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          {!notification.read && (
                            <Tooltip content="Mark as read">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  markAsRead.mutate(notification.id)
                                }}
                                className="p-1.5 rounded-lg hover:bg-accent transition-colors"
                              >
                                <Check className="w-3.5 h-3.5 text-muted-foreground" />
                              </button>
                            </Tooltip>
                          )}
                          <Tooltip content="Delete">
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                deleteNotification.mutate(notification.id)
                              }}
                              className="p-1.5 rounded-lg hover:bg-destructive/10 transition-colors"
                            >
                              <Trash2 className="w-3.5 h-3.5 text-muted-foreground hover:text-destructive" />
                            </button>
                          </Tooltip>
                        </div>
                      </div>
                    </div>
                  </div>
                </motion.div>
              )
            })}
          </motion.div>
        )}
      </div>
      {dialog}
    </div>
  )
}
