/**
 * What every test in this suite gets, before it runs.
 *
 * The point of the suite is to catch a dependency bump that typechecks and
 * builds and then breaks in the browser — React, React Router, TanStack Query
 * and Vite all change behaviour without changing types. So the rules here are
 * the ones that keep such a failure *visible*: nothing may reach the network,
 * and nothing may swallow an error.
 */
import { cleanup, configure } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";

// `findBy*` and `waitFor` give up after 1 s by default. Locally the slowest page
// here renders in a few hundred ms, but CI runs on a self-hosted runner that
// other jobs share, and a busy one takes 1.5 s — so on 2026-09-22 three tests
// failed there that passed on every local run. The wait returns as soon as the
// element appears, so a longer ceiling costs nothing when things are fast.
// `testTimeout` in `vite.config.ts` rises with it, or a test awaiting two of
// these would hit that limit instead.
configure({ asyncUtilTimeout: 5000 });

// jsdom implements `window.scrollTo` and not `Element.prototype.scrollTo`, which
// `InterviewSection` calls on its transcript pane after every message. Without
// this, mounting the Account page throws on a method every real browser has.
if (!("scrollTo" in Element.prototype)) {
  Object.defineProperty(Element.prototype, "scrollTo", { value: () => {}, writable: true });
}

// jsdom implements no `matchMedia` at all, and `lib/theme.ts` asks it what the
// device wants. The module guards for that — a browser too old to answer gets
// the light theme — so without a stub every theme test would silently assert
// against the guard rather than against the logic.
//
// It lives here rather than in the one test that needs it because it has to be
// installed *before* the test file's imports run: `theme.ts` subscribes to the
// media query at module load, and a stub arriving afterwards would be seen by
// `systemTheme()` but never by the listener, which is exactly the half that
// makes "System" mean something.
const mediaListeners = new Set<(event: MediaQueryListEvent) => void>();
let systemDark = false;

/** Flip what the device is asking for, and tell everything that is listening. */
export function setSystemDark(dark: boolean): void {
  systemDark = dark;
  mediaListeners.forEach((listener) => listener({ matches: dark } as MediaQueryListEvent));
}

if (typeof window.matchMedia !== "function") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      media: query,
      get matches() {
        return query.includes("dark") && systemDark;
      },
      onchange: null,
      addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        mediaListeners.add(listener);
      },
      removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => {
        mediaListeners.delete(listener);
      },
      addListener: (listener: (event: MediaQueryListEvent) => void) => {
        mediaListeners.add(listener);
      },
      removeListener: (listener: (event: MediaQueryListEvent) => void) => {
        mediaListeners.delete(listener);
      },
      dispatchEvent: () => false,
    }),
  });
}

// jsdom under recent Node may lack localStorage unless configured. Provide a
// clean in-memory fallback and wipe it between tests.
const storageStore = new Map<string, string>();
const storageMock: Storage = {
  getItem: (key: string) => storageStore.get(key) ?? null,
  setItem: (key: string, value: string) => {
    storageStore.set(key, String(value));
  },
  removeItem: (key: string) => {
    storageStore.delete(key);
  },
  clear: () => {
    storageStore.clear();
  },
  key: (index: number) => Array.from(storageStore.keys())[index] ?? null,
  get length() {
    return storageStore.size;
  },
};
try {
  if (!window.localStorage || typeof window.localStorage.getItem !== "function") {
    Object.defineProperty(window, "localStorage", { value: storageMock, writable: true, configurable: true });
  }
} catch {
  Object.defineProperty(window, "localStorage", { value: storageMock, writable: true, configurable: true });
}

const realConsoleError = console.error;
let consoleErrors: string[] = [];

beforeEach(() => {
  window.localStorage?.clear();
  systemDark = false;
  // No test may reach the network — the same rule the backend suite enforces
  // with `BROWSER_VERIFY=false`. A test that forgets to stub `fetch` fails here
  // naming the URL it wanted, instead of hanging until the runner times out.
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    throw new Error(`Unstubbed fetch in a test: ${String(input)} — use stubApi() from harness.tsx`);
  }) as typeof fetch;

  // React reports a failed render to `console.error` and then carries on with an
  // empty tree, so a test that only asserts on the DOM can pass while the page
  // is broken. Collect them and fail the test instead: "cannot be used as a JSX
  // component" and the hook-order errors — what a major React bump actually
  // looks like — arrive on this channel and nowhere else.
  consoleErrors = [];
  console.error = (...args: unknown[]) => {
    consoleErrors.push(args.map((arg) => (arg instanceof Error ? arg.message : String(arg))).join(" "));
    realConsoleError(...args);
  };
});

afterEach(() => {
  cleanup();
  console.error = realConsoleError;
  if (consoleErrors.length > 0) {
    throw new Error(`console.error during this test:\n${consoleErrors.join("\n")}`);
  }
});
