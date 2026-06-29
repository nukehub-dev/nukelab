// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createRouter } from '@tanstack/react-router'
import * as Sentry from '@sentry/react'
import { routeTree } from './routeTree.gen'
import { queryClient } from './lib/api'
import { ErrorBoundary } from './components/feedback/error-boundary'
import { NotFound } from './components/feedback/not-found'
import { registerServiceWorker } from './lib/register-sw'
import './styles/index.css'

// Initialize Sentry error tracking
const SENTRY_DSN = import.meta.env.VITE_SENTRY_DSN
if (SENTRY_DSN) {
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
    tracesSampleRate: 0.1,
    replaysSessionSampleRate: 0.0,
    replaysOnErrorSampleRate: 1.0,
    beforeSend(event: Sentry.ErrorEvent) {
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
}

const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: 'intent',
  defaultPreloadStaleTime: 0,
  defaultNotFoundComponent: () => <NotFound />,
  defaultErrorComponent: () => (
    <ErrorBoundary>
      <div className="p-8 text-center">
        <h2 className="text-lg font-semibold mb-2">Failed to load page</h2>
        <p className="text-sm text-muted-foreground">
          There was an error loading this page. Please try again.
        </p>
      </div>
    </ErrorBoundary>
  ),
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>
)

registerServiceWorker()
