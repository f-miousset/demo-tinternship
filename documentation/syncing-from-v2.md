# Syncing from v2 — bringing the demo up to date with the real app

The private repository labels everything after the demo's snapshot as **v2**:
tag `v1` marks what `app/` holds, every later commit subject starts `v2:`, and
each user-visible change has a line under `## v2` in its `CHANGELOG.md`. That
list is the work list for a resync.

## Procedure

1. **Read what changed.** In the private checkout:
   `git log --oneline v1..main` and the `## v2` section of `CHANGELOG.md`.
   Note every new or changed endpoint, response field, screen, and agent run.
2. **Make sure the source is publishable.** The privacy check below will
   refuse names, e-mails and infrastructure; fix those *in the private repo*
   (fixtures use the fictional Alex Martin), so the snapshot stays a plain copy.
3. **Tag it there**: `git tag -a v2 -m "…"` on the commit to publish.
4. **Sync**: `make sync SOURCE=<path-to-private-checkout> REF=v2`. This
   replaces `app/`, writes `snapshot.json`, rebuilds the seed and runs the
   privacy check.
5. **Fix the mock until it is green**:
   - `make typecheck` — the mock is typed against `app/frontend/src/lib/types.ts`;
     a changed contract fails here first.
   - `make test` — the contract test fails on any `/api` path without a route,
     and on any auto-filled box whose placeholder changed.
   - New agent run? Add its canned answer (`seed/world.py`,
     `scripts/build_seed.py`), its route, and its row in
     [canned-ai.md](canned-ai.md).
   - New response field? It usually arrives for free through the seed (it is
     the backend's serialisation); fields the mock computes live in
     `mock/serialise.ts`.
6. **Click through it** at 375 px, light and dark: deck, a search, a paste,
   Generate, Tracker, an application, Account, Traces, Settings.
7. `make verify`, `make app-test`, `make smoke`, then commit (`sync: v2 — …`)
   and push.
8. **In the private repo, open the next line**: version to `3.0.0`, a
   `## v3 — unreleased` section, commit prefix `v3:`.

## What is never copied

The private repo's `documentation/`, `CLAUDE.md`, `AGENTS.md`, `README.md`,
`.github/`, `archive/` and `data/` — they describe the author's own
infrastructure, or are the author's data. The include list is `PATHS` in
`scripts/sync-from-tinternship.sh`; `git archive` means only committed files
can come across.
