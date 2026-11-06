const CACHE_NAME = 'ai-predictor-v108';
const ASSETS_TO_CACHE = [
  './',
  './index.html',
  './manifest.json'
];

// Copia di Chart.js per quando il CDN non risponde o si è offline: aggiunta
// a parte (e senza far fallire l'installazione se il download non riesce).
const CHART_JS_URL = 'https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll(ASSETS_TO_CACHE).then(() => cache.add(CHART_JS_URL).catch(() => {}))
    )
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
});

// La pagina decide quando attivare una nuova versione (dopo che l'utente
// tocca il banner "Aggiorna"), invece di sostituire subito quella in uso.
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', (event) => {
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Chart.js: si aggiorna la copia ogni volta che il CDN risponde.
        if (event.request.url === CHART_JS_URL && response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy)).catch(() => {});
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
