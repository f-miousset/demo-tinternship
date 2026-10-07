/**
 * Replace `fetch` for `/api/*` with the in-browser mock.
 *
 * Every API call the app makes goes through `fetch` (`lib/api.ts`), streams
 * included — there is no EventSource and no WebSocket — so this one seam is the
 * whole backend boundary. Anything that is not a same-origin `/api/` request
 * passes through untouched, and the page's CSP (`connect-src 'self'`) means
 * nothing could reach another origin anyway.
 */
import { handle } from "./routes";
import { setRealFetch } from "./store";

export function installMock(): void {
  const original = window.fetch.bind(window);
  setRealFetch(original);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const request = input instanceof Request ? input : null;
    const url = new URL(request ? request.url : String(input), window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/")) {
      return original(input, init);
    }
    const raw = init?.body;
    let body: unknown;
    if (raw instanceof FormData) body = raw;
    else if (typeof raw === "string" && raw) {
      try {
        body = JSON.parse(raw);
      } catch {
        body = raw;
      }
    }
    return handle({
      method: (init?.method ?? request?.method ?? "GET").toUpperCase(),
      path: url.pathname,
      query: url.searchParams,
      body,
    });
  };
}
