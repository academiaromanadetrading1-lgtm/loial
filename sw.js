/* Loial PWA: cache only public static shell/assets; never cache customer data. */
const VERSION = 'loial-pwa-black-metal-v1';
const SHELL = ['/loial-offline.html', '/pwa-icon-192.png', '/pwa-icon-512.png'];
const PUBLIC = new Set(SHELL);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(VERSION).then(cache => cache.addAll(SHELL))
    .then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key !== VERSION && key.startsWith('loial-'))
      .map(key => caches.delete(key))
  )).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Sensitive content: token-authenticated API, dynamic account, referral data,
  // receipt and QR state. Do not read or write any of it to the SW cache.
  if (url.pathname.startsWith('/api/') ||
      url.pathname.startsWith('/gdpr/') ||
      url.pathname.startsWith('/loial-receipt') ||
      url.pathname.startsWith('/wallet-profile/') ||
      url.pathname.startsWith('/wallet-recovery')) return;
  if (PUBLIC.has(url.pathname)) {
    event.respondWith(caches.open(VERSION).then(cache =>
      cache.match(url.pathname).then(hit => hit || fetch(request))));
    return;
  }
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() =>
      caches.open(VERSION).then(cache => cache.match('/loial-offline.html'))));
  }
});