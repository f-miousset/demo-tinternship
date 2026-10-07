# Self-hosting — running the real app from this repository

The public guide is `docs/index.html`, published by GitHub Pages at
<https://f-miousset.github.io/demo-tinternship/> (Settings → Pages: branch
`main`, folder `/docs`). It is a static page — no build step — and the file to
edit when anything below changes. `docs/.nojekyll` stops Pages from running
Jekyll over it.

## `selfhost/`

```
docker compose up -d --build     (from selfhost/, after cp ../app/.env.example .env)
  gateway   nginx:1.31-alpine   127.0.0.1:${PORT:-8080} → /api → api:8000, / → web:80
  api       app/deploy/Dockerfile.api   FastAPI + the agents; ./data mounted at /app/data
  web       app/deploy/Dockerfile.web   the static UI
```

**Why a gateway.** The UI calls `/api` relative to itself (`lib/api.ts`), so UI
and API must share an origin. In the author's own deployment a reverse proxy
does that routing; `gateway.conf` is the same rule for one machine, with
`proxy_buffering off` so a run's progress events arrive as they happen.

**Only `GOOGLE_API_KEY` is required.** Everything else in
`app/.env.example` is optional and documented there. `FRONTEND_ORIGIN` and
`DATA_DIR` are set by the compose file.

**No login, so localhost only.** The app trusts whoever reaches it. The port is
published on `127.0.0.1`; the guide tells readers to put an authenticating proxy
in front before exposing it, never to open the port.

**Verified 2026-10-08**: built from scratch with a dummy key — all three
containers up (api and web healthy), `/api/health` ok through the gateway, the
UI served, and a search stream returning the backend's own "Gemini rejected the
API key" error event, unbuffered.

## `selfhost/example-documents/`

Alex Martin's four base documents, written by `make seed`. Uploading them on
the Account page is the fastest way to try the real app without writing a CV
with blanks first.
