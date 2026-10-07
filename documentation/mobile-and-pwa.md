# Mobile and PWA

All of it is inherited from the real app, unmodified: `viewport-fit=cover`,
safe-area padding, `overscroll-behavior-y: none`, the 44 px targets, the
floating glass header and tab bar, the three-position System/Light/Dark switch
(stamped before paint by `theme-boot.js`, a file because the CSP forbids inline
scripts), the manifest, the maskable icons and the service worker
(`app/frontend/public/`). The service worker never touches `/api`, so it does
not cache the demo's prebuilt documents.

The demo adds two things of its own (`demo/src/demo.css`, on the app's tokens):

- **The Demo pill** — bottom-left, at the height of the app's floating action
  button (`.fab-dock`, bottom-right), so the two read as one row above the tab
  bar and neither covers it; at `sm` and up, the bottom-left corner.
- **The auto-fill toast** — at the *top*. Every sheet that holds an
  auto-filled box rises from the bottom, and a toast down there covered the
  very field it was describing.

Check both at 375 px in light and dark after any resync.
