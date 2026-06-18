{% load static %}'use strict';

const CACHE = 'helpy-v1';

// Assets pré-cacheados na instalação
const PRECACHE = [
  '/painel/',
  '{% static "favicon.svg" %}',
];

// ── Instalação: abre o cache e pré-carrega os assets essenciais ──
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

// ── Ativação: limpa caches de versões antigas ──
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

// ── Fetch: estratégia por tipo de recurso ──
self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);

  // Ignora requisições não-GET e cross-origin (CDNs, Google Fonts, etc.)
  if (req.method !== 'GET' || url.origin !== location.origin) return;

  // Assets estáticos → cache-first (serve do cache, atualiza em background)
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(req).then((cached) => {
        const networkFetch = fetch(req).then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(CACHE).then((c) => c.put(req, clone));
          }
          return res;
        });
        return cached || networkFetch;
      })
    );
    return;
  }

  // Páginas HTML → network-first, cache como fallback offline
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const clone = res.clone();
            caches.open(CACHE).then((c) => c.put(req, clone));
          }
          return res;
        })
        .catch(() =>
          caches.match(req)
            .then((cached) => cached || caches.match('/painel/'))
        )
    );
  }
});
