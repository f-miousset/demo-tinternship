import { useSyncExternalStore } from "react";

/**
 * Light, dark, or whatever the device is doing.
 *
 * **Three positions, not two.** Until this existed the app read
 * `prefers-color-scheme` and nothing else, which is the right default and the
 * one a two-state toggle would have thrown away: a phone that goes dark at
 * sunset should take the app with it. So `system` stays the default, and the
 * other two are an override on top of it.
 *
 * The resolved answer — never the choice — is stamped on `<html>` as
 * `data-theme`, and **that attribute is the only thing the stylesheet reads**:
 * `index.css` keys its token blocks on `[data-theme="dark"]` and Tailwind's
 * `dark:` variant is redefined to match it. One source of truth, so the tokens,
 * the utilities, `color-scheme` and the browser chrome cannot disagree.
 *
 * Two consequences worth knowing:
 *
 * - **Something has to stamp it before the first paint**, or the app renders
 *   light for a frame and then flips. That is `public/theme-boot.js`, loaded
 *   blocking from `index.html` — five lines that read the same key this file
 *   writes. It is duplicated logic on purpose: this module is deferred past the
 *   parse, and this app is a React SPA, so "what if JavaScript is off" is not a
 *   state it has. That script is a *file* and not an inline block because the
 *   production CSP has no `script-src 'unsafe-inline'`; see its own header.
 * - **The page colour lives in three places** — `--page-bg` in `index.css`,
 *   `theme-boot.js`, and `PAGE_BG` below — because each is read at a moment the
 *   other two cannot reach. Change one, change all three.
 *
 * It carries the app's other appearance setting too, and for the same reasons:
 * **how opaque the glass is**, set by the slider on the Settings page, stamped
 * on `<html>` as `--glass-alpha` and mirrored in the boot script so the header
 * does not change opacity a frame after it is drawn. One store, because the two
 * settings share every mechanism they have — the same storage, the same
 * cross-tab event, the same pre-paint problem — and a second copy of all of it
 * is a second place for them to disagree about which frame they land on.
 */
export type ThemeChoice = "system" | "light" | "dark";

/** What `system` resolves to, and the only thing `<html data-theme>` ever holds. */
export type Theme = "light" | "dark";

/** Mirrored in `index.html`'s boot script. */
export const THEME_KEY = "tinternship.theme";

/** The same, for the glass. Mirrored there too. */
export const GLASS_KEY = "tinternship.glass";

/**
 * How opaque the app's glass is, as the `--glass-alpha` the stylesheet derives
 * every pane from — the base grade's alpha, with `.glass-heavy` a notch above
 * it in CSS rather than here.
 *
 * **The full range, both ends real.** At `1` the panes are solid and nothing
 * shows through; at `0` there is no pane at all — `--glass-strength` in
 * `index.css` takes the blur, the saturation, the tint, the rim, the sheen and
 * the shadow down with the colour, so the far end is a window rather than a
 * faint smear of the page. Neither end is a state the design prefers, and both
 * are the user's to pick.
 *
 * The stops are 5% apart because this is dragged with a thumb on a phone, and
 * 100 positions on a 200px track are 100 ways to miss.
 *
 * `default` is what shipped before the slider existed.
 */
export const GLASS = { min: 0, max: 1, step: 0.05, default: 0.62 } as const;

/** At the far end the stylesheet drops `backdrop-filter` rather than computing
 *  an identity one, and it needs a selector to do it: a custom property cannot
 *  switch a declaration off. Mirrored in `theme-boot.js`. */
export function isClearGlass(alpha: number): boolean {
  return alpha <= GLASS.min;
}

/**
 * Anything unparseable, out of range, or absent lands on the default.
 *
 * `parseFloat` on a stringified value rather than `Number()`, and the
 * difference is the whole of this function's first job: `Number(null)` is `0`,
 * which is finite and — now that the range starts there — is *exactly* the value
 * that removes every pane in the app. An install nobody has ever touched this on
 * would open with no header, no tab bar and no sheets, looking broken rather
 * than configured. An unset key has to come back as the default, not as an end
 * of the range.
 */
export function normaliseGlass(value: unknown): number {
  const alpha = typeof value === "number" ? value : Number.parseFloat(String(value ?? ""));
  if (!Number.isFinite(alpha)) return GLASS.default;
  return Math.min(GLASS.max, Math.max(GLASS.min, Math.round(alpha * 100) / 100));
}

/**
 * The status-bar colour per theme, mirrored from `--page-bg` in `index.css`.
 *
 * It is a literal rather than a read of the computed custom property because
 * this also runs in dev, where Vite injects the stylesheet through JavaScript
 * and there is a window in which `--page-bg` computes to nothing.
 */
const PAGE_BG: Record<Theme, string> = { light: "#fafafa", dark: "#0b090e" };

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** Same guard `searchHistory.ts` uses: private browsing throws on access. */
function storage(): Storage | null {
  try {
    if (typeof window !== "undefined" && "localStorage" in window && window.localStorage) {
      return window.localStorage;
    }
  } catch {
    // SecurityError in private browsing or with storage disabled.
  }
  return null;
}

/**
 * The device's preference, as one long-lived `MediaQueryList`.
 *
 * Made once and kept, rather than re-queried per call, and the reference is the
 * point rather than the saving: a `MediaQueryList` nothing holds is a candidate
 * for collection, and the listener attached at the bottom of this file goes
 * with it. The symptom would be the app quietly stopping following the device
 * after some minutes — the kind of bug that never reproduces while you watch.
 *
 * `null` where the browser will not answer: jsdom has no `matchMedia`, and
 * neither does a very old WebView.
 */
const darkMedia: MediaQueryList | null = (() => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
  try {
    return window.matchMedia(DARK_QUERY);
  } catch {
    return null;
  }
})();

/** What the device is asking for right now. Light when it will not say. */
export function systemTheme(): Theme {
  return darkMedia?.matches ? "dark" : "light";
}

/** The stored choice, defaulting to `system` for anything unrecognised. */
export function readThemeChoice(): ThemeChoice {
  const raw = storage()?.getItem(THEME_KEY);
  return raw === "light" || raw === "dark" || raw === "system" ? raw : "system";
}

/** The stored opacity, clamped to the range the slider offers. */
export function readGlass(): number {
  return normaliseGlass(storage()?.getItem(GLASS_KEY));
}

export function resolveTheme(choice: ThemeChoice): Theme {
  return choice === "system" ? systemTheme() : choice;
}

/**
 * Put the resolved theme, and the glass, where the browser can see them.
 *
 * The attribute drives every token in `index.css` and every `dark:` utility;
 * `theme-color` drives the chrome around the app — the Android status bar and
 * Safari's toolbar tint — which on an installed PWA is a visible band of colour
 * above the header rather than a detail.
 *
 * `--glass-alpha` is one inline custom property on the same element, and it is
 * nearly the whole of the slider's effect: every pane derives its background,
 * its blur and its rim from it, so nothing here needs to know which surfaces are
 * glass. It is written even when it equals the stylesheet's own default, for the
 * same reason the attribute is — the DOM stays authoritative rather than the
 * snapshot.
 *
 * The exception is `data-glass="clear"`, and it exists because a custom property
 * can change what a declaration computes to but cannot remove the declaration:
 * at zero the panes are already invisible, and this is what stops the browser
 * still compositing a `backdrop-filter` for them on every scrolled frame.
 */
function paint(theme: Theme, glass: number): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.setProperty("--glass-alpha", String(glass));
  if (isClearGlass(glass)) root.dataset.glass = "clear";
  else delete root.dataset.glass;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", PAGE_BG[theme]);
}

let state: { choice: ThemeChoice; theme: Theme; glass: number } = (() => {
  const choice = readThemeChoice();
  return { choice, theme: resolveTheme(choice), glass: readGlass() };
})();

const listeners = new Set<() => void>();

/**
 * Apply a choice and tell React about it.
 *
 * `paint` runs unconditionally — it is idempotent, and running it even when the
 * snapshot has not moved is what keeps the DOM authoritative if something else
 * has touched the attribute. The listeners only fire on a real change, because
 * `useSyncExternalStore` compares snapshots by identity.
 */
function commit(choice: ThemeChoice, glass: number): void {
  const theme = resolveTheme(choice);
  paint(theme, glass);
  if (choice === state.choice && theme === state.theme && glass === state.glass) return;
  state = { choice, theme, glass };
  listeners.forEach((listener) => listener());
}

/** Pick up a setting written somewhere this module did not see it happen. */
function refresh(): void {
  commit(readThemeChoice(), readGlass());
}

/** Store the choice and apply it. `system` is stored explicitly, not as an
 *  absence, so "follow the device" reads the same on a machine that has never
 *  been touched and on one that was set to dark and then set back. */
export function setThemeChoice(choice: ThemeChoice): void {
  try {
    storage()?.setItem(THEME_KEY, choice);
  } catch {
    // Quota or a locked-down browser: the choice still applies for this session.
  }
  commit(choice, state.glass);
}

/**
 * Store the glass opacity and apply it.
 *
 * Clamped on the way in as well as on the way out: this is called from a range
 * input, which cannot leave the range, and from nothing else today — but the
 * value it writes outlives every version of that input, and a stored `-3` or
 * `NaN` is a state no slider position corresponds to.
 */
export function setGlass(alpha: number): void {
  const glass = normaliseGlass(alpha);
  try {
    storage()?.setItem(GLASS_KEY, String(glass));
  } catch {
    // Quota or a locked-down browser: the choice still applies for this session.
  }
  commit(state.choice, glass);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // The snapshot was taken when this module loaded, which may have been before
  // anything wrote the key — another tab, or a test. React re-reads it after
  // `subscribe` returns, so correcting it here is not too late.
  refresh();
  return () => {
    listeners.delete(listener);
  };
}

function snapshot(): { choice: ThemeChoice; theme: Theme; glass: number } {
  return state;
}

/**
 * The current choice, what it resolves to, and how to change it.
 *
 * `useSyncExternalStore` rather than `useState`, for two reasons that both come
 * from the theme not being any one component's property: the sun setting has to
 * move every mounted switch at once, and the same key set in a second tab has
 * to move this one.
 */
export function useTheme(): {
  choice: ThemeChoice;
  theme: Theme;
  glass: number;
  setChoice: (choice: ThemeChoice) => void;
  setGlass: (alpha: number) => void;
} {
  const current = useSyncExternalStore(subscribe, snapshot, snapshot);
  return { ...current, setChoice: setThemeChoice, setGlass };
}

if (typeof window !== "undefined") {
  // The device changing its mind, which on a phone happens on a schedule
  // nobody is watching. Only moves the app while the choice is `system`;
  // `resolveTheme` ignores it otherwise.
  darkMedia?.addEventListener?.("change", () => commit(state.choice, state.glass));

  // The app open twice — a browser tab beside the installed PWA. `key === null`
  // is a `clear()`, which the reset flow can cause.
  window.addEventListener("storage", (event) => {
    if (event.key === THEME_KEY || event.key === GLASS_KEY || event.key === null) refresh();
  });

  // A safety net, not the mechanism: `index.html`'s boot script has already
  // done this before the first paint. It matters in dev, where an edit to that
  // script only lands on a full reload.
  paint(state.theme, state.glass);
}
