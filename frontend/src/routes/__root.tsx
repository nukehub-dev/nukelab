import { createRootRoute } from '@tanstack/react-router';
import { AppShell } from '../components/layout/app-shell';
import { WebSocketProvider } from '../contexts/websocket-context';

export const Route = createRootRoute({
  component: () => (
    <WebSocketProvider>
      <AppShell />
    </WebSocketProvider>
  ),
});
