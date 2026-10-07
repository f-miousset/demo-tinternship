# Seed data — the fictional world and how it is built

## The world — `seed/world.py`

Everything is invented: the candidate **Alex Martin** (MSc Data Science at the
fictional *École Supérieure des Données*), every company, every person, every
link (all under `example.com` / `example.org`). It holds:

- the master profile, the course and skill lists (each item tagged, so a
  posting can pick the relevant ones);
- the search brief, the hiring playbook and the interview that produced them;
- 26 postings, each with a `pool` — `deck`, `discarded`, `app:<key>` (an
  application), `search:<key>` (revealed by a canned search), `link` or `text`
  (revealed by a canned paste) — and the two sentences its letter is built
  around (`why`, `proof`) in both languages;
- seven applications across the statuses, with their timelines;
- the three canned searches and the two canned pastes.

## The builder — `scripts/build_seed.py` (`make seed`)

Runs in `app/backend`'s own environment, against an empty database in a
temporary directory:

1. builds Alex's four base `.docx` (CV and letter, EN and FR) with
   `[blanks]`, and installs them as the real upload path would;
2. saves the profile, lists, brief and playbook through the backend's services;
3. inserts postings, applications, events, and for each application the
   documents a run would have written — composed per posting, filled by the
   backend's `docx_template`, exactly as `flows.applying_stream` saves them;
4. writes runs with trace events (the real pipelines' agent names, costs from
   `observability/pricing.py`) and Critic verdicts on the real rubrics
   (`agents/rubrics.py`, overall via `critic.weighted_overall`);
5. pre-builds every document a demo run can produce — résumé and letter, both
   languages, every posting — with its preview HTML and `.docx`;
6. reads it all back through the real API (`TestClient`) into
   `demo/static/seed/seed.json`, and the canned answers into `canned.json`.

It also writes `selfhost/example-documents/` — Alex's four base documents, for
trying the real app.

**Deterministic.** Timestamps are pinned, `.docx` zip entries and core
properties are normalised, JSON keys are sorted. Two runs produce identical
bytes; CI's `make seed-check` relies on it. One consequence: ordered data
(a pipeline's stage messages) is stored as lists of pairs, because sorted keys
would reorder an object. → [gotchas.md](gotchas.md)

**The seed's `version` is a hash of its content.** A visitor whose saved state
has another version is started over — mixing a saved state with a different
world would leave ids pointing at nothing.

## Dates

The world is written relative to an epoch (`EPOCH` in `world.py`). On a
visitor's first load, `store.ts::shiftDates` moves every ISO timestamp — and
the date-only `posted_on` / `next_action_date` — by the time since the epoch,
so the deck always reads "posted 3 days ago", never "posted last autumn".
Dates printed *inside* documents (a letter's date line) are not shifted.
