// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { createFileRoute, Link } from '@tanstack/react-router'
import { useState, useEffect, useCallback, useRef } from 'react'
import { motion } from 'framer-motion'
import {
  Server,
  ArrowLeft,
  Play,
  Loader2,
  ExternalLink,
  AlertCircle,
  CheckCircle2,
  Cpu,
  MemoryStick,
  HardDrive,
  Globe,
  Zap,
  ChevronRight,
  Terminal,
  Sparkles,
} from 'lucide-react'
import { useServerByPath } from '../hooks/use-servers'
import { useServerActionsWithReason } from '../hooks/use-server-actions-with-reason'
import { useAuthStore } from '../stores/auth-store'
import { StatusBadge } from '../components/data/status-badge'
import { Card, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'

import { formatDate, cn } from '../lib/utils'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'

const API_BASE = import.meta.env.VITE_API_URL || '/api'
const ACTIVITY_HEARTBEAT_INTERVAL_MS = 30_000

async function getServerAccessToken(serverId: string, reason?: string): Promise<void> {
  const token = localStorage.getItem('nukelab-token') || ''
  const response = await fetch(`${API_BASE}/servers/${serverId}/access-token`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ reason }),
    credentials: 'include',
  })
  if (!response.ok) {
    const body = await response.text().catch(() => '')
    throw new Error(body || `Token request failed (${response.status})`)
  }
}

async function pingServerActivity(serverId: string): Promise<void> {
  try {
    await api.post(`/servers/${serverId}/activity`, {})
  } catch {
    // Activity pings are best-effort; don't surface failures to the user.
  }
}

async function ensureServiceWorkerUpdated(): Promise<void> {
  // Browsers with a stale service worker may serve the cached SPA shell for
  // /user/ routes instead of letting the request reach the terminal container.
  // Force an update and activate any waiting worker before we navigate.
  if (!('serviceWorker' in navigator)) return
  try {
    const registration = await navigator.serviceWorker.ready
    await registration.update()
    if (registration.waiting) {
      registration.waiting.postMessage({ type: 'SKIP_WAITING' })
      // Give the new worker a moment to activate and claim this client.
      await new Promise((resolve) => setTimeout(resolve, 300))
    }
  } catch {
    // Best-effort; don't block navigation if the SW API misbehaves.
  }
}

export const Route = createFileRoute('/user/$username/$serverName')({
  component: ServerGatewayPage,
})

// Animation variants
const containerVariants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.08, delayChildren: 0.1 },
  },
}

const itemVariants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { type: 'spring', stiffness: 400, damping: 28 } },
}

const pulseRingVariants = {
  initial: { scale: 0.8, opacity: 0.6 },
  animate: {
    scale: [0.8, 1.4, 0.8],
    opacity: [0.6, 0, 0.6],
    transition: { duration: 2.5, repeat: Infinity, ease: 'easeInOut' },
  },
}

const stepItems = [
  { icon: Terminal, label: 'Provisioning container', threshold: 0 },
  { icon: Zap, label: 'Starting services', threshold: 30 },
  { icon: Globe, label: 'Activating routing', threshold: 60 },
  { icon: Sparkles, label: 'Ready', threshold: 90 },
]

function StepIndicator({ progress }: { progress: number }) {
  return (
    <div className="space-y-3">
      {stepItems.map((step, i) => {
        const isActive = progress >= step.threshold
        const isCurrent =
          progress >= step.threshold &&
          (i === stepItems.length - 1 || progress < stepItems[i + 1].threshold)
        return (
          <motion.div
            key={step.label}
            className="flex items-center gap-3"
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: isActive ? 1 : 0.4, x: 0 }}
            transition={{ delay: i * 0.1 }}
          >
            <div
              className={cn(
                'w-6 h-6 rounded-full flex items-center justify-center transition-colors duration-500',
                isActive ? 'bg-primary/20' : 'bg-muted',
                isCurrent && 'ring-2 ring-primary/50'
              )}
            >
              {isActive ? (
                <CheckCircle2
                  className={cn(
                    'w-3.5 h-3.5',
                    isCurrent ? 'text-primary animate-pulse' : 'text-primary'
                  )}
                />
              ) : (
                <step.icon className="w-3.5 h-3.5 text-muted-foreground" />
              )}
            </div>
            <span
              className={cn(
                'text-sm transition-colors duration-500',
                isActive ? 'text-foreground' : 'text-muted-foreground'
              )}
            >
              {step.label}
            </span>
            {isCurrent && (
              <motion.div
                className="ml-auto"
                animate={{ opacity: [0.4, 1, 0.4] }}
                transition={{ duration: 1.5, repeat: Infinity }}
              >
                <ChevronRight className="w-4 h-4 text-primary" />
              </motion.div>
            )}
          </motion.div>
        )
      })}
    </div>
  )
}

function ServerInfoHeader({
  server,
  username,
}: {
  server: { name: string; username?: string }
  username: string
}) {
  return (
    <motion.div variants={itemVariants} className="text-center space-y-2">
      <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-primary/10 mb-2">
        <Server className="w-7 h-7 text-primary" />
      </div>
      <h1 className="text-2xl font-bold tracking-tight">{server.name}</h1>
      <p className="text-sm text-muted-foreground">@{username}</p>
    </motion.div>
  )
}

function ServerSpecs({
  server,
}: {
  server: { allocated_cpu?: number; allocated_memory?: string; allocated_disk?: string }
}) {
  const specs = [
    {
      icon: Cpu,
      label: 'CPU',
      value: server.allocated_cpu ? `${server.allocated_cpu} cores` : '—',
    },
    { icon: MemoryStick, label: 'Memory', value: server.allocated_memory || '—' },
    { icon: HardDrive, label: 'Storage', value: server.allocated_disk || '—' },
  ]

  return (
    <motion.div variants={itemVariants} className="grid grid-cols-1 sm:grid-cols-3 gap-2">
      {specs.map((spec) => (
        <div key={spec.label} className="text-center p-3 rounded-xl bg-muted/50">
          <spec.icon className="w-4 h-4 mx-auto text-muted-foreground mb-1" />
          <p className="text-xs font-medium">{spec.value}</p>
          <p className="text-[10px] text-muted-foreground">{spec.label}</p>
        </div>
      ))}
    </motion.div>
  )
}

function LoadingState() {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        className="text-center space-y-6 max-w-sm w-full"
      >
        <motion.div variants={itemVariants} className="relative inline-flex">
          <motion.div
            className="absolute inset-0 rounded-full bg-primary/20"
            variants={pulseRingVariants}
            initial="initial"
            animate="animate"
          />
          <div className="relative w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center">
            <Loader2 className="w-7 h-7 animate-spin text-primary" />
          </div>
        </motion.div>
        <motion.p variants={itemVariants} className="text-muted-foreground">
          Checking server status...
        </motion.p>
      </motion.div>
    </div>
  )
}

function ErrorState({ serverName, error }: { serverName: string; error: Error | null }) {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        className="text-center space-y-6 max-w-md w-full"
      >
        <motion.div variants={itemVariants}>
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-destructive/10 mb-2">
            <AlertCircle className="w-8 h-8 text-destructive" />
          </div>
        </motion.div>
        <motion.div variants={itemVariants} className="space-y-2">
          <h2 className="text-xl font-semibold">Server Not Found</h2>
          <p className="text-sm text-muted-foreground">
            {error instanceof Error
              ? error.message
              : `The server "${serverName}" does not exist or you don't have access.`}
          </p>
        </motion.div>
        <motion.div variants={itemVariants}>
          <Link to="/servers">
            <Button variant="default" className="gap-2">
              <ArrowLeft className="w-4 h-4" />
              Back to Servers
            </Button>
          </Link>
        </motion.div>
      </motion.div>
    </div>
  )
}

function RunningRedirectState({ server }: { server: { name: string } }) {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        className="text-center space-y-6 max-w-sm w-full"
      >
        <motion.div variants={itemVariants} className="relative inline-flex">
          <motion.div
            className="absolute inset-0 rounded-full bg-primary/20"
            variants={pulseRingVariants}
            initial="initial"
            animate="animate"
          />
          <motion.div
            className="absolute inset-0 rounded-full bg-primary/10"
            animate={{ scale: [1, 1.6, 1], opacity: [0.5, 0, 0.5] }}
            transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut', delay: 0.3 }}
          />
          <div className="relative w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center">
            <CheckCircle2 className="w-7 h-7 text-primary" />
          </div>
        </motion.div>

        <motion.div variants={itemVariants} className="space-y-1">
          <p className="font-semibold text-lg">{server.name} is ready</p>
          <p className="text-sm text-muted-foreground">Opening your environment...</p>
        </motion.div>

        <motion.div
          variants={itemVariants}
          className="h-1.5 bg-muted rounded-full overflow-hidden w-56 mx-auto"
        >
          <motion.div
            className="h-full bg-primary rounded-full"
            initial={{ width: '0%' }}
            animate={{ width: '100%' }}
            transition={{ duration: 4, ease: 'linear' }}
          />
        </motion.div>
      </motion.div>
    </div>
  )
}

function ManualOpenState({
  server,
  username,
  onOpen,
  isOpening,
  tokenError,
}: {
  server: {
    id: string
    name: string
    username?: string
    allocated_cpu?: number
    allocated_memory?: string
    allocated_disk?: string
    created_at?: string
  }
  username: string
  onOpen: () => void
  isOpening?: boolean
  tokenError?: string | null
}) {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        className="w-full max-w-md space-y-6"
      >
        <ServerInfoHeader server={server} username={username} />

        <motion.div variants={itemVariants}>
          <Card variant="bubble">
            <CardContent className="p-6 space-y-5">
              <div className="flex items-center justify-center">
                <StatusBadge status="running" pulse size="md" />
              </div>

              <div className="text-center space-y-1">
                <p className="text-sm text-muted-foreground">
                  Your server is running and ready to use.
                </p>
              </div>

              <Button onClick={onOpen} disabled={isOpening} className="w-full gap-2" size="lg">
                {isOpening ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <ExternalLink className="w-4 h-4" />
                )}
                {isOpening ? 'Opening...' : 'Open Environment'}
              </Button>

              {tokenError && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 space-y-2"
                >
                  <div className="flex items-center gap-2 text-destructive text-sm">
                    <AlertCircle className="w-4 h-4 shrink-0" />
                    <span>Access token error</span>
                  </div>
                  <p className="text-xs text-muted-foreground">{tokenError}</p>
                  <p className="text-xs text-muted-foreground">
                    Try opening the server again, or go to Details to investigate.
                  </p>
                </motion.div>
              )}
            </CardContent>
          </Card>
        </motion.div>

        <ServerSpecs server={server} />

        <motion.div
          variants={itemVariants}
          className="flex items-center justify-center gap-4 text-sm"
        >
          <Link
            to="/servers"
            className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-primary transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            All Servers
          </Link>
          <Link
            to="/servers/$serverId"
            params={{ serverId: server.id }}
            className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-primary transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            Details
          </Link>
        </motion.div>
      </motion.div>
    </div>
  )
}

function StartingState({
  server,
  username,
  pollCount,
  elapsedSeconds,
}: {
  server: {
    name: string
    username?: string
    status: string
    allocated_cpu?: number
    allocated_memory?: string
    allocated_disk?: string
  }
  username: string
  pollCount: number
  elapsedSeconds: number
}) {
  const progress = Math.min(pollCount * 10, 85)

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        className="w-full max-w-md space-y-6"
      >
        <ServerInfoHeader server={server} username={username} />

        <motion.div variants={itemVariants}>
          <Card variant="bubble">
            <CardContent className="p-6 space-y-5">
              <div className="flex items-center justify-center gap-3">
                <div className="relative">
                  <motion.div
                    className="absolute inset-0 rounded-full bg-primary/20"
                    animate={{ scale: [1, 1.5, 1], opacity: [0.5, 0, 0.5] }}
                    transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
                  />
                  <div className="relative w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                    <Loader2 className="w-5 h-5 animate-spin text-primary" />
                  </div>
                </div>
                <span className="font-medium">Starting server...</span>
              </div>

              <div className="space-y-3">
                <div className="h-2 bg-muted rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-primary rounded-full"
                    initial={{ width: '0%' }}
                    animate={{ width: `${progress}%` }}
                    transition={{ duration: 0.5, ease: 'easeOut' }}
                  />
                </div>
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>{elapsedSeconds}s elapsed</span>
                  <span>{pollCount} checks</span>
                </div>
              </div>

              <StepIndicator progress={progress} />
            </CardContent>
          </Card>
        </motion.div>

        <motion.div variants={itemVariants} className="text-center">
          <p className="text-xs text-muted-foreground">
            The page will automatically redirect when the server is ready.
          </p>
        </motion.div>
      </motion.div>
    </div>
  )
}

function StoppedState({
  server,
  username,
  onStart,
  isStarting,
}: {
  server: {
    id: string
    name: string
    username?: string
    status: string
    external_url?: string
    allocated_cpu?: number
    allocated_memory?: string
    allocated_disk?: string
    created_at?: string
  }
  username: string
  onStart: () => void
  isStarting: boolean
}) {
  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        className="w-full max-w-md space-y-6"
      >
        <ServerInfoHeader server={server} username={username} />

        <motion.div variants={itemVariants}>
          <Card variant="bubble">
            <CardContent className="p-6 space-y-5">
              <div className="flex items-center justify-center">
                <StatusBadge status="stopped" size="md" />
              </div>

              <div className="text-center space-y-1">
                <p className="text-sm text-muted-foreground">
                  This server is currently stopped. Start it to access your environment.
                </p>
                {server.external_url && (
                  <p className="text-xs text-muted-foreground font-mono break-all">
                    {server.external_url}
                  </p>
                )}
              </div>

              <Button onClick={onStart} disabled={isStarting} className="w-full gap-2" size="lg">
                {isStarting ? (
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
              </Button>
            </CardContent>
          </Card>
        </motion.div>

        <ServerSpecs server={server} />

        <motion.div
          variants={itemVariants}
          className="flex items-center justify-center gap-4 text-sm"
        >
          <Link
            to="/servers"
            className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-primary transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            All Servers
          </Link>
          <Link
            to="/servers/$serverId"
            params={{ serverId: server.id }}
            className="inline-flex items-center gap-1.5 text-muted-foreground hover:text-primary transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            Details
          </Link>
        </motion.div>

        {server.created_at && (
          <motion.p variants={itemVariants} className="text-center text-xs text-muted-foreground">
            Created {formatDate(server.created_at)}
          </motion.p>
        )}
      </motion.div>
    </div>
  )
}

function ServerGatewayPage() {
  const { username, serverName } = Route.useParams()
  const { data: server, isLoading, isError, error } = useServerByPath(username, serverName)
  const {
    startServerAsync,
    promptAccessReason,
    dialog: reasonDialog,
  } = useServerActionsWithReason()
  const queryClient = useQueryClient()
  const user = useAuthStore((state) => state.user)
  const isOwnServer = server ? server.user_id === user?.id : true

  const [isStarting, setIsStarting] = useState(false)
  const [pollCount, setPollCount] = useState(0)
  const startTimeRef = useRef<number | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [manualOpenReady, setManualOpenReady] = useState(false)
  const [tokenError, setTokenError] = useState<string | null>(null)
  const [isOpening, setIsOpening] = useState(false)

  useEffect(() => {
    if (server?.status === 'pending' && startTimeRef.current === null) {
      startTimeRef.current = Date.now()
    }
  }, [server?.status])

  useEffect(() => {
    if (server?.status !== 'pending' && !isStarting) {
      return
    }
    const interval = setInterval(() => {
      if (startTimeRef.current) {
        setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000))
      }
    }, 1000)
    return () => clearInterval(interval)
  }, [server?.status, isStarting])

  // Poll server status when it's pending (starting up)
  useEffect(() => {
    if (!server || server.status !== 'pending') {
      return
    }

    const interval = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: ['server-by-path', username, serverName] })
      setPollCount((c) => c + 1)
    }, 2000)

    return () => clearInterval(interval)
  }, [server, username, serverName, queryClient])

  // Keep server last_activity fresh while this gateway page is open and visible.
  // The terminal itself runs outside the SPA, so this complements the access-token
  // refresh that happens each time the user opens/reloads the environment.
  useEffect(() => {
    if (!server || server.status !== 'running') {
      return
    }

    const sendPing = () => {
      if (document.visibilityState === 'visible') {
        void pingServerActivity(server.id)
      }
    }

    // Ping immediately so we refresh activity right away when the page becomes
    // visible with a running server (e.g. returning to the manual-open state).
    sendPing()

    const interval = setInterval(sendPing, ACTIVITY_HEARTBEAT_INTERVAL_MS)
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        sendPing()
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [server])

  // When server transitions to running, get access token and redirect
  useEffect(() => {
    if (server?.status === 'running') {
      const redirectKey = `server-redirect-${server.id}`
      const alreadyRedirected = sessionStorage.getItem(redirectKey)

      if (alreadyRedirected) {
        queueMicrotask(() => setManualOpenReady(true))
        return
      }

      // For cross-user access, don't auto-redirect; show manual open button
      // so user can provide a reason via prompt
      if (!isOwnServer) {
        queueMicrotask(() => setManualOpenReady(true))
        return
      }

      sessionStorage.setItem(redirectKey, 'true')

      const getAccessTokenAndRedirect = async () => {
        try {
          await getServerAccessToken(server.id)
          // Force a real navigation so the service worker bypass for /user/ routes
          // sends the request to the terminal container instead of the SPA shell.
          await ensureServiceWorkerUpdated()
          window.location.href = server.external_url || window.location.href
        } catch (err) {
          setTokenError(err instanceof Error ? err.message : 'Failed to get access token')
          setManualOpenReady(true)
        }
      }

      const timeout = setTimeout(() => {
        getAccessTokenAndRedirect()
      }, 3000)
      return () => clearTimeout(timeout)
    }
  }, [server?.status, server?.id, server?.external_url, isOwnServer])

  const handleStart = useCallback(async () => {
    if (!server) return
    setIsStarting(true)
    try {
      await startServerAsync(server)
      queryClient.invalidateQueries({ queryKey: ['server-by-path', username, serverName] })
    } catch {
      setIsStarting(false)
    }
  }, [server, startServerAsync, queryClient, username, serverName])

  const handleManualOpen = useCallback(async () => {
    const targetUrl = server?.external_url || window.location.href
    let reason: string | undefined
    if (!isOwnServer && server) {
      const entered = await promptAccessReason(server, 'open')
      if (entered === null) return
      reason = entered || undefined
    }

    setIsOpening(true)
    setTokenError(null)

    try {
      if (server?.id) {
        await getServerAccessToken(server.id, reason)
      }
      // Same-tab navigation avoids popup blockers and is consistent with the
      // auto-redirect flow. Update the service worker first so a stale SW does
      // not serve the cached SPA shell for /user/ routes.
      await ensureServiceWorkerUpdated()
      window.location.href = targetUrl
    } catch (err) {
      setIsOpening(false)
      setTokenError(err instanceof Error ? err.message : 'Failed to get access token')
    }
  }, [server, isOwnServer, promptAccessReason])

  if (isLoading) {
    return (
      <>
        <LoadingState />
        {reasonDialog}
      </>
    )
  }

  if (isError || !server) {
    return (
      <>
        <ErrorState serverName={serverName} error={error} />
        {reasonDialog}
      </>
    )
  }

  // Server is running - either redirecting or show manual open button
  if (server.status === 'running') {
    if (manualOpenReady) {
      return (
        <>
          <ManualOpenState
            server={server}
            username={username}
            onOpen={handleManualOpen}
            isOpening={isOpening}
            tokenError={tokenError}
          />
          {reasonDialog}
        </>
      )
    }
    return (
      <>
        <RunningRedirectState server={server} />
        {reasonDialog}
      </>
    )
  }

  // Server is starting/pending
  if (server.status === 'pending' || server.status === 'error' || isStarting) {
    return (
      <>
        <StartingState
          server={server}
          username={username}
          pollCount={pollCount}
          elapsedSeconds={elapsedSeconds}
        />
        {reasonDialog}
      </>
    )
  }

  // Server is stopped - show start option
  return (
    <>
      <StoppedState
        server={server}
        username={username}
        onStart={handleStart}
        isStarting={isStarting || false}
      />
      {reasonDialog}
    </>
  )
}
