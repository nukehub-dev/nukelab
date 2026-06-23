import { useContext } from 'react';
import { WebSocketContext, type WebSocketContextValue } from '../contexts/websocket-context';

export type { WebSocketContextValue };

export function useSharedWebSocket(): WebSocketContextValue {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error('useSharedWebSocket must be used within a WebSocketProvider');
  }
  return context;
}
