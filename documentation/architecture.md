# Architecture — how the demo is put together

The demo is **the real app's frontend over a fake backend that lives in the
visitor's browser**. Nothing about the UI is re-implemented: the deck, the
Tracker, the application page, Account, Settings and Traces are
`app/frontend/src`, byte for byte what the private repository runs. What is
replaced is the one thing a public demo cannot have — the API and the agents
behind it.

```
browser ─────────────────────────────────────────────────────────────────────┐
│  demo/src/main.demo.tsx                                                     │
│    1. installMock()      window.fetch for /api/* → demo/src/mock/routes.ts  │
│    2. import app/frontend/src/main.tsx   (the real app, unmodified)         │
│    3. <DemoNotice/>      its own React root: notice, Demo pill, auto-fill   │
│                                                                             │
│  mock/store.ts   one visitor's state in localStorage ("demo-tinternship:…") │
│        ▲ seeded once from /demo-data/seed.json, dates shifted to today      │
│        ▲ canned answers from /demo-data/canned.json, loaded on first run    │
└─────────────────────────────────────────────────────────────────────────────┘
          │ GET only
nginx (Dockerfile) — static files; every POST/PUT/PATCH/DELETE → 404/405
  /                    the SPA shell and assets
  /demo-data/*.json    the seed
  /api/applications/artifacts/<id>/{preview,export}   prebuilt HTML and .docx
  /api/*               anything else → 404 (the page never asks)
```

## The four parts of the repository

| path | what it is | who writes it |
|---|---|---|
| `app/` | a sanitised copy of the real app at tag `v1` — backend (the agents, prompts, rubrics), frontend, Dockerfiles | `scripts/sync-from-tinternship.sh`, never by hand |
| `demo/` | the mock API, the demo notice and auto-fill, the static files the build serves | by hand, except `demo/static/` (the seed builder) |
| `seed/world.py` + `scripts/build_seed.py` | the fictional world, and the script that runs it through the real backend to produce `demo/static/` | by hand / `make seed` |
| `selfhost/`, `docs/` | how to run the real app with your own key; the GitHub Pages guide | by hand |

## Decisions, and why

**The frontend is imported, not copied into `demo/`.** A demo that
re-implemented the screens would drift from the app on the first v2 change and
stop being evidence of anything. Importing `app/frontend/src/main.tsx` means a
resync updates every screen at once, and `tsc` checks the mock against the
app's own types (`app/frontend/src/lib/types.ts`).

**`fetch` is the only seam.** Every API call in the app goes through `fetch`
in `lib/api.ts`, streams included (a fetch body reader, not EventSource), so
one interceptor replaces the whole backend. The two exceptions are not
`fetch` at all — the document preview is an `<iframe src>` and the download an
`<a href>` — so those are real static files at the exact paths the app asks
for, written by the seed builder and served by nginx.
→ [mock-api.md](mock-api.md)

**The seed is produced by the real backend, offline.** `scripts/build_seed.py`
writes the fictional world into an empty database through the backend's own
services and reads it back through its own API, so every response shape is the
backend's. It fills the candidate's documents with the real `.docx` filler and
renders previews with the real renderer. No model is called.
→ [seed-data.md](seed-data.md)

**State is per browser, by construction.** The server has no write path, and
the page's CSP pins `connect-src 'self'`; a visitor's changes exist only in
their own localStorage. Two people using the demo at once cannot see each
other because there is nothing shared to see. → [deployment.md](deployment.md)

**The agents are replayed, not simulated.** A run streams the same `phase`
lines the real pipeline sends (taken from the backend's own message tables),
paced over a few seconds, then saves a pre-written result and logs a trace
with the real pipeline's agent names. → [canned-ai.md](canned-ai.md)

**Vite's root is the repository root.** Tailwind generates only the utilities
it finds under the root; `demo/` as the root built an unstyled app.
→ [gotchas.md](gotchas.md)
