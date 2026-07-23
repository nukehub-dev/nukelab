// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useCallback, useEffect, useRef, useState } from 'react'
import { refreshAccessToken } from '../lib/api'

// If no message arrived for this long when the page becomes visible again,
// assume the socket is a zombie (mobile OS/proxy dropped it silently).
const ZOMBIE_THRESHOLD_MS = 90_000

export interface WebSocketMessage {
  event: string
  data: unknown
  scope?: string
  target_id?: string
  message?: string
}

type MessageHandler = (message: WebSocketMessage) => void

interface UseWebSocketOptions {
  url?: string
  autoConnect?: boolean
  reconnectInterval?: number
  maxReconnectAttempts?: number
}

function getToken(): string {
  return localStorage.getItem('nukelab-token') || ''
}

function getDefaultWebSocketUrl(): string {
  const apiUrl = import.meta.env.VITE_API_URL as string | undefined

  if (apiUrl) {
    // VITE_API_URL is set (e.g. http://localhost:8000/api)
    // Convert to WebSocket URL: ws://localhost:8000/api/ws
    const httpUrl = apiUrl.replace(/\/+$/, '') // trim trailing slashes
    const wsProtocol = httpUrl.startsWith('https:') ? 'wss:' : 'ws:'
    const rest = httpUrl.replace(/^https?:/, '')
    // Keep the /api prefix since the WS endpoint is at /api/ws
    const hostPart = rest.replace(/\/api$/, '')
    return `${wsProtocol}${hostPart}/api/ws`
  }

  // Development fallback: when running via Vite dev server (port 5173),
  // connect directly to the backend on port 8080 (Traefik/proxy)
  const isLocalhost =
    window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  const host = isLocalhost ? 'localhost:8080' : window.location.host
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${host}/api/ws`
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const {
    url: explicitUrl,
    autoConnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 5,
  } = options

  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const handlersRef = useRef<Set<MessageHandler>>(new Set())
  const shouldReconnectRef = useRef(true)
  const isConnectingRef = useRef(false)
  const lastMessageAtRef = useRef(0)
  const authFailedRef = useRef(false)

  const connectRef = useRef<() => void>(() => {})

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    if (isConnectingRef.current) return

    // Build URL fresh each time so token changes are picked up on reconnect
    const url = explicitUrl || getDefaultWebSocketUrl()

    isConnectingRef.current = true
    setIsConnecting(true)
    setError(null)

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        // Send auth message immediately — token never goes in the URL
        const token = getToken()
        if (token) {
          ws.send(JSON.stringify({ type: 'auth', token }))
        }
      }

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as WebSocketMessage
          lastMessageAtRef.current = Date.now()

          // Handle auth handshake before dispatching to consumers
          if (message.event === 'auth:success') {
            authFailedRef.current = false
            isConnectingRef.current = false
            setIsConnected(true)
            setIsConnecting(false)
            setError(null)
            reconnectAttemptsRef.current = 0
            return
          }
          if (message.event === 'auth:error') {
            authFailedRef.current = true
            setError('Authentication failed')
            setIsConnecting(false)
            ws.close()
            return
          }

          handlersRef.current.forEach((handler) => {
            try {
              handler(message)
            } catch (err) {
              console.error('WebSocket message handler error:', err)
            }
          })
        } catch (err) {
          console.error('Failed to parse WebSocket message:', err)
        }
      }

      ws.onerror = () => {
        isConnectingRef.current = false
        setError('WebSocket connection error')
        setIsConnecting(false)
      }

      ws.onclose = (e) => {
        isConnectingRef.current = false
        setIsConnected(false)
        setIsConnecting(false)
        // Only clear the ref if this is still the current socket — a stale
        // onclose from an abandoned socket must not clobber its replacement.
        if (wsRef.current === ws) wsRef.current = null

        // Auth failure: the token may simply be expired. The REST layer
        // renews tokens transparently — do the same here instead of giving
        // up permanently (which previously required a page refresh).
        if (e.code === 4001 || authFailedRef.current) {
          authFailedRef.current = false
          setError('Authentication required')
          if (shouldReconnectRef.current) {
            void refreshAccessToken().then((refreshed) => {
              if (refreshed && shouldReconnectRef.current) {
                reconnectAttemptsRef.current = 0
                reconnectTimerRef.current = setTimeout(() => {
                  connectRef.current()
                }, 1000)
              }
            })
          }
          return
        }

        if (shouldReconnectRef.current && reconnectAttemptsRef.current < maxReconnectAttempts) {
          reconnectAttemptsRef.current += 1
          reconnectTimerRef.current = setTimeout(() => {
            connectRef.current()
          }, reconnectInterval)
        }
      }
    } catch (err) {
      isConnectingRef.current = false
      setError(err instanceof Error ? err.message : 'Failed to connect')
      setIsConnecting(false)
    }
  }, [explicitUrl, reconnectInterval, maxReconnectAttempts])

  useEffect(() => {
    connectRef.current = connect
  }, [connect])

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setIsConnected(false)
  }, [])

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
      return true
    }
    return false
  }, [])

  const subscribe = useCallback(
    (scope: string, targetId?: string) => {
      send({ type: 'subscribe', scope, target_id: targetId })
    },
    [send]
  )

  const unsubscribe = useCallback(
    (scope: string, targetId?: string) => {
      send({ type: 'unsubscribe', scope, target_id: targetId })
    },
    [send]
  )

  const onMessage = useCallback((handler: MessageHandler) => {
    handlersRef.current.add(handler)
    return () => {
      handlersRef.current.delete(handler)
    }
  }, [])

  useEffect(() => {
    if (autoConnect) {
      shouldReconnectRef.current = true
      queueMicrotask(connect)
    }

    return () => {
      disconnect()
    }
  }, [autoConnect, connect, disconnect])

  // Recover from silently-dead connections. Mobile browsers suspend
  // background tabs and the OS/proxy drops the socket — often without
  // firing onclose — leaving isConnected stuck at true with no traffic.
  // Re-check the connection when the page becomes visible or the network
  // returns, and clear the exhausted-retry state so recovery isn't blocked.
  useEffect(() => {
    if (!autoConnect) return

    const recover = () => {
      if (isConnectingRef.current) return
      reconnectAttemptsRef.current = 0
      shouldReconnectRef.current = true

      const ws = wsRef.current
      if (ws) {
        if (ws.readyState === WebSocket.OPEN) {
          // Socket looks open but may be a zombie: force a reconnect if
          // no message arrived for a while (system metrics publish every
          // 60s, container metrics every 5s).
          if (Date.now() - lastMessageAtRef.current > ZOMBIE_THRESHOLD_MS) {
            ws.close()
          }
          return
        }
        if (ws.readyState !== WebSocket.CLOSED) return // CONNECTING/CLOSING — let it settle
      }
      connectRef.current()
    }

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') recover()
    }

    document.addEventListener('visibilitychange', handleVisibility)
    window.addEventListener('online', recover)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility)
      window.removeEventListener('online', recover)
    }
  }, [autoConnect])

  return {
    isConnected,
    isConnecting,
    error,
    connect,
    disconnect,
    send,
    subscribe,
    unsubscribe,
    onMessage,
  }
}
