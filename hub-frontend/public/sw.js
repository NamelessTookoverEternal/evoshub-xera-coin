/* Evos Hub service worker.
   - HTML pages: network-first (so deploys are never served stale), cached copy as offline fallback.
   - Static assets (/assets/*): stale-while-revalidate.
   - Never touches non-GET, cross-origin, or /api requests (auth, payments, Supabase stay live). */
const VERSION = 'evoshub-v1'
const SHELL = ['/appevoxera', '/assets/images/evoxera.png', '/assets/icons/icon-192.png']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(VERSION)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
      .catch(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/') || url.pathname === '/sw.js') return

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)) }
          return res
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match('/appevoxera')))
    )
    return
  }

  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.open(VERSION).then((cache) =>
        cache.match(req).then((hit) => {
          const network = fetch(req)
            .then((res) => { if (res.ok) cache.put(req, res.clone()); return res })
            .catch(() => hit)
          return hit || network
        })
      )
    )
  }
})
