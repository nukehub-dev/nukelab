import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useWebSocket } from '../../hooks/use-websocket';
import { useAuthStore } from '../../stores/auth-store';
import { useToast } from '../../stores/toast-store';
import { isAuthenticated } from '../../hooks/use-auth';
import type { Notification } from '../../hooks/use-notifications';

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
 * Listens for real-time notifications via WebSocket and shows toasts.
 * Falls back to HTTP polling via the unread-count hook if WebSocket is down.
 * Uses localStorage timestamp to avoid replaying old notifications across tabs.
 */
export function useNotificationToasts() {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const lastToastTimeRef = useRef<string>(getLastToastTime());
  const { info, success, warning, error } = useToast();

  // Only connect when both user object and JWT token are present
  const canConnect = !!(user && isAuthenticated());
  const { isConnected, subscribe, unsubscribe, onMessage } = useWebSocket({
    autoConnect: canConnect,
  });

  // Subscribe to user-specific room when connected
  useEffect(() => {
    if (!isConnected || !user) return;
    subscribe('user', user.id);
    return () => {
      unsubscribe('user', user.id);
    };
  }, [isConnected, user, subscribe, unsubscribe]);

  // Handle incoming notification events
  useEffect(() => {
    const cleanup = onMessage((message) => {
      if (message.event !== 'notification:new') return;

      const notification = message.data as Notification;
      if (!notification?.created_at) return;

      // Deduplicate against last toast time (cross-tab safety)
      const lastToastTime = lastToastTimeRef.current;
      if (parseUtcDate(notification.created_at) <= parseUtcDate(lastToastTime)) {
        return;
      }

      // Show toast based on severity
      const toastFn =
        notification.severity === 'success'
          ? success
          : notification.severity === 'warning'
            ? warning
            : notification.severity === 'error'
              ? error
              : info;

      toastFn(notification.title, notification.message);

      // Update last toast time
      lastToastTimeRef.current = notification.created_at;
      setLastToastTime(notification.created_at);

      // Invalidate notification queries so NotificationCenter updates instantly
      queryClient.invalidateQueries({ queryKey: ['notifications'] });
    });

    return cleanup;
  }, [onMessage, queryClient, info, success, warning, error]);
}
