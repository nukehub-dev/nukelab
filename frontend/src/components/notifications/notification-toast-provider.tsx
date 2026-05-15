import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useUnreadCount } from '../../hooks/use-notifications';
import { useToast } from '../../stores/toast-store';
import { api } from '../../lib/api';
import type { Notification, NotificationListResponse } from '../../hooks/use-notifications';

const STORAGE_KEY = 'nukelab-last-notification-toast';

/** Backend returns naive UTC datetimes (no Z suffix). Treat them as UTC. */
function parseUtcDate(iso: string): Date {
  const normalized = iso.endsWith('Z') ? iso : iso + 'Z';
  return new Date(normalized);
}

function getLastToastTime(): string {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored) return stored;
  const now = new Date().toISOString();
  localStorage.setItem(STORAGE_KEY, now);
  return now;
}

function setLastToastTime(time: string) {
  localStorage.setItem(STORAGE_KEY, time);
}

/**
 * Watches unread count and shows toasts for new notifications.
 * Uses React Query fetchQuery for fresh data and localStorage timestamp
 * to avoid replaying old notifications across tabs.
 */
export function useNotificationToasts() {
  const queryClient = useQueryClient();
  const { data: unreadCount = 0 } = useUnreadCount();
  const prevCountRef = useRef(0);
  const lastToastTimeRef = useRef<string>(getLastToastTime());
  const busyRef = useRef(false);
  const { info, success, warning, error } = useToast();

  useEffect(() => {
    const prevCount = prevCountRef.current;
    prevCountRef.current = unreadCount;

    if (unreadCount <= prevCount) return;
    if (busyRef.current) return;

    const checkAndToast = async () => {
      busyRef.current = true;
      try {
        const data = await queryClient.fetchQuery<NotificationListResponse>({
          queryKey: ['notifications', 'unread', 1, 10],
          queryFn: async () => {
            return api.get<NotificationListResponse>(
              '/notifications/?unread_only=true&page=1&page_size=10'
            );
          },
          staleTime: 0,
        });

        const notifications = data.notifications || [];
        const lastToastTime = lastToastTimeRef.current;
        const lastToastDate = parseUtcDate(lastToastTime);

        const newNotifications = notifications.filter(
          (n: Notification) => parseUtcDate(n.created_at) > lastToastDate
        );

        if (!newNotifications.length) return;

        const toShow = newNotifications.slice(0, 3);
        let newestTime = lastToastTime;

        for (const notification of toShow) {
          const toastFn =
            notification.severity === 'success'
              ? success
              : notification.severity === 'warning'
                ? warning
                : notification.severity === 'error'
                  ? error
                  : info;

          toastFn(notification.title, notification.message);

          if (notification.created_at > newestTime) {
            newestTime = notification.created_at;
          }
        }

        lastToastTimeRef.current = newestTime;
        setLastToastTime(newestTime);
      } finally {
        busyRef.current = false;
      }
    };

    checkAndToast();
  }, [unreadCount, queryClient, info, success, warning, error]);
}
