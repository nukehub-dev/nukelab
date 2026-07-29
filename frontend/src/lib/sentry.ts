// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

// Sentry is loaded lazily via dynamic import so its ~60 KB of code stays out
// of the initial bundle and off the mobile startup path. `initSentry()` must
// be called once at app startup; because the module promise is cached and
// callbacks run in registration order, init always completes before any
// queued captureException call is flushed.

import type { ErrorEvent } from '@sentry/react'

type SentryModule = typeof import('@sentry/react')

const SENTRY_DSN = import.meta.env.VITE_SENTRY_DSN

let sentryModulePromise: Promise<SentryModule> | null = null

function loadSentry(): Promise<SentryModule> | null {
  if (!SENTRY_DSN) return null
  sentryModulePromise ??= import('@sentry/react')
  return sentryModulePromise
}

export function initSentry() {
  const promise = loadSentry()
  if (!promise) return

  void promise.then((Sentry) => {
    Sentry.init({
      dsn: SENTRY_DSN,
      environment: import.meta.env.MODE || 'development',
      release: import.meta.env.VITE_SENTRY_RELEASE || 'nukelab-frontend@dev',
      integrations: [
        Sentry.browserTracingIntegration(),
        Sentry.replayIntegration({
          maskAllText: true,
          blockAllMedia: true,
          maskAllInputs: true,
        }),
      ],
      tracesSampleRate: 0.01,
      replaysSessionSampleRate: 0.0,
      replaysOnErrorSampleRate: 1.0,
      beforeSend(event: ErrorEvent) {
        // Strip all sensitive headers
        if (event.request?.headers) {
          const headers = event.request.headers as Record<string, string>
          const sensitiveHeaders = ['Authorization', 'Cookie', 'X-CSRF-Token', 'X-Correlation-ID']
          for (const h of sensitiveHeaders) {
            if (headers[h]) headers[h] = '[REDACTED]'
          }
        }
        // Scrub sensitive query params from request URL
        if (event.request?.url) {
          try {
            const url = new URL(event.request.url as string)
            const sensitiveParams = ['refresh_token', 'token', 'password', 'secret', 'api_key']
            for (const p of sensitiveParams) {
              if (url.searchParams.has(p)) {
                url.searchParams.set(p, '[REDACTED]')
              }
            }
            event.request.url = url.toString()
          } catch {
            // ignore invalid URLs
          }
        }
        return event
      },
    })
  })
}

export function captureException(
  error: unknown,
  hint?: Parameters<SentryModule['captureException']>[1]
) {
  void loadSentry()?.then((Sentry) => Sentry.captureException(error, hint))
}
