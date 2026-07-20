// Service Worker — PWA offline support (v3 — clear all cache)
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => {
    e.waitUntil(caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k)))));
    self.clients.claim();
});
self.addEventListener('fetch', e => { return; });
