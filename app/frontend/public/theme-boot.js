/**
 * Stamp the theme before the first paint.
 *
 * `<html data-theme>` is what `index.css` keys every token block on and what
 * Tailwind's `dark:` variant matches, so whatever sets it decides what the very
 * first frame looks like. The app's own module cannot: it is `type="module"`,
 * which defers past the parse, and a returning user who chose dark would get a
 * white flash and then a flip.
 *
 * **A separate file rather than an inline script**, which is what this would
 * obviously be, because `deploy/nginx.conf` serves `script-src 'self'` with no
 * `'unsafe-inline'` — the inline version is blocked in production and works
 * perfectly in dev, which is the worst way for a thing to be wrong. It is
 * precached with the shell in `sw.js` so an offline launch stamps too.
 *
 * It stamps the **glass opacity** for the same reason: `--glass-alpha` is what
 * every pane's background derives from, so a returning user who dragged the
 * slider would otherwise watch the header change opacity one frame in. The
 * range is clamped here as well as in the module — this reads a value a user
 * can edit by hand, and an out-of-range one is a header you cannot read.
 *
 * The keys, the accepted values, the range and the two colours are duplicated
 * from `src/lib/theme.ts` (and the colours again from `--page-bg` in
 * `index.css`). Nothing importable runs this early, so the duplication is the
 * price. Change one, change all of them.
 */
(function () {
  var choice = null;
  try {
    choice = localStorage.getItem("tinternship.theme");
  } catch (error) {
    // Private browsing, or storage switched off: fall through to the device.
  }
  var dark =
    choice === "dark" ||
    (choice !== "light" &&
      !!window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", dark ? "#0b090e" : "#fafafa");

  var glass = null;
  try {
    glass = parseFloat(localStorage.getItem("tinternship.glass"));
  } catch (error) {
    // Same story: no storage, so the stylesheet's own default stands.
  }
  if (isFinite(glass)) {
    glass = Math.min(1, Math.max(0, glass));
    document.documentElement.style.setProperty("--glass-alpha", String(glass));
    // The far end of the slider drops `backdrop-filter` through a selector,
    // because a custom property cannot remove a declaration. `isClearGlass` in
    // theme.ts is the same test.
    if (glass <= 0) document.documentElement.dataset.glass = "clear";
  }

  // Stamp the launch context, which `--header-clearance` reads: an installed app
  // needs 16pt of room below the Dynamic Island, a browser tab already sits
  // below the browser's chrome and only wants 4pt. Stamped on a POSITIVE browser
  // match and never the other way round, so anything unprovable — an engine with
  // no `matchMedia`, a display mode that answers neither — keeps the installed
  // app's spacing, which is the half that must not be got wrong.
  // `navigator.standalone` is iOS's own signal and the belt to that query's
  // braces: a legacy iOS home-screen app answers `display-mode: browser` too,
  // and the query alone would hand it the tab's spacing.
  var isBrowser =
    window.navigator.standalone !== true &&
    !!window.matchMedia &&
    window.matchMedia("(display-mode: browser)").matches;
  if (isBrowser) document.documentElement.setAttribute("data-display", "browser");
})();
