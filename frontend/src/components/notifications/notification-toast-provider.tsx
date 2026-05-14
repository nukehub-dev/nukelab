import { useEffect, useRef } from 'react';
import { useUnreadCount, useNotifications } from '../../hooks/use-notifications';
import { useToast } from '../../stores/toast-store';
import { Server, CreditCard, AlertTriangle, Info, CheckCircle } from 'lucide-react';

const typeIcons: Record<string, typeof Info> = {
  server: Server,
  credit: CreditCard,
  system: Info,
};

const severityToToastType = {
  info: 'info' as const,
  success: 'success' as const,
  warning: 'warning' as const,
  error: 'error' as const,
};

/**
 * Global provider that watches for new notifications and displays them as toasts.
 * Place this inside AppShell (already mounted via a hook approach).
 */
export function useNotificationToasts() {
  const { data: unreadCount = 0 } = useUnreadCount();
  const prevCountRef = useRef(0);
  const shownIdsRef = useRef<Set<string>>(new Set());
  const { info, success, warning, error } = useToast();

  // Fetch unread notifications when count changes
  const { data: notificationsData } = useNotifications(true, 1, 10);
  const notifications = notificationsData?.notifications || [];

  useEffect(() => {
    const prevCount = prevCountRef.current;
    prevCountRef.current = unreadCount;

    if (unreadCount <= prevCount) return;
    if (!notifications.length) return;

    // Show toasts for notifications we haven't shown yet
    const newNotifications = notifications.filter((n) => !shownIdsRef.current.has(n.id));

    for (const notification of newNotifications.slice(0, 3)) {
      shownIdsRef.current.add(notification.id);

      const toastFn =
        notification.severity === 'success'
          ? success
          : notification.severity === 'warning'
            ? warning
            : notification.severity === 'error'
              ? error
              : info;

      toastFn(notification.title, notification.message);
    }
  }, [unreadCount, notifications, info, success, warning, error]);

  // Reset shown IDs when count drops to 0 (all read)
  useEffect(() => {
    if (unreadCount === 0) {
      shownIdsRef.current.clear();
    }
  }, [unreadCount]);
}
