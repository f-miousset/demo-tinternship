/**
 * The API, answered in the browser.
 *
 * One entry per endpoint the app's frontend calls (`app/frontend/src/lib/api.ts`
 * and its callers), each naming the backend handler it stands in for. Reads
 * come from this visitor's stored state; writes change it and are saved; the
 * agent runs replay pre-written results over a stream paced like a real one.
 *
 * **No model is called, ever.** Where the real endpoint would ask one, the
 * answer here is the pre-written one for that posting (`demo-data/canned.json`,
 * produced offline by scripts/build_seed.py). Free text the visitor types is
 * steered to the nearest canned answer — or, for a link or posting the demo
 * has nothing for, answered with an error that says why.
 *
 * `routes.test.ts` checks that every path the frontend source mentions has a
 * route here, so a resync that adds an endpoint cannot ship without one.
 */
import type { AgentPrompt, ChatMessage, ProfileSource } from "../../../app/frontend/src/lib/types";
import { error, json, sse, text, type StreamStep } from "./http";
import { borrowVerdict, recordAudit, recordRun } from "./runs";
import {
  applicationOut,
  config,

  followUps,
  jobOut,
  listApplications,
  listJobs,
  nowIso,
  progress,
  traceStats,
} from "./serialise";
import { cannedFor, loadSeed, newId, reset, save, store } from "./store";
import type { HiddenJob, State, StoredApplication, StoredArtifact, StoredJob } from "./types";

export interface MockRequest {
  method: string;
  path: string;
  query: URLSearchParams;
  body: any;
}

type Handler = (state: State, request: MockRequest, params: string[]) => Promise<Response> | Response;

const DEMO_NOTE =
  "This is a demo: the agents' answers are pre-written, so it can only read the posting it suggests. " +
  "Clear the box and tap it again to get that one.";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function findApplication(state: State, id: number): StoredApplication {
  const found = state.applications.find((application) => application.id === id);
  if (!found) throw new HttpError(`No application ${id}`, 404);
  return found;
}

function findJob(state: State, id: number): StoredJob {
  const found = state.jobs.find((job) => job.id === id && !job.purged);
  if (!found) throw new HttpError(`No job ${id}`, 404);
  return found;
}

class HttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function addEvent(application: StoredApplication, from: string, to: string, note: string): void {
  application.events.push({ from, to, note, at: nowIso() });
  application.updated_at = nowIso();
}

/** `tools/persistence.py::track_posting` — saying yes to a posting, idempotently. */
function track(state: State, job: StoredJob, note: string, pinned = false): { application: StoredApplication; created: boolean } {
  const existing = state.applications.find((application) => application.job_posting_id === job.id);
  if (existing) {
    existing.trashed_at = null;
    if (pinned) existing.pinned = true;
    existing.updated_at = nowIso();
    return { application: existing, created: false };
  }
  const now = nowIso();
  const application: StoredApplication = {
    id: newId(state),
    job_posting_id: job.id,
    job_key: job.key,
    status: "saved",
    pinned,
    language: job.language === "fr" ? "fr" : "en",
    personalisation: "",
    notes: "",
    next_action: "",
    next_action_date: "",
    applied_at: null,
    trashed_at: null,
    created_at: now,
    updated_at: now,
    events: [{ from: "", to: "saved", note, at: now }],
  };
  state.applications.push(application);
  return { application, created: true };
}

/** Put a canned posting on the list, as a search or a paste would have saved it. */
function reveal(state: State, hidden: HiddenJob): StoredJob {
  state.hidden = state.hidden.filter((job) => job.key !== hidden.key);
  const { pool: _pool, ...job } = hidden;
  const saved: StoredJob = { ...job, id: newId(state), discovered_at: nowIso(), dismissed: false, deferred_at: null };
  state.jobs.push(saved);
  return saved;
}

const phase = (name: string, message: string, delay = 1, track?: string): StreamStep => ({
  event: "phase",
  data: track ? { phase: name, message, track } : { phase: name, message },
  delay,
});

function freshness(jobs: { posted_days_ago: number | null }[]) {
  const buckets = { week: 0, month: 0, quarter: 0, older: 0, undated: 0 };
  for (const { posted_days_ago: age } of jobs) {
    if (age === null) buckets.undated += 1;
    else if (age <= 7) buckets.week += 1;
    else if (age <= 30) buckets.month += 1;
    else if (age <= 90) buckets.quarter += 1;
    else buckets.older += 1;
  }
  return buckets;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// ---------------------------------------------------------------------------
// Jobs — the deck, and the three ways a posting reaches it
// ---------------------------------------------------------------------------

/** Which canned search a free-text focus is closest to. */
export function searchFor(focus: string): string {
  const text = focus.toLowerCase();
  if (/energ|climat|solar|solaire|grid|réseau|hydro|batter|lyon/.test(text)) return "energy";
  if (/nlp|langu|text|texte|health|santé|sante|speech|remote|télétravail|teletravail/.test(text)) return "nlp";
  return "default";
}

const runSearch: Handler = async (state, request) => {
  const seed = await loadSeed();
  const focus = String(request.body?.focus ?? "").trim();
  const key = searchFor(focus);
  const scenario = seed.searches.find((search) => search.key === key) ?? seed.searches[0];
  const target = Number(request.query.get("target_results") ?? 15);
  const runId = newId(state);
  const steps: StreamStep[] = [
    { event: "run", data: { run_id: runId }, delay: 0.2 },
    phase("feedback", "Reading what past applications taught us…", 0.6),
    ...seed.messages.investigator.map(([name, message], index) => phase(name, message, index === 1 ? 2.2 : 1.2)),
    phase("audit", "Auditing the ranking…", 1),
    {
      delay: 0.8,
      produce: async () => {
        const revealed = state.hidden.filter((job) => job.pool === `search:${key}`).map((job) => reveal(state, job));
        const already = state.searched.includes(key);
        if (!already) state.searched.push(key);
        // A second run of the same search finds the same postings again — now
        // already on the deck, which is what the reply says.
        const found = already
          ? state.jobs.filter((job) => seed.hidden_jobs.some((hidden) => hidden.key === job.key && hidden.pool === `search:${key}`))
          : revealed;
        const jobs = found.map((job) => jobOut(state, job));
        const realId = recordRun(state, "investigator", focus ? `Search — ${focus}` : "Search — the brief as written", { target_results: target, focus }, { saved: revealed.length });
        const audit = recordAudit(state, realId, "job_ranking", "", borrowVerdict(state, "job_ranking"));
        save();
        return [
          {
            event: "result",
            data: {
              jobs,
              saved: { saved: jobs.length, created: revealed.length },
              url_check: { ok: jobs.length },
              freshness: freshness(jobs),
              link_drops: {},
              answered_drops: {},
              strategy_notes: already
                ? "Every posting this search finds is already on your deck — the demo has a fixed set of postings. Try one of the other suggestions."
                : scenario.notes,
              feedback_applied: { summary: "Weighted Lyon and forecasting roles up, after the Helio Grid interview." },
              audit,
              run_id: realId,
              target_results: target,
              focus,
            },
          },
        ];
      },
    },
  ];
  return sse(steps);
};

/** The shared tail of both paste paths: save, track, score. */
function importResult(state: State, job: StoredJob, created: boolean, kind: "link_intake" | "text_intake", linkNote = "") {
  const wasDismissed = job.dismissed;
  job.dismissed = false;
  const before = state.applications.find((application) => application.job_posting_id === job.id);
  const wasTrashed = Boolean(before?.trashed_at);
  const { application, created: tracked } = track(state, job, kind === "link_intake" ? "Added by pasting its link." : "Added by pasting its text.");
  const runId = recordRun(state, kind, `${kind === "link_intake" ? "Link" : "Text"} — ${job.company}`, { url: job.url }, { job_id: job.id });
  const audit = recordAudit(state, runId, "job_ranking", String(job.id), borrowVerdict(state, "job_ranking"));
  save();
  return {
    job: jobOut(state, job),
    job_id: job.id,
    saved: { saved: 1, created: created ? 1 : 0, updated: created ? 0 : 1 },
    already_saved: !created,
    restored: wasDismissed,
    untrashed: wasTrashed,
    application_id: application.id,
    tracked,
    url_check: job.url ? { ok: 1 } : { unchecked: 1 },
    ...(kind === "text_intake" ? { link_note: linkNote } : {}),
    audit,
    run_id: runId,
  };
}

const importLink: Handler = async (state, request) => {
  const seed = await loadSeed();
  const url = String(request.body?.url ?? "").trim().replace(/\/+$/, "");
  const known = state.jobs.find((job) => job.url && job.url.replace(/\/+$/, "") === url && !job.purged);
  const hidden = state.hidden.find((job) => job.url && job.url.replace(/\/+$/, "") === url);
  const stages = seed.messages.link_intake;
  if (!known && !hidden) {
    return sse([
      { event: "run", data: { run_id: newId(state) }, delay: 0.2 },
      phase("fetch", "Opening the link…", 1),
      { event: "error", data: { error: DEMO_NOTE }, delay: 1.2 },
    ]);
  }
  return sse([
    { event: "run", data: { run_id: newId(state) }, delay: 0.2 },
    phase("fetch", "Opening the link…", 1),
    ...stages.map(([name, message]) => phase(name, message, 1.6)),
    phase("save", "Saving it to your list…", 0.8),
    phase("audit", "Auditing the score…", 0.8),
    {
      delay: 0.6,
      produce: async () => {
        const job = known ?? reveal(state, hidden!);
        return [{ event: "result", data: importResult(state, job, !known, "link_intake") }];
      },
    },
  ]);
};

const importText: Handler = async (state, request) => {
  const seed = await loadSeed();
  const pasted = String(request.body?.text ?? "");
  const hidden = state.hidden.find((job) => job.pool === "text");
  const known = state.jobs.find((job) => job.key === seed.hidden_jobs.find((item) => item.pool === "text")?.key);
  const matches = /tidewater/i.test(pasted);
  if (!matches || (!hidden && !known)) {
    return sse([
      { event: "run", data: { run_id: newId(state) }, delay: 0.2 },
      phase("reader", "Reading the posting…", 1.2),
      { event: "error", data: { error: DEMO_NOTE.replace("the posting it suggests", "the posting text it suggests") }, delay: 1.2 },
    ]);
  }
  return sse([
    { event: "run", data: { run_id: newId(state) }, delay: 0.2 },
    ...seed.messages.link_intake.map(([name, message]) => phase(name, message, 1.6)),
    phase("verify", "Checking any link the text carried…", 0.8),
    phase("save", "Saving it to your list…", 0.8),
    phase("audit", "Auditing the score…", 0.8),
    {
      delay: 0.6,
      produce: async () => {
        const job = known ?? reveal(state, hidden!);
        return [
          {
            event: "result",
            data: importResult(state, job, !known, "text_intake", "The text carried no link, so the card has none — add the posting's address to its notes if you find it."),
          },
        ];
      },
    },
  ]);
};

// ---------------------------------------------------------------------------
// Applications — the Tracker, and the runs that write for one
// ---------------------------------------------------------------------------

function artifactRow(state: State, application: StoredApplication, kind: string, content: Record<string, any>, runId: number, id?: number, textBody?: string): StoredArtifact {
  const version = Math.max(0, ...state.artifacts.filter((a) => a.application_id === application.id && a.kind === kind).map((a) => a.version)) + 1;
  const existing = id !== undefined ? state.artifacts.find((artifact) => artifact.id === id) : undefined;
  const row: StoredArtifact = {
    id: id ?? newId(state),
    application_id: application.id,
    kind: kind as StoredArtifact["kind"],
    version,
    revisions: 0,
    rendered_path: "",
    created_at: nowIso(),
    content,
    run_id: runId,
    invocation_id: `e-demo-${runId}`,
    audit: null,
    text: textBody,
  };
  // A canned document has one id, so a second run "writing" it again becomes
  // its next version in place rather than a row the preview cannot find.
  if (existing) Object.assign(existing, row);
  else state.artifacts.push(row);
  return existing ?? row;
}

const generate: Handler = async (state, request, [id]) => {
  const seed = await loadSeed();
  const application = findApplication(state, Number(id));
  const body = request.body ?? {};
  const language: "en" | "fr" = body.language === "fr" || body.language === "en" ? body.language : application.language;
  const kinds = [...(body.resume !== false ? ["resume"] : []), ...(body.cover_letter ? ["cover_letter"] : [])];
  if (kinds.length === 0) return error("Nothing to generate: ask for the résumé, the cover letter, or both.");
  application.language = language;
  if (typeof body.personalisation === "string") application.personalisation = body.personalisation.trim();
  if (application.status === "saved") {
    application.status = "preparing";
    addEvent(application, "saved", "preparing", "Generating the application package.");
  }
  save();
  const canned = await cannedFor(application.job_key);
  const runId = newId(state);
  const label = (kind: string) => seed.messages.tracks[kind] ?? kind;
  const stage = (kind: string, name: string) => seed.messages.stages[name].replace("{label}", label(kind));
  const steps: StreamStep[] = [{ event: "run", data: { run_id: runId }, delay: 0.2 }];
  if (kinds.includes("resume")) steps.push(phase("writing", stage("resume", "writing"), 1, "resume"));
  if (kinds.includes("cover_letter")) {
    steps.push(phase("researching", stage("cover_letter", "researching"), 1, "cover_letter"));
    steps.push(phase("writing", stage("cover_letter", "writing"), 1.6, "cover_letter"));
  }
  for (const kind of kinds) steps.push(phase("reviewing", stage(kind, "reviewing"), 1.4, kind));
  if (kinds.includes("cover_letter")) steps.push(phase("humanising", stage("cover_letter", "humanising"), 1.2, "cover_letter"));
  for (const kind of kinds) {
    const document = canned.documents[`${kind}:${language}`];
    steps.push(phase("gate", `Audit ${label(kind)}: ${document.audit.overall.toFixed(1)}/10 — passed.`, 1, kind));
  }
  steps.push({
    delay: 0.6,
    produce: async () => {
      const real = recordRun(state, "applying", `Applying — ${findJob(state, application.job_posting_id).company}`, { language, resume: kinds.includes("resume"), cover_letter: kinds.includes("cover_letter") }, { artifacts: kinds });
      const artifacts: Record<string, { id: number; kind: string; version: number }> = {};
      const events: { event: string; data: unknown }[] = [];
      for (const kind of kinds) {
        const document = canned.documents[`${kind}:${language}`];
        const row = artifactRow(state, application, kind, document.content, real, document.id, document.text);
        row.audit = recordAudit(state, real, kind, "", document.audit);
        artifacts[kind] = { id: row.id, kind, version: row.version };
        events.push({ event: "phase", data: { phase: "saved", track: kind, message: stage(kind, "saved") } });
      }
      application.updated_at = nowIso();
      save();
      return [...events, { event: "result", data: { artifacts, run_id: real } }];
    },
  });
  return sse(steps);
};

/** Interview brief, contact shortlist and follow-up: one artifact, one track. */
function singleArtifactRun(kind: "interview_prep" | "contacts" | "follow_up", runKind: string, messagesKey: "interview_prep" | "contacts" | "follow_up"): Handler {
  return async (state, _request, [id]) => {
    const seed = await loadSeed();
    const application = findApplication(state, Number(id));
    const canned = await cannedFor(application.job_key);
    const messages = seed.messages[messagesKey];
    const order = ["researching", "writing", "reviewing", "gate", "sources", "links"].filter((name) => messages[name]);
    const runId = newId(state);
    return sse([
      { event: "run", data: { run_id: runId }, delay: 0.2 },
      ...order.map((name) => phase(name, messages[name], name === "researching" ? 2 : 1.2)),
      {
        delay: 0.6,
        produce: async () => {
          const company = findJob(state, application.job_posting_id).company;
          const real = recordRun(state, runKind, `${{ interview_prep: "Interview brief", contacts: "Contacts", follow_up: "Follow-up" }[kind]} — ${company}`, { application_id: application.id }, {});
          const content = structuredClone(kind === "follow_up" ? canned.follow_up : kind === "contacts" ? canned.contacts : canned.interview_prep);
          const row = artifactRow(state, application, kind, content, real);
          row.audit = recordAudit(state, real, kind, "", borrowVerdict(state, kind));
          save();
          return [
            { event: "phase", data: { phase: "saved", message: messages.saved } },
            { event: "result", data: { artifact: { id: row.id, kind, version: row.version }, run_id: real } },
          ];
        },
      },
    ]);
  };
}

const contactMessage: Handler = async (state, request, [id]) => {
  const application = findApplication(state, Number(id));
  const canned = await cannedFor(application.job_key);
  const shortlist = state.artifacts
    .filter((artifact) => artifact.application_id === application.id && artifact.kind === "contacts")
    .sort((a, b) => b.version - a.version)[0];
  if (!shortlist) return error("Find the people to contact first.", 404);
  const index = Number(request.body?.index ?? 0);
  const person = shortlist.content.people?.[index];
  if (!person) return error(`No contact ${index} on that shortlist.`, 404);
  await sleep(1800);
  const line = canned.contact_messages[person.name] ?? `Hello ${String(person.name).split(" ")[0]} — I'm applying for this internship and would value two minutes of your advice.`;
  person.opening_line = line;
  person.opening_line_over_limit = line.length > 300;
  const runId = recordRun(state, "contact_message", `Message — ${person.name}`, { index }, { length: line.length });
  save();
  return json({ opening_line: line, over_limit: line.length > 300, artifact_id: shortlist.id, index, name: person.name, run_id: runId });
};

const reaudit: Handler = async (state, _request, [id]) => {
  const artifact = state.artifacts.find((item) => item.id === Number(id));
  if (!artifact) return error(`No artifact ${id}`, 404);
  await sleep(1600);
  const verdict = artifact.audit ?? borrowVerdict(state, artifact.kind);
  const runId = recordRun(state, "applying", `Re-audit — ${artifact.kind.replace("_", " ")} v${artifact.version}`, { artifact_id: artifact.id }, {});
  artifact.audit = recordAudit(state, runId, artifact.kind, String(artifact.id), { ...verdict, revision: 0 });
  save();
  return json(artifact.audit);
};

// ---------------------------------------------------------------------------
// Account — the profile, the interview, the brief and the playbook
// ---------------------------------------------------------------------------

async function interviewScript() {
  const seed = await loadSeed();
  const assistant = seed.interview.filter((message) => message.role === "assistant").map((message) => message.text);
  const user = ["Hi — I'm looking for my end-of-studies internship.", ...seed.interview.filter((m) => m.role === "user").map((m) => m.text)];
  return { assistant, user };
}

/** The next thing the visitor would say, for the interview box's auto-fill. */
export async function nextInterviewLine(): Promise<string> {
  const state = await store();
  const { user } = await interviewScript();
  const said = state.interview.filter((message) => message.role === "assistant").length;
  return user[said] ?? "One more thing: I'd also consider Bordeaux for the right team.";
}

const interviewMessage: Handler = async (state, request) => {
  const { assistant } = await interviewScript();
  const message = String(request.body?.message ?? "").trim();
  if (!message) return error("Say something first.");
  const turn = state.interview.filter((item) => item.role === "assistant").length;
  const reply =
    assistant[turn] ??
    "Noted — I'll keep that in mind. Your brief is already written; edit it on step 3 or start the interview over to rewrite it. (Demo: the interviewer's lines are pre-written.)";
  const complete = turn === assistant.length - 1;
  state.interview.push({ role: "user", author: "user", text: message });
  save();
  return sse([
    { event: "event", data: { text: "", partial: true }, delay: 0.4 },
    {
      delay: 1.8,
      produce: async () => {
        state.interview.push({ role: "assistant", author: "interrogator", text: reply });
        if (turn === 0) recordRun(state, "interrogator", "Interview — internship preferences", { turns: 1 }, {});
        save();
        return [
          { event: "event", data: { text: reply, partial: false } },
          ...(complete ? [{ event: "complete", data: { session_id: "interview" } }] : []),
        ];
      },
    },
  ]);
};

function newPrompt(state: State, kind: string, from: AgentPrompt, fields: Partial<AgentPrompt>): AgentPrompt {
  for (const prompt of state.prompts) if (prompt.kind === kind) prompt.is_active = false;
  const prompt: AgentPrompt = {
    ...from,
    id: newId(state),
    version: Math.max(0, ...state.prompts.filter((item) => item.kind === kind).map((item) => item.version)) + 1,
    is_active: true,
    created_at: nowIso(),
    audit: null,
    ...fields,
  };
  state.prompts.unshift(prompt);
  return prompt;
}

function promptOut(state: State, prompt: AgentPrompt): AgentPrompt {
  const subject = prompt.kind === "search_brief" ? "brief" : prompt.kind;
  const audit = state.audits.find((record) => record.subject_kind === subject && record.subject_id === String(prompt.id));
  if (!audit) return { ...prompt, audit: prompt.audit ?? null };
  const { id: _id, subject_kind: _k, subject_id: _s, blocking: _b, run_id: _r, created_at: _c, ...summary } = audit;
  return { ...prompt, audit: summary };
}

async function seededPrompt(kind: string): Promise<AgentPrompt> {
  const seed = await loadSeed();
  return seed.prompts.find((prompt) => prompt.kind === kind)!;
}

const finalise: Handler = async (state) => {
  await sleep(2600);
  const template = await seededPrompt("search_brief");
  const runId = recordRun(state, "interrogator", "Brief writer — from the interview", {}, { brief: template.title });
  const prompt = newPrompt(state, "search_brief", template, { author: "agent", note: "Written by the brief writer from the interview." });
  const audit = recordAudit(state, runId, "brief", String(prompt.id), borrowVerdict(state, "brief"));
  save();
  return json({ brief: template.structured, prompt: promptOut(state, prompt), audit, run_id: runId });
};

const hrExpert: Handler = async (state) => {
  const seed = await loadSeed();
  return sse([
    { event: "run", data: { run_id: newId(state) }, delay: 0.2 },
    ...seed.messages.hr_expert.map(([name, message], index) => phase(name, message, index === 0 ? 2.4 : 1.6)),
    phase("save", "Saving the playbook as a new version…", 0.8),
    phase("audit", "Auditing the playbook…", 1),
    {
      delay: 0.6,
      produce: async () => {
        const template = await seededPrompt("playbook");
        const runId = recordRun(state, "hr_expert", "HR Expert — data science internships, France", {}, { sections: 12 });
        const prompt = newPrompt(state, "playbook", template, { author: "agent", note: "Researched by the HR Expert." });
        const audit = recordAudit(state, runId, "playbook", String(prompt.id), borrowVerdict(state, "playbook"));
        save();
        return [{ event: "result", data: { playbook: template.structured, prompt: promptOut(state, prompt), audit, run_id: runId } }];
      },
    },
  ]);
};

function uploadedName(body: any): string {
  const file = body instanceof FormData ? body.get("file") : null;
  return file instanceof File ? file.name : "document.docx";
}

const uploadProfile: Handler = async (state, request) => {
  await sleep(2200);
  const name = uploadedName(request.body);
  const source: ProfileSource = {
    id: newId(state),
    kind: name.toLowerCase().endsWith(".pdf") ? "upload_pdf" : "upload_docx",
    label: name,
    status: "parsed",
    error: "",
    source_url: "",
    file_name: "",
    can_preview: false,
    created_at: nowIso(),
  };
  state.profile.sources.unshift(source);
  recordRun(state, "profile_parse", `Profile — ${name}`, { file: name }, { merged: true });
  save();
  // The demo never reads the file: the profile stays Alex's, which the notice says.
  return json({ source_id: source.id, kind: source.kind, extracted: state.profile.profile, profile: state.profile.profile });
};

const uploadBase: Handler = async (state, request, [kind, language]) => {
  await sleep(1400);
  const name = uploadedName(request.body);
  const documents = kind === "resume" ? state.profile.base_resumes : state.profile.base_cover_letters;
  const seed = await loadSeed();
  const previous = (kind === "resume" ? seed.profile.base_resumes : seed.profile.base_cover_letters)[language as "en" | "fr"];
  const document = { ...previous!, id: newId(state), label: name, created_at: nowIso() };
  documents[language as "en" | "fr"] = document;
  save();
  return json({
    source_id: document.id,
    kind,
    language,
    blocks: 24,
    placeholders: document.placeholders,
    page: document.page,
    room: document.room,
    crowded: document.crowded,
    language_warning: "",
    status: "parsed",
    error: "",
    profile: state.profile.profile,
  });
};

// ---------------------------------------------------------------------------
// The table
// ---------------------------------------------------------------------------

const ROUTES: [string, RegExp, Handler][] = [
  // api/system.py, api/account.py
  ["GET", /^\/api\/health$/, () => json({ status: "ok" })],
  ["GET", /^\/api\/config$/, async (state) => json(config(state, (await loadSeed()).config))],
  ["GET", /^\/api\/account$/, async (state) => json({ ...(await loadSeed()).account, setup: progress(state) })],

  // api/jobs.py
  ["GET", /^\/api\/jobs$/, (state, request) => json(listJobs(state, request.query.get("view") ?? "deck"))],
  ["POST", /^\/api\/jobs\/search$/, runSearch],
  ["GET", /^\/api\/jobs\/search\/history$/, (state) => json({ items: [...state.history].sort((a, b) => b.timestamp - a.timestamp) })],
  ["POST", /^\/api\/jobs\/search\/history$/, (state, request) => {
    const textValue = String(request.body?.text ?? "").trim();
    if (!textValue) return error("Query text cannot be empty");
    const now = nowIso();
    const existing = state.history.find((item) => item.text.toLowerCase() === textValue.toLowerCase());
    const item = existing ?? { id: String(newId(state)), text: textValue, created_at: now, updated_at: now, timestamp: Date.now() };
    Object.assign(item, { updated_at: now, timestamp: Date.now() });
    if (!existing) state.history.push(item);
    save();
    return json(item);
  }],
  ["POST", /^\/api\/jobs\/search\/history\/sync$/, (state, request) => {
    for (const entry of request.body?.items ?? []) {
      const textValue = String(entry.text ?? "").trim();
      if (!textValue || state.history.some((item) => item.text.toLowerCase() === textValue.toLowerCase())) continue;
      const at = new Date(entry.timestamp ?? Date.now()).toISOString();
      state.history.push({ id: String(newId(state)), text: textValue, created_at: at, updated_at: at, timestamp: Date.parse(at) });
    }
    save();
    return json({ items: [...state.history].sort((a, b) => b.timestamp - a.timestamp) });
  }],
  ["DELETE", /^\/api\/jobs\/search\/history\/(\w+)$/, (state, _request, [id]) => {
    const before = state.history.length;
    state.history = state.history.filter((item) => item.id !== id);
    save();
    return before === state.history.length ? error("Not found", 404) : json({ deleted: true, id });
  }],
  ["DELETE", /^\/api\/jobs\/search\/history$/, (state) => {
    const count = state.history.length;
    state.history = [];
    save();
    return json({ deleted_count: count });
  }],
  ["POST", /^\/api\/jobs\/import$/, importLink],
  ["POST", /^\/api\/jobs\/import-text$/, importText],
  ["POST", /^\/api\/jobs\/(\d+)\/defer$/, (state, _request, [id]) => {
    const job = findJob(state, Number(id));
    job.deferred_at = nowIso();
    save();
    return json({ id: job.id, deferred_at: job.deferred_at });
  }],
  ["POST", /^\/api\/jobs\/(\d+)\/dismiss$/, (state, request, [id]) => {
    const job = findJob(state, Number(id));
    job.dismissed = request.query.get("dismissed") !== "false";
    save();
    return json({ id: job.id, dismissed: job.dismissed });
  }],
  ["DELETE", /^\/api\/jobs\/trash$/, (state) => {
    const trashed = state.jobs.filter((job) => job.dismissed && !job.purged);
    for (const job of trashed) job.purged = true;
    save();
    return json({ deleted: trashed.length, files: 0 });
  }],
  ["DELETE", /^\/api\/jobs\/(\d+)$/, (state, _request, [id]) => {
    const job = findJob(state, Number(id));
    if (!job.dismissed) return error("Only a posting in the trash can be deleted forever.", 409);
    job.purged = true;
    save();
    return json({ deleted: 1, files: 0 });
  }],
  ["GET", /^\/api\/jobs\/(\d+)$/, (state, _request, [id]) => json(jobOut(state, findJob(state, Number(id))))],

  // api/applications.py
  ["GET", /^\/api\/applications$/, (state, request) => json(listApplications(state, request.query.get("view") ?? "board"))],
  ["POST", /^\/api\/applications$/, (state, request) => {
    const job = findJob(state, Number(request.body?.job_posting_id));
    const pinned = Boolean(request.body?.pinned);
    const { application } = track(state, job, pinned ? "Pinned from the deck." : "Saved from the deck.", pinned);
    save();
    return json(applicationOut(state, application));
  }],
  ["GET", /^\/api\/applications\/follow-ups$/, (state) => json(followUps(state))],
  ["DELETE", /^\/api\/applications\/trash$/, (state) => {
    const trashed = state.applications.filter((application) => application.trashed_at);
    for (const application of trashed) {
      const job = state.jobs.find((item) => item.id === application.job_posting_id);
      if (job) job.purged = true;
    }
    state.applications = state.applications.filter((application) => !application.trashed_at);
    state.artifacts = state.artifacts.filter((artifact) => state.applications.some((a) => a.id === artifact.application_id));
    save();
    return json({ deleted: trashed.length, files: 0 });
  }],
  ["GET", /^\/api\/applications\/artifacts\/(\d+)\/text$/, (state, _request, [id]) => {
    const artifact = state.artifacts.find((item) => item.id === Number(id));
    return artifact?.text ? text(artifact.text) : error("That document has no text form.", 404);
  }],
  ["POST", /^\/api\/applications\/artifacts\/(\d+)\/reaudit$/, reaudit],
  ["GET", /^\/api\/applications\/(\d+)$/, (state, _request, [id]) => json(applicationOut(state, findApplication(state, Number(id)), true))],
  ["PATCH", /^\/api\/applications\/(\d+)$/, (state, request, [id]) => {
    const application = findApplication(state, Number(id));
    const body = request.body ?? {};
    if (body.status && body.status !== application.status) {
      const previous = application.status;
      application.status = body.status;
      if (body.status === "applied" && !application.applied_at) application.applied_at = nowIso();
      addEvent(application, previous, body.status, body.note ?? "");
    } else if (body.note) {
      addEvent(application, application.status, application.status, body.note);
    }
    for (const field of ["pinned", "notes", "next_action", "next_action_date"] as const) {
      if (body[field] !== undefined && body[field] !== null) (application as any)[field] = body[field];
    }
    application.updated_at = nowIso();
    save();
    return json(applicationOut(state, application));
  }],
  ["POST", /^\/api\/applications\/(\d+)\/trash$/, (state, request, [id]) => {
    const application = findApplication(state, Number(id));
    application.trashed_at = request.query.get("trashed") === "false" ? null : nowIso();
    save();
    return json(applicationOut(state, application));
  }],
  ["DELETE", /^\/api\/applications\/(\d+)$/, (state, _request, [id]) => {
    const application = findApplication(state, Number(id));
    if (!application.trashed_at) return error("Move it to the trash before deleting it forever.", 409);
    const job = state.jobs.find((item) => item.id === application.job_posting_id);
    if (job) job.purged = true;
    state.applications = state.applications.filter((item) => item.id !== application.id);
    state.artifacts = state.artifacts.filter((artifact) => artifact.application_id !== application.id);
    save();
    return json({ deleted: 1, files: 0 });
  }],
  ["GET", /^\/api\/applications\/(\d+)\/artifacts$/, (state, _request, [id]) => {
    const rows = state.artifacts
      .filter((artifact) => artifact.application_id === Number(id))
      .sort((a, b) => a.kind.localeCompare(b.kind) || b.version - a.version)
      .map(({ application_id: _a, text: _t, ...artifact }) => artifact);
    return json({ artifacts: rows });
  }],
  ["POST", /^\/api\/applications\/(\d+)\/generate$/, generate],
  ["POST", /^\/api\/applications\/(\d+)\/interview-prep$/, singleArtifactRun("interview_prep", "interview_prep", "interview_prep")],
  ["POST", /^\/api\/applications\/(\d+)\/contacts$/, singleArtifactRun("contacts", "contacts", "contacts")],
  ["POST", /^\/api\/applications\/(\d+)\/contacts\/message$/, contactMessage],
  ["POST", /^\/api\/applications\/(\d+)\/follow-up$/, singleArtifactRun("follow_up", "follow_up", "follow_up")],
  ["POST", /^\/api\/applications\/(\d+)\/follow-up\/(sent|no-contact)$/, (state, _request, [id, which]) => {
    const application = findApplication(state, Number(id));
    addEvent(application, application.status, application.status, which === "sent" ? "Follow-up email sent." : "Follow-up not sent: nobody found to send it to.");
    save();
    return json(applicationOut(state, application));
  }],

  // api/profile.py
  ["GET", /^\/api\/profile$/, (state) => json({ ...state.profile, has_profile: Boolean(state.profile.profile?.full_name) })],
  ["PATCH", /^\/api\/profile$/, (state, request) => {
    for (const [key, value] of Object.entries(request.body ?? {})) if (value !== null && value !== undefined) state.profile.profile[key] = value;
    save();
    return json({ profile: state.profile.profile });
  }],
  ["PUT", /^\/api\/profile\/master$/, (state, request) => {
    state.profile.profile = { ...state.profile.profile, ...(request.body?.profile ?? {}) };
    save();
    return json({ profile: state.profile.profile, updated_at: nowIso() });
  }],
  ["POST", /^\/api\/profile\/upload$/, uploadProfile],
  ["POST", /^\/api\/profile\/base-document\/(resume|cover_letter)\/(en|fr)$/, uploadBase],
  ["DELETE", /^\/api\/profile\/base-document\/(resume|cover_letter)\/(en|fr)$/, (state, _request, [kind, language]) => {
    const documents = kind === "resume" ? state.profile.base_resumes : state.profile.base_cover_letters;
    documents[language as "en" | "fr"] = null;
    save();
    return json({ status: "ok", kind, language, profile: state.profile.profile });
  }],
  ["DELETE", /^\/api\/profile\/sources\/(\d+)$/, (state, _request, [id]) => {
    state.profile.sources = state.profile.sources.filter((source) => source.id !== Number(id));
    save();
    return json({ status: "ok", profile: state.profile.profile });
  }],
  ["GET", /^\/api\/profile\/lists$/, (state) => json({ lists: state.lists })],
  ["POST", /^\/api\/profile\/lists$/, (state, request) => {
    const { kind, en, fr } = request.body ?? {};
    if (kind !== "course" && kind !== "skill") return error(`Unknown list ${kind}`);
    if (!String(en ?? "").trim() || !String(fr ?? "").trim()) return error("Both the English and the French are required.");
    const item = { id: newId(state), kind, en: String(en).trim(), fr: String(fr).trim(), position: state.lists[kind as "course" | "skill"].length };
    state.lists[kind as "course" | "skill"].push(item);
    save();
    return json({ lists: state.lists, item });
  }],
  ["PATCH", /^\/api\/profile\/lists\/(\d+)$/, (state, request, [id]) => {
    const item = [...state.lists.course, ...state.lists.skill].find((entry) => entry.id === Number(id));
    if (!item) return error(`No item ${id}`, 404);
    item.en = String(request.body?.en ?? item.en).trim();
    item.fr = String(request.body?.fr ?? item.fr).trim();
    save();
    return json({ lists: state.lists, item });
  }],
  ["DELETE", /^\/api\/profile\/lists\/(\d+)$/, (state, _request, [id]) => {
    state.lists.course = state.lists.course.filter((entry) => entry.id !== Number(id));
    state.lists.skill = state.lists.skill.filter((entry) => entry.id !== Number(id));
    save();
    return json({ lists: state.lists });
  }],

  // api/interview.py, api/strategy.py
  ["GET", /^\/api\/interview\/history$/, (state) => json({ session_id: "interview", messages: state.interview })],
  ["POST", /^\/api\/interview\/message$/, interviewMessage],
  ["POST", /^\/api\/interview\/finalise$/, finalise],
  ["POST", /^\/api\/interview\/reset$/, (state) => {
    state.interview = [] as ChatMessage[];
    save();
    return json({ status: "ok", session_id: "interview" });
  }],
  ["POST", /^\/api\/strategy\/hr-expert$/, hrExpert],
  ["GET", /^\/api\/strategy\/prompts$/, (state, request) => {
    const kind = request.query.get("kind");
    const rows = state.prompts.filter((prompt) => !kind || prompt.kind === kind).sort((a, b) => a.kind.localeCompare(b.kind) || b.version - a.version);
    return json({ prompts: rows.map((prompt) => promptOut(state, prompt)) });
  }],
  ["GET", /^\/api\/strategy\/prompts\/active$/, (state) => {
    const active = (kind: string) => {
      const found = state.prompts.find((prompt) => prompt.kind === kind && prompt.is_active);
      return found ? promptOut(state, found) : null;
    };
    return json({ search_brief: active("search_brief"), playbook: active("playbook") });
  }],
  ["PUT", /^\/api\/strategy\/prompts\/(search_brief|playbook)$/, (state, request, [kind]) => {
    const current = state.prompts.find((prompt) => prompt.kind === kind && prompt.is_active) ?? state.prompts.find((p) => p.kind === kind)!;
    const body = request.body ?? {};
    const prompt = newPrompt(state, kind, current, {
      content: String(body.content ?? current.content),
      structured: body.structured ?? current.structured,
      title: body.title || current.title,
      note: body.note ?? "Edited by hand.",
      author: "user",
    });
    save();
    return json(promptOut(state, prompt));
  }],
  ["POST", /^\/api\/strategy\/prompts\/(\d+)\/activate$/, (state, _request, [id]) => {
    const prompt = state.prompts.find((item) => item.id === Number(id));
    if (!prompt) return error(`No prompt ${id}`, 404);
    for (const other of state.prompts) if (other.kind === prompt.kind) other.is_active = other.id === prompt.id;
    save();
    return json(promptOut(state, prompt));
  }],

  // api/settings.py
  ["GET", /^\/api\/settings\/config$/, (state) => json(state.settings)],
  ["PUT", /^\/api\/settings\/config$/, (state, request) => {
    for (const field of state.settings.fields) {
      const value = request.body?.[field.key];
      if (value === undefined || value === null || value === "") continue;
      field.value = field.kind === "number" ? Number(value) : String(value);
      field.overridden = field.value !== field.default;
    }
    save();
    return json(state.settings);
  }],
  ["DELETE", /^\/api\/settings\/config$/, (state) => {
    for (const field of state.settings.fields) Object.assign(field, { value: field.default, overridden: false });
    save();
    return json(state.settings);
  }],
  ["GET", /^\/api\/settings\/data$/, async (state) => {
    const seed = await loadSeed();
    return json({ ...seed.settings_data, summary: summary(state) });
  }],
  ["POST", /^\/api\/settings\/reset$/, async (_state, request) => {
    const seed = await loadSeed();
    if (String(request.body?.confirm ?? "") !== seed.settings_data.confirm_phrase) {
      return error(`This cannot be undone. Type ${seed.settings_data.confirm_phrase} to confirm.`);
    }
    // In the demo "delete my data" means "start the demo over": the seed comes
    // back, and the visitor's own changes go — from this browser, the only place
    // they ever were.
    await reset();
    return json({ status: "ok", deleted: {}, summary: summary(await store()) });
  }],

  // api/traces.py
  ["GET", /^\/api\/traces\/stats$/, (state) => json(traceStats(state))],
  ["GET", /^\/api\/traces\/runs$/, (state, request) => {
    const kind = request.query.get("kind");
    const limit = Number(request.query.get("limit") ?? 100);
    const runs = state.runs
      .filter(({ run }) => !kind || run.kind === kind)
      .sort((a, b) => Date.parse(b.run.started_at) - Date.parse(a.run.started_at))
      .slice(0, limit)
      .map(({ run, events }) => ({ ...run, event_count: events.length }));
    return json({ runs });
  }],
  ["GET", /^\/api\/traces\/runs\/(\d+)$/, (state, _request, [id]) => {
    const found = state.runs.find(({ run }) => run.id === Number(id));
    return found ? json(found) : error(`No run ${id}`, 404);
  }],
  ["GET", /^\/api\/traces\/audits$/, (state, request) => {
    const limit = Number(request.query.get("limit") ?? 200);
    const audits = [...state.audits].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, limit);
    return json({ audits });
  }],
];

function summary(state: State): Record<string, number> {
  return {
    applications: state.applications.length,
    artifacts: state.artifacts.length,
    audits: state.audits.length,
    jobs: state.jobs.filter((job) => !job.purged).length,
    profile: state.profile.profile?.full_name ? 1 : 0,
    profile_sources: state.profile.sources.length + 4,
    prompts: state.prompts.length,
    runs: state.runs.length,
    search_queries: state.history.length,
    trace_events: state.runs.reduce((total, run) => total + run.events.length, 0),
  };
}

/** Every route, for the contract test. */
export const routeTable = ROUTES.map(([method, pattern]) => ({ method, pattern }));

/** Answer one API request. Never throws: a failure is a JSON error, as the backend's would be. */
export async function handle(request: MockRequest): Promise<Response> {
  try {
    const state = await store();
    for (const [method, pattern, handler] of ROUTES) {
      if (method !== request.method) continue;
      const match = pattern.exec(request.path);
      if (match) return await handler(state, request, match.slice(1));
    }
    return error(`The demo has no ${request.method} ${request.path}.`, 404);
  } catch (failure) {
    if (failure instanceof HttpError) return error(failure.message, failure.status);
    return error(failure instanceof Error ? failure.message : String(failure), 500);
  }
}

