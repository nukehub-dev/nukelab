import { createContext, useContext, type ReactNode } from 'react';
import { useWebSocket, type WebSocketMessage } from '../hooks/use-websocket';
import { useAuthStore } from '../stores/auth-store';
import { isAuthenticated } from '../hooks/use-auth';

export interface WebSocketContextValue {
  isConnected: boolean;
  isConnecting: boolean;
  error: string | null;
  subscribe: (scope: string, targetId?: string) => void;
  unsubscribe: (scope: string, targetId?: string) => void;
  onMessage: (handler: (message: WebSocketMessage) => void) => () => void;
  send: (data: unknown) => boolean;
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null);

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const user = useAuthStore((state) => state.user);
  const canConnect = !!(user && isAuthenticated());
  const ws = useWebSocket({ autoConnect: canConnect });

  return (
    <WebSocketContext.Provider value={ws}>
      {children}
    </WebSocketContext.Provider>
  );
}

export function useSharedWebSocket(): WebSocketContextValue {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error('useSharedWebSocket must be used within a WebSocketProvider');
  }
  return context;
}
