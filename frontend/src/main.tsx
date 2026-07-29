// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createRouter } from '@tanstack/react-router'
import { MotionConfig } from 'framer-motion'
import { routeTree } from './routeTree.gen'
import { queryClient } from './lib/api'
import { initSentry } from './lib/sentry'
import { ErrorBoundary } from './components/feedback/error-boundary'
import { NotFound } from './components/feedback/not-found'
import { registerServiceWorker } from './lib/register-sw'
import './styles/index.css'

// Initialize Sentry error tracking (loaded lazily, see lib/sentry.ts)
initSentry()

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

// Handle deep-link redirects from server containers that returned 401.
// Server nginx redirects browser page loads to /?next=<original-path> so the
// SPA can run the gateway flow, acquire a server access token, and redirect
// back to the original server URL. Unauthenticated users are sent to login
// with the same next parameter preserved.
const searchParams = new URLSearchParams(window.location.search)
const nextPath = searchParams.get('next')
if (nextPath && nextPath.startsWith('/') && !nextPath.startsWith('//')) {
  const cleanUrl = new URL(window.location.href)
  cleanUrl.searchParams.delete('next')
  window.history.replaceState({}, '', cleanUrl.toString())

  const token = localStorage.getItem('nukelab-token')
  if (token) {
    router.navigate({ to: nextPath }).catch(() => {
      // Navigation failures fall through to RouterProvider's route matching.
    })
  } else {
    router.navigate({ to: '/login', search: { next: nextPath } }).catch(() => {
      // Fall through to the login route if navigation fails.
    })
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        {/* Honor the OS reduced-motion setting for all framer-motion animations */}
        <MotionConfig reducedMotion="user">
          <RouterProvider router={router} />
        </MotionConfig>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>
)

registerServiceWorker()
