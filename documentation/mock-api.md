# The mock API — `demo/src/mock/`

| file | does |
|---|---|
| `install.ts` | replaces `window.fetch` for same-origin `/api/*`; everything else passes through |
| `routes.ts` | the route table — one entry per endpoint the app calls, each naming the backend handler it stands in for — and the agent runs |
| `serialise.ts` | the backend's read side: deck order (`recency.score`), Tracker views, follow-up silence, setup progress, trace stats |
| `store.ts` | the visitor's state: seeding, date shifting, saving to localStorage, reset |
| `http.ts` | JSON and error responses, and `sse()` — the backend's event-stream wire format, paced |
| `runs.ts` | the trace a run leaves: agent/model/tool events, tokens, cost from the price list, the Critic's verdict |
| `types.ts` | the stored shapes, typed with the app's own `lib/types.ts` |

## Rules

- **Every route names its backend counterpart** in the comment or the
  grouping (`// api/jobs.py`). When the backend changes on a resync, that is
  the line to compare against.
- **Reads come from the stored state; only today-dependent values are
  computed** — a posting's age, an application's silence, the deck order.
  Everything else was serialised by the real backend at seed time.
- **No route ever calls the network.** `realFetch` (the browser's own fetch,
  saved at install) is used only for `/demo-data/*.json` on the same origin.
- **Errors look like the backend's**: `{"detail": "…"}` with the status the
  real endpoint would send (404 unknown id, 409 not in trash, 400 bad input).

## Ids

Seeded rows keep the backend's ids. New rows take `state.nextId`, which starts
above every seeded id. Canned documents have fixed ids from 1000 up, because
their preview and download are files named by id: a run that "writes" a
document reuses that id, and a second run of the same document bumps its
version in place (`artifactRow`).

## Adding a route

1. Add the entry to `ROUTES` in `routes.ts`, next to its neighbours from the
   same backend file.
2. `make test` — the contract test (`mock.test.ts`) extracts every `/api/…`
   path from `app/frontend/src` and fails on any without a route. It is the
   check that makes a resync safe.
3. If it is an agent run, give it a pre-written answer — see
   [canned-ai.md](canned-ai.md).
