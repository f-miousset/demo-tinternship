# Gotchas — every trap already fallen into

Newest first. Each entry: what happened, how it showed, what fixed it.

### The privacy check found what the hand sweep missed — 2026-10-08
The first public snapshot passed a manual search for the author's name and
e-mail, then `ci/check-privacy.py` flagged the author's school in a docstring
and two test fixtures, a private sibling project's name in four design
comments, and a non-example e-mail in a test. Fixed in the private repo on a
branch cut from tag `v1` (so the snapshot stays version 1.0.0), the tag moved
to it, the branch merged into `main`. **Run `make public` before the first
push of anything** — and fix the source, not the denylist.

### `curl | grep -q` fails under `pipefail` on a large body — 2026-10-08
The smoke reported "the seed is not served" while nginx served it fine:
`grep -q` exits at its first match, `curl` dies of SIGPIPE writing the rest
of 650 kB, and `set -o pipefail` fails the pipeline. Read the body into a
variable first, then search it (`ci/smoke.sh`).

### The auto-fill toast covered the field it filled — 2026-10-08
Placed above the tab bar, it sat exactly over the paste sheet's input. Moved
to the top of the screen; every relevant sheet rises from the bottom.

### A run's progress lines came out in alphabetical order — 2026-10-08
The seed is written with sorted keys (for determinism), so the Investigator's
stage table — an object — arrived Matcher first. Stage tables are now lists
of `[stage, message]` pairs.

### The seed was downloaded four times per page load — 2026-10-08
The app's first render fires several queries at once; caching the parsed seed
only after it arrived started one download per query. `store.ts` caches the
*promise*.

### Vite's root at `demo/` built an unstyled app — 2026-10-08
17 kB of CSS instead of 73 kB, no error: Tailwind v4 only scans files under
the Vite root, and every class the UI uses lives in `app/frontend/src`. The
root is the repository root now, and `ci/check-dist.sh` asserts three classes
that exist only in the app's components.

### A 404 for the seed in the dev console
`make seed` deletes and rewrites `demo/static/`; a dev server that reloads in
that window gets a 404 for `/demo-data/seed.json`. Harmless — reload after the
builder finishes.
