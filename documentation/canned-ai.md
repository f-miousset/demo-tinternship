# Canned AI — what every agent run does in the demo

**No model is ever called.** Every place the real app runs an agent, the demo
streams the real pipeline's progress lines and then returns an answer written
in advance (`demo-data/canned.json`, produced offline by `make seed`). The run
is logged on Traces like a real one, with the real agents' names — the tokens
and cost there are illustrative, and each event says it was simulated.

| where | endpoint | what comes back |
|---|---|---|
| Jobs → chat / Run Investigator | `POST /api/jobs/search` | the focus is matched to one of three canned searches (energy, NLP, the brief as written) by keyword; the first time, its postings are revealed on the deck; after that it finds the same postings again and says so |
| Jobs → + → Link | `POST /api/jobs/import` | the suggested link reveals *Papyrus AI* and puts it on the Tracker; **any other link is answered with an error that says why** |
| Jobs → + → Text | `POST /api/jobs/import-text` | text naming *Tidewater* reveals that posting; anything else gets the same explanatory error |
| Application → Generate | `POST …/generate` | the résumé and/or letter for that posting in the chosen language — filled by the real `.docx` filler at build time, with real previews and downloads |
| Application → interview brief, contacts, follow-up | `POST …/interview-prep`, `…/contacts`, `…/follow-up` | a templated brief, a shortlist of fictional people, a chase e-mail |
| Contacts → Write the message | `POST …/contacts/message` | a pre-written note for that person |
| Re-audit | `POST …/artifacts/<id>/reaudit` | the document's own verdict again |
| Account → interview | `POST /api/interview/message` | the scripted Interrogator; the last scripted turn ends the interview, after which every reply says the brief is written |
| Account → brief, playbook | `POST /api/interview/finalise`, `/api/strategy/hr-expert` | a new version of the seeded brief / playbook |
| Account → uploads | `POST /api/profile/upload`, `…/base-document/…` | accepted and listed under the uploaded name; **the file is never read** — the profile stays Alex's |

## Auto-fill — `demo/src/demo/autofill.ts`

Focusing an **empty** box that feeds an agent fills it with something the demo
has an answer for, and a toast says what happened. Boxes are found by the
attributes the app already gives them, so the app stays unmodified:

| box | found by | fills |
|---|---|---|
| Jobs chat | `placeholder` starting "A company, a kind of role" | the next canned search not yet run |
| Paste a link | `placeholder="Paste a job posting link"` | the Papyrus AI link |
| Paste a posting | `placeholder` starting "Paste the whole posting" | the Tidewater posting's text |
| Interview | `placeholder` starting "Describe the internship you want" | the candidate's next scripted answer |
| Generate dialog | `aria-label="What you know about this employer"` | an optional personal note |

A resync that renames any of these fails `mock.test.ts`, which looks for each
attribute in `app/frontend/src`, instead of silently leaving a box empty.

## The notice — `demo/src/demo/DemoNotice.tsx`

Shown once per browser session over the app (the app's own `Modal`): no AI is
called, tap a box to get a prompt, your changes stay in this browser,
everyone is fictional — with links to the source and the self-hosting guide.
A **Demo** pill stays on screen to reopen it; that is also where *Reset the
demo* lives. Settings → delete-all does the same reset.

## Writing a new canned answer

Canned content is data in `seed/world.py` (postings and their sentences) and
templates in `scripts/build_seed.py` (documents, briefs, shortlists). Edit
there, run `make seed`, commit the regenerated `demo/static/`. Never hand-edit
`demo/static/` — `make seed-check` in CI rebuilds it and fails on a
difference.
