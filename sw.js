// Service Worker for Tmimer's Plants PWA
const CACHE_NAME = 'plant-tracker-v3';
const ASSETS_TO_CACHE = [
  '/plants',
  '/plants/manifest.json',
  '/plants/icon-192.png',
  '/plants/icon-512.png'
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
  // Network first, fallback to cache for HTML shell
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match('/plants'))
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then((cached) => cached || fetch(e.request))
  );
});

// Push notification listener
self.addEventListener('push', (event) => {
  let data = {
    title: "🌿 Tmimer's Plants",
    body: "One of your plants is due for watering!",
    url: "/plants"
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
    icon: '/plants/icon-192.png',
    badge: '/plants/icon-192.png',
    vibrate: [200, 100, 200],
    tag: 'plant-watering-alert',
    renotify: true,
    data: {
      url: data.url || '/plants'
    },
    actions: [
      { action: 'open', title: 'Open Tracker' }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// Click notification listener
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/plants';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url.includes('/plants') && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
