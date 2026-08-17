// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

/**
 * Register the NukeLab service worker in production builds.
 *
 * The service worker is intentionally disabled in development to avoid
 * intercepting Vite's HMR and serving stale assets. It also never intercepts
 * /api, /ws, /grafana, /prometheus, /alertmanager, or /jaeger.
 *
 * Push notifications can be enabled in dev by setting
 * `VITE_ENABLE_PUSH_IN_DEV=true` — useful for testing Web Push locally.
 */

const enablePushInDev = import.meta.env.VITE_ENABLE_PUSH_IN_DEV === 'true'

export function registerServiceWorker() {
  if (import.meta.env.DEV && !enablePushInDev) return
  if (!('serviceWorker' in navigator)) return

  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then((registration) => {
        console.log('SW registered:', registration.scope)
      })
      .catch((error) => {
        console.error('SW registration failed:', error)
      })
  })
}

interface PushSubscriptionKeys {
  p256dh: string
  auth: string
}

interface PushSubscriptionInfo {
  endpoint: string
  keys: PushSubscriptionKeys
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = window.atob(base64)
  const outputArray = new Uint8Array(rawData.length)
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return outputArray
}

const SW_ACTIVATION_TIMEOUT_MS = 10_000

/**
 * Resolve an active service worker registration without hanging forever.
 *
 * `navigator.serviceWorker.ready` never resolves when no worker is
 * registered — which happens in dev (auto-registration is skipped) or when
 * page-load registration has not run yet. Optionally register on demand, and
 * bound the activation wait with a timeout so callers cannot hang.
 */
async function resolveRegistration(
  registerIfMissing: boolean
): Promise<ServiceWorkerRegistration | null> {
  let registration = await navigator.serviceWorker.getRegistration()
  if (!registration && registerIfMissing) {
    registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
  }
  if (!registration) return null

  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise<never>((_, reject) =>
      setTimeout(
        () => reject(new Error('Service worker activation timed out')),
        SW_ACTIVATION_TIMEOUT_MS
      )
    ),
  ])
}

/**
 * Request browser notification permission and subscribe to push.
 * Must be called from a user gesture.
 */
export async function subscribePush(
  publicKey: string,
  saveSubscription: (sub: PushSubscriptionInfo) => Promise<void>
): Promise<PushSubscriptionInfo | null> {
  if (!('serviceWorker' in navigator)) {
    throw new Error('Service workers are not supported')
  }
  if (!('PushManager' in window)) {
    throw new Error('Push notifications are not supported')
  }

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    throw new Error(`Notification permission ${permission}`)
  }

  const registration = await resolveRegistration(true)
  if (!registration) {
    throw new Error('Service worker is not available')
  }
  const applicationServerKey = urlBase64ToUint8Array(publicKey)

  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: applicationServerKey as BufferSource,
  })

  const subJson = subscription.toJSON()
  if (!subJson.endpoint || !subJson.keys?.p256dh || !subJson.keys?.auth) {
    throw new Error('Invalid push subscription')
  }

  const info: PushSubscriptionInfo = {
    endpoint: subJson.endpoint,
    keys: {
      p256dh: subJson.keys.p256dh,
      auth: subJson.keys.auth,
    },
  }

  await saveSubscription(info)
  return info
}

/**
 * Unsubscribe from push notifications.
 */
export async function unsubscribePush(
  removeSubscription: (endpoint: string) => Promise<void>
): Promise<void> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    return
  }

  const registration = await resolveRegistration(false)
  if (!registration) return
  const subscription = await registration.pushManager.getSubscription()
  if (!subscription) return

  await subscription.unsubscribe()
  const subJson = subscription.toJSON()
  if (subJson.endpoint) {
    await removeSubscription(subJson.endpoint)
  }
}

/**
 * Return the current push subscription if any.
 */
export async function getPushSubscription(): Promise<PushSubscriptionInfo | null> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    return null
  }

  const registration = await resolveRegistration(false)
  if (!registration) return null
  const subscription = await registration.pushManager.getSubscription()
  if (!subscription) return null

  const subJson = subscription.toJSON()
  if (!subJson.endpoint || !subJson.keys?.p256dh || !subJson.keys?.auth) {
    return null
  }

  return {
    endpoint: subJson.endpoint,
    keys: {
      p256dh: subJson.keys.p256dh,
      auth: subJson.keys.auth,
    },
  }
}
