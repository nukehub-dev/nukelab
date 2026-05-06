import { createFileRoute, Link } from '@tanstack/react-router';
import { useState, useEffect, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  Server,
  ArrowLeft,
  Play,
  Loader2,
  ExternalLink,
  AlertCircle,
  RefreshCw,
  CheckCircle2,
} from 'lucide-react';
import { useServerByPath, useServerActions } from '../hooks/use-servers';
import { StatusBadge } from '../components/data/status-badge';
import { springs } from '../lib/animations';
import { formatDate } from '../lib/utils';
import { useQueryClient } from '@tanstack/react-query';

export const Route = createFileRoute('/user/$username/$serverName')({
  component: ServerGatewayPage,
});

function ServerGatewayPage() {
  const { username, serverName } = Route.useParams();
  const { data: server, isLoading, isError, error } = useServerByPath(username, serverName);
  const { startServer } = useServerActions();
  const queryClient = useQueryClient();

  const [isStarting, setIsStarting] = useState(false);
  const [pollCount, setPollCount] = useState(0);
  const startTimeRef = useRef<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [manualOpenReady, setManualOpenReady] = useState(false);

  useEffect(() => {
    if (server?.status === 'pending' && startTimeRef.current === null) {
      startTimeRef.current = Date.now();
    }
  }, [server?.status]);

  useEffect(() => {
    if (server?.status !== 'pending' && !isStarting) {
      return;
    }
    const interval = setInterval(() => {
      if (startTimeRef.current) {
        setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(interval);
  }, [server?.status, isStarting]);

  // Poll server status when it's pending (starting up)
  useEffect(() => {
    if (!server || server.status !== 'pending') {
      return;
    }

    const interval = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['server-by-path', username, serverName] });
      setPollCount((c) => c + 1);
    }, 2000);

    return () => clearInterval(interval);
  }, [server, username, serverName, queryClient]);

  // When server transitions to running, redirect to the actual container URL
  useEffect(() => {
    if (server?.status === 'running') {
      const redirectKey = `server-redirect-${server.id}`;
      const alreadyRedirected = sessionStorage.getItem(redirectKey);

      if (alreadyRedirected) {
        // We already tried redirecting but we're still here (Traefik not ready)
        // Show manual open button instead of looping
        setManualOpenReady(true);
        return;
      }

      // Mark that we're about to redirect
      sessionStorage.setItem(redirectKey, 'true');

      // Use external_url (e.g. http://localhost:8080/user/admin/my-server)
      // rather than current page URL (e.g. http://localhost:5173/... in dev)
      const targetUrl = server.external_url || window.location.href;

      // Wait longer for Traefik to pick up the Docker route (5s)
      const timeout = setTimeout(() => {
        window.location.replace(targetUrl);
      }, 5000);
      return () => clearTimeout(timeout);
    }
  }, [server?.status, server?.id, server?.external_url]);

  const handleStart = useCallback(async () => {
    if (!server) return;
    setIsStarting(true);
    try {
      await startServer.mutateAsync(server.id);
      // After starting, begin polling
      queryClient.invalidateQueries({ queryKey: ['server-by-path', username, serverName] });
    } catch {
      setIsStarting(false);
    }
  }, [server, startServer, queryClient, username, serverName]);

  const handleManualOpen = useCallback(() => {
    // Use external_url to go to the actual container (e.g. port 8080 in dev)
    const targetUrl = server?.external_url || window.location.href;
    window.location.href = targetUrl;
  }, [server?.external_url]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="text-center space-y-4"
        >
          <Loader2 className="w-8 h-8 mx-auto animate-spin text-primary" />
          <p className="text-muted-foreground">Checking server status...</p>
        </motion.div>
      </div>
    );
  }

  if (isError || !server) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.gentle}
          className="text-center space-y-4 max-w-md"
        >
          <AlertCircle className="w-12 h-12 mx-auto text-destructive" />
          <h2 className="text-lg font-semibold">Server Not Found</h2>
          <p className="text-muted-foreground">
            {error instanceof Error ? error.message : `The server "${serverName}" does not exist or you don't have access.`}
          </p>
          <Link
            to="/servers"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Servers
          </Link>
        </motion.div>
      </div>
    );
  }

  // Server is running - either redirecting or show manual open button
  if (server.status === 'running') {
    if (manualOpenReady) {
      return (
        <div className="min-h-screen flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={springs.gentle}
            className="text-center space-y-6 max-w-md w-full"
          >
            <div className="space-y-2">
              <CheckCircle2 className="w-12 h-12 mx-auto text-emerald-400" />
              <h1 className="text-xl font-bold">{server.name}</h1>
              <p className="text-sm text-muted-foreground">
                @{username}
              </p>
            </div>

            <div className="bubble p-6 space-y-4">
              <div className="flex items-center justify-center gap-2">
                <StatusBadge status="running" pulse />
              </div>

              <p className="text-sm text-muted-foreground">
                Your server is running. Click below to access it.
              </p>

              <button
                onClick={handleManualOpen}
                className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 transition-colors cursor-pointer"
              >
                <ExternalLink className="w-4 h-4" />
                Open Server
              </button>
            </div>

            <div className="flex items-center justify-center gap-4 text-sm">
              <Link
                to="/servers"
                className="inline-flex items-center gap-1 text-muted-foreground hover:text-primary transition-colors"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                All Servers
              </Link>
              <Link
                to="/servers/$serverId"
                params={{ serverId: server.id }}
                className="inline-flex items-center gap-1 text-muted-foreground hover:text-primary transition-colors"
              >
                <ExternalLink className="w-3.5 h-3.5" />
                Details
              </Link>
            </div>
          </motion.div>
        </div>
      );
    }

    // First time - show redirecting message with longer wait
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="text-center space-y-4 max-w-md"
        >
          <Loader2 className="w-8 h-8 mx-auto animate-spin text-primary" />
          <p className="font-medium">Server is ready</p>
          <p className="text-sm text-muted-foreground">
            Waiting for routing to activate... This may take a few seconds.
          </p>
          <div className="h-1 bg-muted rounded-full overflow-hidden w-48 mx-auto">
            <motion.div
              className="h-full bg-primary rounded-full"
              initial={{ width: '0%' }}
              animate={{ width: '100%' }}
              transition={{ duration: 5, ease: 'linear' }}
            />
          </div>
        </motion.div>
      </div>
    );
  }

  // Server is starting/pending
  if (server.status === 'pending' || server.status === 'error' || isStarting) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={springs.gentle}
          className="text-center space-y-6 max-w-md w-full"
        >
          <div className="space-y-2">
            <Server className="w-12 h-12 mx-auto text-primary" />
            <h1 className="text-xl font-bold">{server.name}</h1>
            <p className="text-sm text-muted-foreground">
              @{username}
            </p>
          </div>

          <div className="bubble p-6 space-y-4">
            <div className="flex items-center justify-center gap-3">
              <Loader2 className="w-5 h-5 animate-spin text-primary" />
              <span className="font-medium">Starting server...</span>
            </div>

            <div className="space-y-2">
              <div className="h-2 bg-muted rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-primary rounded-full"
                  initial={{ width: '0%' }}
                  animate={{ width: `${Math.min(pollCount * 10, 90)}%` }}
                  transition={{ duration: 0.5 }}
                />
              </div>
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Provisioning container</span>
                <span>{elapsedSeconds}s</span>
              </div>
            </div>

            <div className="text-sm text-muted-foreground space-y-1">
              <p>Polling status every 2 seconds...</p>
              <p className="text-xs">The page will automatically redirect when the server is ready.</p>
            </div>
          </div>

          <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
            <RefreshCw className="w-3 h-3" />
            <span>Status: {server.status}</span>
            {pollCount > 0 && <span>· Checks: {pollCount}</span>}
          </div>
        </motion.div>
      </div>
    );
  }

  // Server is stopped - show start option
  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={springs.gentle}
        className="text-center space-y-6 max-w-md w-full"
      >
        <div className="space-y-2">
          <Server className="w-12 h-12 mx-auto text-muted-foreground" />
          <h1 className="text-xl font-bold">{server.name}</h1>
          <p className="text-sm text-muted-foreground">
            @{username}
          </p>
        </div>

        <div className="bubble p-6 space-y-4">
          <div className="flex items-center justify-center gap-2">
            <StatusBadge status="stopped" />
          </div>

          <p className="text-sm text-muted-foreground">
            This server is currently stopped. Start it to access your environment.
          </p>

          {server.external_url && (
            <div className="text-xs text-muted-foreground font-mono break-all">
              {server.external_url}
            </div>
          )}

          <button
            onClick={handleStart}
            disabled={startServer.isPending || isStarting}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium text-sm hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {startServer.isPending || isStarting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Starting...
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                Start Server
              </>
            )}
          </button>
        </div>

        <div className="flex items-center justify-center gap-4 text-sm">
          <Link
            to="/servers"
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-primary transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            All Servers
          </Link>
          <Link
            to="/servers/$serverId"
            params={{ serverId: server.id }}
            className="inline-flex items-center gap-1 text-muted-foreground hover:text-primary transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            Details
          </Link>
        </div>

        {server.created_at && (
          <p className="text-xs text-muted-foreground">
            Created {formatDate(server.created_at)}
          </p>
        )}
      </motion.div>
    </div>
  );
}
