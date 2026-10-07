# Deployment — the image, nginx, and the public route

## The image (`Dockerfile`)

Two stages: `node:24-alpine` runs `npm ci` and `vite build`; `nginx:1.31-alpine`
serves `dist/`. Only the frontend sources, `demo/` and the build config are
copied in — `app/backend` never enters the image (`.dockerignore`): the demo's
server runs no Python and no agent. The `HEALTHCHECK` is in the Dockerfile, so
every `docker run` (the smoke included) executes it, and probes `127.0.0.1`
rather than `localhost`, which busybox resolves to `::1` first.

The build also writes `dist-nginx/export-names.conf` — an nginx `map` from each
download's path to the `Content-Disposition` the real API would send
(`Resume_Alex_Martin_Helio_Grid_….docx`) — which the image installs as
`conf.d/00-export-names.conf`.

## nginx (`nginx.conf`)

- **No write path.** Static files only; a POST/PUT/PATCH/DELETE anywhere is a
  404 or 405. `ci/smoke.sh` sends them to prove it.
- **`/api/*` is a 404**, except the two prebuilt document paths
  (`…/artifacts/<id>/preview` → `preview.html`, `…/export` → `export.docx`).
- **Headers live at server level, varied by `map`** — an `add_header` inside a
  location would silently drop the CSP. The CSP is the real app's, with
  `frame-ancestors` relaxed to `'self'` for the preview alone (it is shown in an
  iframe on the same origin) and `'none'` everywhere else.
- `connect-src 'self'` makes "your data stays in your browser" a rule the
  browser enforces, not only a property of the code.
- `.webmanifest` gets its MIME type in its own location: a `types` block at
  server level would replace nginx's whole table.

## Where it runs

`https://demo-tinternship.fmiousset.com` — a container on the owner's server
behind a reverse proxy, on a **public route** (no authentication: there is
nothing to protect, and a login would defeat a portfolio demo). How it is
wired there is documented with that infrastructure, not here. What this repo
guarantees is the image: stateless, no mounts, no environment, no secrets.

Deploying a change is rebuilding that image from `main`; `make smoke` is the
check a deploy runs first.
