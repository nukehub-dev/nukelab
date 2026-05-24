import { useCallback } from 'react';
import { useAuthStore } from '../stores/auth-store';
import { useServerActions } from './use-servers';
import { useReasonDialog } from './use-reason-dialog';
import type { Server } from '../types/api';

export function useServerActionsWithReason() {
  const user = useAuthStore((state) => state.user);
  const actions = useServerActions();
  const { prompt, dialog } = useReasonDialog();

  const isOwnServer = useCallback(
    (server: Server) => {
      return !!user && server.user_id === user.id;
    },
    [user]
  );

  const promptAccessReason = useCallback(
    async (server: Server, actionLabel: string): Promise<string | null> => {
      if (isOwnServer(server)) return '';
      const owner = server.username || 'another user';
      return prompt({
        description: `You are about to ${actionLabel} a server owned by ${owner}. Please provide a reason.`,
        actionLabel,
      });
    },
    [isOwnServer, prompt]
  );

  const runWithReason = useCallback(
    (server: Server, mutateFn: (vars: { serverId: string; reason?: string }) => void, actionLabel: string) => {
      if (isOwnServer(server)) {
        mutateFn({ serverId: server.id });
        return;
      }

      prompt({
        description: `You are about to ${actionLabel} a server owned by ${server.username || 'another user'}. Please provide a reason.`,
        actionLabel,
      }).then((reason) => {
        if (reason) {
          mutateFn({ serverId: server.id, reason });
        }
      });
    },
    [isOwnServer, prompt]
  );

  const runAsyncWithReason = useCallback(
    async (
      server: Server,
      mutateAsyncFn: (vars: { serverId: string; reason?: string }) => Promise<unknown>,
      actionLabel: string
    ): Promise<boolean> => {
      if (isOwnServer(server)) {
        await mutateAsyncFn({ serverId: server.id });
        return true;
      }

      const reason = await prompt({
        description: `You are about to ${actionLabel} a server owned by ${server.username || 'another user'}. Please provide a reason.`,
        actionLabel,
      });
      if (reason) {
        await mutateAsyncFn({ serverId: server.id, reason });
        return true;
      }
      return false;
    },
    [isOwnServer, prompt]
  );

  const startServer = useCallback(
    (server: Server) => runWithReason(server, actions.startServer.mutate, 'start'),
    [runWithReason, actions.startServer]
  );

  const stopServer = useCallback(
    (server: Server) => runWithReason(server, actions.stopServer.mutate, 'stop'),
    [runWithReason, actions.stopServer]
  );

  const restartServer = useCallback(
    (server: Server) => runWithReason(server, actions.restartServer.mutate, 'restart'),
    [runWithReason, actions.restartServer]
  );

  const deleteServer = useCallback(
    (server: Server) => runWithReason(server, actions.deleteServer.mutate, 'delete'),
    [runWithReason, actions.deleteServer]
  );

  const startServerAsync = useCallback(
    (server: Server) => runAsyncWithReason(server, actions.startServer.mutateAsync, 'start'),
    [runAsyncWithReason, actions.startServer]
  );

  return {
    startServer,
    stopServer,
    restartServer,
    deleteServer,
    startServerAsync,
    promptAccessReason,
    isOperationPending: actions.isOperationPending,
    createServer: actions.createServer,
    updateServer: actions.updateServer,
    dialog,
  };
}
