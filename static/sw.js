/**
 * Service Worker minimal pour ML Info.
 * Permet l'installation sur Android (Chrome) et un fallback offline basique.
 *
 * Stratégie :
 *   - Précache des assets statiques au moment de l'install
 *   - Network-first pour les pages HTML et les API (toujours frais)
 *   - Cache-first pour les assets statiques (icônes, manifest)
 */

const CACHE = 'ml-info-v3';
const STATIC_ASSETS = [
    '/static/manifest.json',
    '/static/icon-192.png',
    '/static/icon-512.png',
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE).then(c => c.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        ).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const { request } = event;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    if (url.origin !== location.origin) return;

    // Cache-first pour les assets statiques
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(request).then(cached =>
                cached || fetch(request).then(resp => {
                    const clone = resp.clone();
                    caches.open(CACHE).then(c => c.put(request, clone));
                    return resp;
                })
            )
        );
        return;
    }

    // Network-first pour HTML et API (avec fallback cache)
    if (request.headers.get('accept')?.includes('text/html')
        || url.pathname.startsWith('/api/')) {
        event.respondWith(
            fetch(request)
                .then(resp => {
                    if (resp.ok && url.pathname === '/') {
                        const clone = resp.clone();
                        caches.open(CACHE).then(c => c.put(request, clone));
                    }
                    return resp;
                })
                .catch(() => caches.match(request)
                    .then(cached => cached
                        || new Response(
                            '<h1>Hors ligne</h1><p>Réessaie dans quelques instants.</p>',
                            { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
                        )
                    )
                )
        );
    }
});

// ============================================================
// Push notifications
// ============================================================
self.addEventListener('push', (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = { title: 'Mali Info', body: event.data ? event.data.text() : '' };
    }
    const title = data.title || 'Mali Info';
    const options = {
        body: data.body || '',
        icon: '/static/icon-192.png',
        badge: '/static/icon-192.png',
        data: { url: data.url || '/' },
        tag: data.url || 'ml-info-default',
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || '/';
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
            for (const w of wins) {
                if ('focus' in w) {
                    w.focus();
                    if ('navigate' in w) w.navigate(url);
                    return;
                }
            }
            return clients.openWindow(url);
        })
    );
});
