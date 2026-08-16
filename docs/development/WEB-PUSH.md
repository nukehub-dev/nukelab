# Web Push Notifications

NukeLab can deliver desktop/Android push notifications through the browser's
Push API. This guide covers local setup, key generation, and known limitations.

## Enabling Web Push

1. Generate VAPID keys (base64url format):

   ```bash
   npx web-push generate-vapid-keys
   ```

2. Add the keys to your environment:

   ```bash
   VAPID_PUBLIC_KEY=<public-key>
   VAPID_PRIVATE_KEY=<private-key>
   VAPID_SUBJECT=mailto:admin@example.com
   ```

   In development use `.env.development`; in production use `.env.production`.

3. Pass the same variables to the `celery-worker` container in `compose.yml`.
   Background tasks run in the worker, not the API container, so missing
   variables there silently disable push while in-app notifications still work.

4. Restart the stack:

   ```bash
   ./nukelabctl down
   ./nukelabctl up dev
   ```

5. In the browser, opt in from **Settings → Notifications**.

## Service worker

`frontend/public/sw.js.tpl` contains the `push` and `notificationclick`
handlers. `frontend/public/sw.js` is generated at build time by
`scripts/inject-sw-cache.cjs`; edit the template, not the generated file.

## Development testing

By default the service worker is disabled in development to avoid intercepting
Vite HMR. Set `VITE_ENABLE_PUSH_IN_DEV=true` to register it locally for push
testing:

```bash
VITE_ENABLE_PUSH_IN_DEV=true ./nukelabctl up dev
```

## Payload limits

Push payloads are capped to ~2 KB and contain only `title`, a short `body`
preview, and the notification `action_url`. The full message text is never sent;
users must open the app to read the complete notification.

## Dead subscriptions

The worker removes push subscriptions that return HTTP `404` or `410`.

## iOS limitation

Safari on iOS only delivers push notifications when the PWA is installed to the
home screen. Users who have not installed the app will not receive pushes.

## Verification

- `./nukelabctl lint all`
- `./nukelabctl test backend tests/services/test_push_notifications.py tests/api/test_push.py`
- `cd frontend && npm run build` (compiles the generated service worker)
