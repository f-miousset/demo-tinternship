# Tinternship — demo

**Live demo: <https://demo-tinternship.fmiousset.com>** · **Run the real thing: <https://f-miousset.github.io/demo-tinternship/>**

Tinternship is a team of AI agents that finds internships worth applying to,
scores each against what you want, and fills in **your own** CV and cover
letter for every one — every decision traced and audited. You triage what the
agents find by swiping a deck: right to save, left to discard, up to pin, down
for later.

This repository holds two things:

- **The demo** — the real app's interface over a fake backend that runs in your
  browser. **No AI is called**: every agent answer was written in advance, and
  runs are replayed so you can watch them. Everything you do stays in your own
  browser; nobody else sees it.
- **The real app's code**, in [`app/`](app/) — the agents, prompts, rubrics,
  API and UI — to read, audit, and run yourself with a Gemini API key.

The candidate in the demo, *Alex Martin*, and every company and person in it
are fictional.

## Try the demo

Open it on your phone — it installs as an app — or a desktop browser:

| try | what happens |
|---|---|
| **Jobs** — swipe the deck | right saves to the Tracker, left discards, up pins, down defers |
| **Run Investigator**, or tap the chat box | the box fills with a search the demo knows; send it and watch the four agents run and new postings land |
| **+ → Link**, tap the box | a posting's link fills in; the Reader scores it and it goes straight to your Tracker |
| An application → **Generate** | Alex's own CV and letter, with only their blanks filled for this posting — preview, download the `.docx` |
| **Tracker** | a follow-up already due, an offer, an interview brief, a contact shortlist |
| **Account → interview** | tap the box to answer the Interrogator, which writes the search brief |
| **Settings → Traces** | every run: agents, model calls, tool calls, tokens, cost, and the Critic's score per criterion |

The **Demo** pill reopens the explanation and resets your data.

## What is worth stealing

- **Fill the candidate's document; don't generate one.** The CV is the
  candidate's own `.docx` with `[blanks]`; a run fills only those, measured to
  keep the page at one page. Formatting survives by construction.
  (`app/backend/src/tinternship_backend/services/docx_template.py`)
- **A prompt is a request; a promise lives in Python.** Result counts, ordering,
  page fit, output language and the quality bar are enforced in code.
- **A Critic gate with real rubrics.** Every document is scored per criterion
  and sent back below the threshold. (`agents/rubrics.py`, `agents/critic.py`)
- **Every link proved before it is saved.** (`services/verification.py`)
- **A demo that cannot drift from the app.** This demo imports the real
  frontend unchanged and swaps only `fetch`; its seed is produced by running
  the real backend offline. ([architecture](documentation/architecture.md))

## Run it yourself

Docker and a Gemini API key:

```bash
git clone https://github.com/f-miousset/demo-tinternship.git
cd demo-tinternship/selfhost
cp ../app/.env.example .env      # put your GOOGLE_API_KEY in it
docker compose up -d --build     # then open http://localhost:8080
```

The full guide — account setup, costs, local models, privacy — is at
<https://f-miousset.github.io/demo-tinternship/>.

## Working on the demo

```bash
make install   # npm ci
make dev       # the demo on http://localhost:5174
make verify    # privacy check, lint, typecheck, tests, build
make seed      # rebuild the seed through the real backend (needs uv)
make smoke     # build the image and prove it serves (needs docker)
```

Start at [CLAUDE.md](CLAUDE.md), the index of [`documentation/`](documentation/).

## Licence

[MIT](LICENSE).
