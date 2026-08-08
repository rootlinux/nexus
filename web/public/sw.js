const CACHE_PREFIX = 'nexus-shell';
const CACHE_NAME = `${CACHE_PREFIX}-v3`;
const OFFLINE_URL = '/offline.html';

const APP_SHELL = [
  '/offline.html',
  '/manifest.webmanifest',
  '/icon-192.png',
  '/icon-512.png',
  '/icon-maskable-512.png',
  '/apple-touch-icon.png',
  '/favicon.ico',
];

const IMMUTABLE_PATH_PREFIXES = ['/_next/static/'];
const SAFE_CACHE_PATHS = new Set(APP_SHELL);

function isSafeStaticAsset(request, url) {
  if (request.method !== 'GET' || url.origin !== self.location.origin) {
    return false;
  }

  if (request.cache === 'only-if-cached' && request.mode !== 'same-origin') {
    return false;
  }

  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/_next/data')) {
    return false;
  }

  return (
    SAFE_CACHE_PATHS.has(url.pathname) ||
    IMMUTABLE_PATH_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))
  );
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).catch(() => undefined)
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.map((key) =>
            key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME
              ? caches.delete(key)
              : Promise.resolve()
          )
        )
      )
      .then(async () => {
        if ('navigationPreload' in self.registration) {
          await self.registration.navigationPreload.enable();
        }
      })
      .then(() => self.clients.claim())
  );
});

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('push', (event) => {
  const payload = (() => {
    try {
      return event.data ? event.data.json() : {};
    } catch {
      return { body: event.data ? event.data.text() : '' };
    }
  })();

  const title = payload.title || 'New activity';
  const body = payload.body || payload.message || 'Open the app to catch up.';
  const url = payload.url || payload.path || '/notifications';

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: payload.icon || '/icon-192.png',
      badge: payload.badge || '/icon-192.png',
      tag: payload.tag || undefined,
      data: {
        url,
        notificationId: payload.notification_id || null,
        notificationType: payload.notification_type || null,
      },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const rawTargetUrl = event.notification.data?.url || '/notifications';
  const targetUrl = new URL(rawTargetUrl, self.location.origin).toString();

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client && new URL(client.url).origin === self.location.origin) {
          return client.navigate(targetUrl).then(() => client.focus());
        }
      }

      return self.clients.openWindow(targetUrl);
    })
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/_next/data')) {
    return;
  }

  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(
      (async () => {
        try {
          const preload = await event.preloadResponse;
          if (preload) {
            return preload;
          }
          return await fetch(request);
        } catch {
          const cache = await caches.open(CACHE_NAME);
          return (await cache.match(OFFLINE_URL)) || Response.error();
        }
      })()
    );
    return;
  }

  if (!isSafeStaticAsset(request, url)) {
    return;
  }

  event.respondWith(
    caches.match(request).then(async (cached) => {
      if (cached) {
        return cached;
      }

      const response = await fetch(request);
      if (response && response.ok) {
        const cache = await caches.open(CACHE_NAME);
        cache.put(request, response.clone());
      }
      return response;
    })
  );
});
