/**
 * The offline shell. Hand-written on purpose — the caching rules here are three
 * lines of policy, and the interesting part is what is *not* cached.
 *
 * Nothing under /api is touched. Those are the agent runs: SSE streams that must
 * reach the network unbuffered, mutations that must not be replayed, and
 * responses that may be a redirect to the Authelia portal. A service worker
 * sitting in that path is a way to break a run, never a way to speed one up.
 *
 * There is no build-time precache manifest, so nothing here needs bumping on a
 * deploy. Vite fingerprints everything under /assets, which makes those safe to
 * serve from the cache forever; everything else — the HTML shell, the theme boot
 * script, the icons and the manifest — sits at a URL that never changes, so all
 * of it goes to the network first and falls back to the cache only when the
 * phone is actually offline.
 *
 * `assets-v2` is a one-time purge, not a new habit. Until 2026-08-27 the icons
 * and the manifest were stale-while-revalidate, which meant an installed app
 * kept the old mark for one more load after a rebrand — and for a PWA that is
 * the load the launcher icon is read on. `activate` deletes any cache not in
 * KEEP, so bumping the name drops what was stored under the old policy.
 */

const SHELL = "shell-v1";
const ASSETS = "assets-v2";
const KEEP = [SHELL, ASSETS];

/**
 * The two files a launch cannot start without, both at URLs that never change.
 *
 * `/theme-boot.js` is here rather than with the icons below because of *when*
 * it runs: it stamps `<html data-theme>` before the first paint, so a launch
 * that cannot fetch it paints the wrong theme and then flips — the one frame a
 * home-screen app is judged on. It is 400 bytes. See index.html.
 */
const SHELL_FILES = ["/index.html", "/theme-boot.js"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      .then((cache) =>
        Promise.all(SHELL_FILES.map((path) => cache.add(new Request(path, { cache: "reload" })))),
      )
      // A first install with no network still has to finish, or the worker is
      // stuck and the next visit gets no offline support either.
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(names.filter((name) => !KEEP.includes(name)).map((name) => caches.delete(name))),
      )
      .then(() => self.clients.claim()),
  );
});

/** Only a plain, complete, same-origin 200 is worth keeping. */
function cacheable(response) {
  return response && response.ok && response.type === "basic" && !response.redirected;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  // The shell. Network first, so a deploy is picked up on the next navigation
  // rather than whenever the cache happens to be evicted.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (cacheable(response)) {
            const copy = response.clone();
            caches.open(SHELL).then((cache) => cache.put("/index.html", copy));
          }
          return response;
        })
        .catch(() => caches.match("/index.html").then((hit) => hit ?? Response.error())),
    );
    return;
  }

  // Fingerprinted bundles: the URL changes when the content does, so a hit is
  // always the right answer and never needs revalidating.
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ??
          fetch(request).then((response) => {
            if (cacheable(response)) {
              const copy = response.clone();
              caches.open(ASSETS).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
    return;
  }

  // The boot script. Network first like the shell it belongs to — its URL never
  // changes, so the day its bytes do a cache hit is the one certainly wrong
  // answer — with the cache as the offline fallback rather than as the fast
  // path.
  if (url.pathname === "/theme-boot.js") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (cacheable(response)) {
            const copy = response.clone();
            caches.open(SHELL).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request).then((hit) => hit ?? Response.error())),
    );
    return;
  }

  // Icons and the manifest. Network first, like the shell and for the same
  // reason: these URLs never change, so the day their bytes do — a rebrand — a
  // cache hit is the one answer that is certainly wrong. They are 4-14 KB and
  // asked for about once a page, so the cache here buys offline support rather
  // than speed, and paying a request for it is the right way round.
  if (/\.(png|svg|webmanifest|ico)$/.test(url.pathname)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (cacheable(response)) {
            const copy = response.clone();
            caches.open(ASSETS).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request).then((hit) => hit ?? Response.error())),
    );
  }
});
