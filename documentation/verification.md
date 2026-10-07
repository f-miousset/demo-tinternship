# Verification — the gate, and what it can still miss

`make verify` is the demo's gate; CI (`.github/workflows/ci.yml`) calls the
same targets, so there is one definition of each command.

| target | checks |
|---|---|
| `make public` | `ci/check-privacy.py`: a hashed denylist (the original candidate's identity and school, the owner's other private projects and storage), private-infrastructure words, any host on the owner's domain except the demo's, e-mails outside `example.org`/`example.com`, non-noreply commit identities. Reads inside every `.docx`. |
| `make lint` | eslint `--max-warnings 0` (the app's rules), ruff on the seed builder, shellcheck |
| `make typecheck` | `tsc` — the mock against the app's own types |
| `make test` | vitest, `demo/src/mock/mock.test.ts`: every `/api` path in the app has a route; every auto-filled box still exists; every canned document has its preview and download; setup opens complete; dates shift; runs reveal, import, generate and trace; state survives a reload and resets |
| `make build` | `vite build`, then `ci/check-dist.sh`: shell, seed, every preview and download, the nginx name map, the app's Tailwind classes present, no model endpoint or key-shaped string in the bundle |
| `make seed-check` | rebuilds the seed and fails if the committed `demo/static/` differs |
| `make app-test` | the snapshot's own gate in `app/`: ruff, pytest, eslint, tsc, vitest — so the code published as "runnable" passes its own tests |
| `make smoke` | builds the image, waits for its HEALTHCHECK, probes the shell, CSP, manifest, seed, a preview (HTML, frameable by self) and a download (named `.docx`), `/api/config` → 404, and that writes are refused, the docroot is read-only to the worker and nothing is mounted |

**Never remove a hash from the denylist to make a build pass.** Fix the source
— in the private repository, so the next sync stays clean.

## CI specifics

- **GitHub-hosted runners only.** The repo is public; a pull request's code
  runs on the runner, and a self-hosted one would hand it the machine.
- **The failure mail** (`notify-failure`) is the one path a green run cannot
  prove, so the `notifier` job asserts its credentials every run and sends one
  real message whenever the workflow changes. The secrets are synced from the
  owner's machine.
- **Renovate** (`renovate.json`) ignores `app/**`: a bump there would make the
  published code differ from the tag it claims to be. Patches, pins, digests
  and devDependency minors automerge after the gate; majors, base images and
  the workflow's own actions wait for a person.

## What could still be green and wrong

- **Visual regressions.** No test looks at pixels. A resync that changes the
  app's layout can put the Demo pill on top of something; check at 375 px,
  light and dark ([mobile-and-pwa.md](mobile-and-pwa.md)).
- **A canned answer that no longer fits the app's narrative** — e.g. a new
  status the seeded timelines never reach. The types allow it; only a
  click-through shows it.
- **The live origin.** The smoke runs the image locally; Cloudflare-side
  behaviour (an injected script the CSP blocks, a cached manifest) shows only
  on the public URL.
