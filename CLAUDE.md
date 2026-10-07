# Tinternship — a public, AI-free demo, and the real app's code

A portfolio demo of **Tinternship**, a team of AI agents that finds internships
and fills in the candidate's own CV and cover letter for each one. The demo at
<https://demo-tinternship.fmiousset.com> is the real app's frontend over a mock
API in the visitor's browser: **no model is ever called**, every agent answer is
pre-written, and every visitor's data stays in their own browser. `app/` holds
the real app's code (a sanitised snapshot of the private repository at tag
`v1`), published for auditing and for self-hosting with one API key.

This file is an **index** — the facts live in [`documentation/`](documentation/).
Open the one file the task needs.

---

## ⚠ Documentation is part of every task

Before finishing ANY change on disk, update the documentation in the same task:
re-read the topic files your change touches and make them describe the system
as it now is, record the *why* with the date in
[gotchas.md](documentation/gotchas.md) when something bit, and update in-file
comments. A doc describing behaviour you just changed is wrong, and wrong docs
are trusted.

---

## The documentation map

| read this | when you are… |
|---|---|
| [README.md](README.md) | explaining the project to someone else — the outside view |
| [architecture.md](documentation/architecture.md) | new here: the four parts, how the mock replaces the backend, why |
| [mock-api.md](documentation/mock-api.md) | touching `demo/src/mock/`: routes, state, serialisers, ids |
| [canned-ai.md](documentation/canned-ai.md) | changing what an agent run returns, the auto-fill, or the demo notice |
| [seed-data.md](documentation/seed-data.md) | editing `seed/world.py` or `scripts/build_seed.py`; dates; determinism |
| [syncing-from-v2.md](documentation/syncing-from-v2.md) | bringing `app/` and the demo up to date with the private repo |
| [self-hosting.md](documentation/self-hosting.md) | `selfhost/`, the GitHub Pages guide in `docs/` |
| [deployment.md](documentation/deployment.md) | the image, nginx, the CSP, the public route |
| [verification.md](documentation/verification.md) | the gate, CI, the privacy check, Renovate |
| [mobile-and-pwa.md](documentation/mobile-and-pwa.md) | the Demo pill, the toast, anything at 375 px |
| [gotchas.md](documentation/gotchas.md) | **before changing anything clever** — every trap already fallen into |

---

## Rules that must not be broken

1. **No model, no backend, no network.** The demo answers `/api` inside the
   page; nginx has no write path and the CSP pins `connect-src 'self'`. A new
   agent run gets a canned answer, never a call. → [canned-ai.md](documentation/canned-ai.md)
2. **Nothing identifying or private, ever.** This repository is public.
   `make public` fails on a hashed denylist, infrastructure words, foreign
   hosts on the owner's domain, non-example e-mails and non-noreply commit
   identities. Commit as the GitHub noreply address. Never remove a hash to
   make a build pass — fix the source, in the private repo.
   → [verification.md](documentation/verification.md)
3. **`app/` is a copy, never edited here.** It changes only through
   `make sync` from a tag of the private repo, and Renovate ignores it.
   → [syncing-from-v2.md](documentation/syncing-from-v2.md)
4. **`demo/static/` is generated.** Edit `seed/world.py` or the builder, run
   `make seed`, commit the output; CI's `make seed-check` rebuilds and compares.
5. **The app's frontend stays unmodified.** The demo hooks in through `fetch`
   and its own React root; anything that would need an app change is wrong here.
6. **Mobile first, both themes.** Check 375 px, light and dark.
7. **Lint is a gate**: `make verify` passes before anything is committed.

---

## How work lands

1. Update the documentation (above).
2. `make verify`; `make app-test` after a sync; `make smoke` if the Dockerfile,
   nginx config or build changed.
3. Commit in this repo's style (`area: what changed, and why`) and push to `main`.
4. The deployment rebuilds the image from `main`; where and how is documented
   with the infrastructure that serves it, not here.
