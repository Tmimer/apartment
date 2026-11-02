// Service Worker for Shared Apartment Hub (Tamir & Mikush)
const CACHE_NAME = 'apartment-hub-v5';
const ASSETS_TO_CACHE = [
  '/',
  '/login',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS_TO_CACHE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
    ))
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  // Network first for HTML navigations, fallback to cached shell
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match('/') || caches.match('/login'))
    );
    return;
  }

  // Cache first with network fallback for static icons/manifest
  if (e.request.url.includes('/icon-') || e.request.url.includes('/manifest.json')) {
    e.respondWith(
      caches.match(e.request).then((cached) => cached || fetch(e.request))
    );
    return;
  }

  // Network first for APIs and dynamic data
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});

// Push notification listener
self.addEventListener('push', (event) => {
  let data = {
    title: "🏠 Apartment Hub",
    body: "You have an apartment notification!",
    url: "/"
  };

  if (event.data) {
    try {
      data = Object.assign(data, event.data.json());
    } catch (err) {
      data.body = event.data.text();
    }
  }

  const options = {
    body: data.body,
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    vibrate: [200, 100, 200],
    tag: 'apartment-notification',
    renotify: true,
    data: {
      url: data.url || '/'
    },
    actions: [
      { action: 'open', title: 'Open Hub' }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// Click notification listener
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes(self.location.origin) && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
