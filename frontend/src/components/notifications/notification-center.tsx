import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { Link } from '@tanstack/react-router';
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
} from 'lucide-react';
import {
  useNotifications,
  useUnreadCount,
  useMarkAsRead,
  useMarkAllAsRead,
  useDeleteNotification,
} from '../../hooks/use-notifications';
import { cn } from '../../lib/utils';
import { Tooltip } from '../ui/tooltip';

const severityIcons = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
};

const severityColors = {
  info: 'text-blue-400 bg-blue-400/10',
  success: 'text-emerald-400 bg-emerald-400/10',
  warning: 'text-amber-400 bg-amber-400/10',
  error: 'text-destructive bg-destructive/10',
};

const MAX_DROPDOWN_ITEMS = 6;

export function NotificationCenter() {
  const [isOpen, setIsOpen] = useState(false);
  const bellRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  
  const { data: unreadCount = 0, refetch: refetchUnread } = useUnreadCount();
  const { data: notificationsData, refetch: refetchNotifications } = useNotifications(false, 1, MAX_DROPDOWN_ITEMS);
  const markAsRead = useMarkAsRead();
  const markAllAsRead = useMarkAllAsRead();
  const deleteNotification = useDeleteNotification();

  const notifications = notificationsData?.notifications || [];
  const totalCount = notificationsData?.total || 0;

  const MAX_DROPDOWN_HEIGHT = 480;

  // Position dropdown when opened
  useEffect(() => {
    if (!isOpen || !bellRef.current || !dropdownRef.current) return;

    const positionDropdown = () => {
      if (!bellRef.current || !dropdownRef.current) return;
      const bell = bellRef.current;
      const dropdown = dropdownRef.current;
      const rect = bell.getBoundingClientRect();

      const gap = 12;
      const dropdownWidth = 360;

      // Position to the right of the bell button
      let left = rect.right + gap;
      // Align bottom of dropdown with bottom of bell button (so it grows upward)
      let top = rect.bottom - MAX_DROPDOWN_HEIGHT;

      // If would overflow right, show on the left side instead
      if (left + dropdownWidth > window.innerWidth - gap) {
        left = rect.left - dropdownWidth - gap;
      }

      // If dropdown goes above viewport, position below the bell instead
      if (top < gap) {
        top = rect.bottom + gap;
      }

      // Ensure not off-screen
      left = Math.max(gap, left);
      top = Math.max(gap, top);

      dropdown.style.position = 'fixed';
      dropdown.style.top = `${top}px`;
      dropdown.style.left = `${left}px`;
      dropdown.style.zIndex = '9999';
      dropdown.style.width = `${dropdownWidth}px`;
      dropdown.style.maxHeight = `${MAX_DROPDOWN_HEIGHT}px`;
    };

    // Measure after content has rendered
    positionDropdown();
    const raf = requestAnimationFrame(positionDropdown);
    return () => cancelAnimationFrame(raf);
  }, [isOpen]);

  // Close on escape
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false);
    };
    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
      return () => document.removeEventListener('keydown', handleEscape);
    }
  }, [isOpen]);

  // Close on click outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        bellRef.current && 
        !bellRef.current.contains(target) &&
        dropdownRef.current &&
        !dropdownRef.current.contains(target)
      ) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener('mousedown', handleClick);
      return () => document.removeEventListener('mousedown', handleClick);
    }
  }, [isOpen]);

  const toggleDropdown = useCallback(() => {
    setIsOpen((prev) => {
      const next = !prev;
      if (next) {
        // Refetch when opening
        refetchUnread();
        refetchNotifications();
      }
      return next;
    });
  }, [refetchUnread, refetchNotifications]);

  const handleClose = useCallback(() => {
    setIsOpen(false);
  }, []);

  return (
    <>
      {isOpen ? (
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
            <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 bg-destructive text-destructive-foreground text-[10px] font-bold rounded-full flex items-center justify-center border-2 border-sidebar"
            >
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
              <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 bg-destructive text-destructive-foreground text-[10px] font-bold rounded-full flex items-center justify-center border-2 border-sidebar"
              >
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </button>
        </Tooltip>
      )}

      {isOpen && createPortal(
        <div
            ref={dropdownRef}
            className="bg-popover/80 backdrop-blur-xl border border-border/50 rounded-2xl shadow-2xl shadow-black/20 overflow-hidden"
            style={{
              position: 'fixed',
              zIndex: 9999,
              width: '360px',
              maxWidth: 'calc(100vw - 2rem)',
            }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/50 bg-muted/30 backdrop-blur-sm">
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
                    onClick={handleClose}
                    className="p-2 rounded-lg hover:bg-accent transition-colors inline-flex"
                  >
                    <Settings className="w-4 h-4 text-muted-foreground" />
                  </Link>
                </Tooltip>
              </div>
            </div>

            {/* Notification List */}
            <div className="overflow-y-auto" style={{ maxHeight: '380px' }}>
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
                    const Icon = severityIcons[notification.severity as keyof typeof severityIcons] || Info;
                    return (
                      <div
                        key={notification.id}
                        className={cn(
                          'flex items-start gap-3 px-4 py-3 hover:bg-accent/40 transition-colors group cursor-pointer',
                          !notification.read && 'bg-primary/[0.03]'
                        )}
                        onClick={() => {
                          if (!notification.read) {
                            markAsRead.mutate(notification.id);
                          }
                          if (notification.action_url) {
                            handleClose();
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
                          <p className={cn('text-sm leading-snug', !notification.read && 'font-medium')}>
                            {notification.title}
                          </p>
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                            {notification.message}
                          </p>
                          <p className="text-[10px] text-muted-foreground/70 mt-1">
                            {new Date(notification.created_at).toLocaleDateString(undefined, {
                              month: 'short',
                              day: 'numeric',
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </p>
                        </div>

                        <div className="flex flex-col items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                          {!notification.read && (
                            <Tooltip content="Mark as read">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  markAsRead.mutate(notification.id);
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
                                e.stopPropagation();
                                deleteNotification.mutate(notification.id);
                              }}
                              className="p-1 rounded hover:bg-destructive/10 transition-colors"
                            >
                              <Trash2 className="w-3 h-3 text-muted-foreground hover:text-destructive" />
                            </button>
                          </Tooltip>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between px-4 py-2.5 border-t border-border/50 bg-muted/30 backdrop-blur-sm">
              <Link
                to="/notifications"
                onClick={handleClose}
                className="text-xs font-medium text-primary hover:text-primary/80 transition-colors"
              >
                View all notifications
                {totalCount > MAX_DROPDOWN_ITEMS && (
                  <span className="ml-1 text-muted-foreground">({totalCount})</span>
                )}
              </Link>
              <span className="text-[10px] text-muted-foreground">Press Esc to close</span>
            </div>
          </div>,
        document.body
      )}
    </>
  );
}
