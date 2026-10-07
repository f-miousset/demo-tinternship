/**
 * Install the offline shell (see `public/sw.js`).
 *
 * Production only. In dev the same worker would sit in front of Vite's module
 * graph and serve yesterday's shell to an HMR session, which looks exactly like
 * a bug in whatever you were editing. Any worker left over from a production
 * visit to the same origin is unregistered instead.
 */
export function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;

  if (!import.meta.env.PROD) {
    void navigator.serviceWorker
      .getRegistrations()
      .then((registrations) => registrations.forEach((registration) => registration.unregister()));
    return;
  }

  // After load: registering competes with the first paint for bandwidth
  // otherwise, and on a phone that is the part you can feel.
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch(() => {
      // An origin without HTTPS, or a browser with workers switched off. The app
      // works without one — it just does not survive a tunnel.
    });
  });
}
