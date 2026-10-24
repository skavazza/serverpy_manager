// Cache only the generic offline screen. Files, listings and APIs always use the network.
const CACHE = 'serverpy-pwa-v1';
const OFFLINE = '/_serverpy/pwa/offline.html';
self.addEventListener('install', event => {
    event.waitUntil((async () => {
        const response = await fetch(OFFLINE, {cache: 'reload'});
        if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) {
            throw new Error('Unable to load the offline screen');
        }
        const cache = await caches.open(CACHE);
        await cache.put(OFFLINE, response);
        await self.skipWaiting();
    })());
});
self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        for (const key of await caches.keys()) {
            if (key.startsWith('serverpy-pwa-') && key !== CACHE) await caches.delete(key);
        }
        await self.clients.claim();
    })());
});
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);
    if (event.request.method !== 'GET' || event.request.mode !== 'navigate' ||
        url.origin !== self.location.origin || !url.pathname.endsWith('/') ||
        url.pathname.startsWith('/api/') || url.pathname.startsWith('/_serverpy/')) return;
    event.respondWith((async () => {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 8000);
        try {
            // Preserve HTTP errors (including 401/403); never substitute cached listings.
            return await fetch(event.request, {cache: 'no-store', signal: controller.signal});
        } catch {
            const cache = await caches.open(CACHE);
            return await cache.match(OFFLINE) || Response.error();
        } finally {
            clearTimeout(timer);
        }
    })());
});
