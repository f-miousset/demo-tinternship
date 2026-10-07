export interface AppConfig {
  models: { primary: string; fast: string; grounded: string };
  gemini_configured: boolean;
  job_sources: string[];
  priority_platforms: string[];
  results: { default: number; min: number; max: number };
  /** Which of the four base documents exist — the CV and the letter, in each
   *  language. `null` for one that has not been uploaded: the application page
   *  greys that choice out rather than letting a run open and fail. */
  base_resumes: Record<PackageLanguage, BaseDocument | null>;
  base_cover_letters: Record<PackageLanguage, BaseDocument | null>;
  audit: { threshold: number; max_revisions: number };
  /** The steps of the Account page. `complete` gates the numbered screens, and
   *  ignores `has_interview` — starting the interview over must not lock the
   *  app over a brief and a playbook that still exist. See
   *  `services/onboarding.py`. */
  progress: {
    has_base_resumes: boolean;
    /** Both base cover letters. Separate from the résumés because they are
     *  separate uploads and each blocks an application on its own — a run
     *  produces two documents. */
    has_base_letters: boolean;
    has_profile: boolean;
    /** Both of the two lists the résumé's blanks are filled from. Required:
     *  a coursework or skills blank with no list behind it leaves the Tailor
     *  choosing between an unfinished sentence and an invented qualification. */
    has_lists: boolean;
    has_interview: boolean;
    has_brief: boolean;
    has_playbook: boolean;
    complete: boolean;
  };
  warnings: string[];
}

/**
 * One setting the Settings page may change without a backend restart.
 *
 * `value` is what the app is running now, `default` is what `.env` says, and
 * `overridden` is the difference between them — see
 * `services/runtime_config.py` for why only a few settings are in this list.
 */
export interface ConfigField {
  key: string;
  label: string;
  help: string;
  kind: "model" | "number";
  min: number | null;
  max: number | null;
  step: number | null;
  /** Which providers a model field accepts — the search model is Gemini-only. */
  providers: string[];
  value: string | number;
  default: string | number;
  overridden: boolean;
}

/** One model the app can run on, from either provider. */
export interface ModelOption {
  /** Gemini ids are bare; local ones are prefixed `ollama/`. */
  id: string;
  /** The provider's own name for it — "Gemini 3.6 Flash". Empty if unknown. */
  label: string;
  provider: "gemini" | "ollama";
  /** Really on this machine. False for an Ollama `…-cloud` model. */
  local: boolean;
  /** Where an Ollama model actually runs, when it is not here — "ollama.com". */
  remote_host: string;
  /** Costed. A Gemini model that is not traces as $0; local models always are. */
  priced: boolean;
  /** Input cost per 1M tokens in USD, or null if unknown / unpriced. */
  input_price?: number | null;
  /** Output cost per 1M tokens in USD, or null if unknown / unpriced. */
  output_price?: number | null;
  /** Field keys this model is the recommended pick for — starred in the list. */
  recommended_for: string[];
}

/** `GET /api/settings/config`. */
export interface EditableConfig {
  fields: ConfigField[];
  /** Asked of Google and of the local Ollama, not a list this repo keeps. */
  model_options: ModelOption[];
  ollama: { base_url: string; reachable: boolean; in_use: boolean };
}

/**
 * Whoever Authelia says is on the other end of the request.
 *
 * The app authenticates nobody — the proxy in front of it does, and passes the
 * identity down as headers. Locally there is no proxy, so nothing is signed in
 * and `authenticated` is false.
 */
export interface AccountInfo {
  authenticated: boolean;
  username: string;
  display_name: string;
  email: string;
  groups: string[];
  setup: AppConfig["progress"];
}

/**
 * One progress line from a streaming run — the `phase` event.
 *
 * The long runs answer with SSE rather than one blocking response, so these
 * arrive while the work happens instead of after it.
 */
export interface RunPhase {
  phase: string;
  message: string;
  /** Which artifact the line is about, when several are in flight at once. */
  track?: string;
}

/** The `result` event of `POST /api/jobs/search`. */
export interface SearchResult {
  jobs: Job[];
  saved: { saved: number; created: number };
  url_check: Record<string, number>;
  /** How fresh the results are, bucketed by age — see `services/recency.py`. */
  freshness: { week: number; month: number; quarter: number; older: number; undated: number };
  /** Postings the run threw away for having no link, keyed by why. */
  link_drops: Record<string, number>;
  /** Postings dropped because the candidate had already answered them —
   *  `dismissed` or `applied`. See `tools/persistence.partition_answered`. */
  answered_drops: Record<string, number>;
  strategy_notes: string;
  feedback_applied: { summary?: string } | null;
  audit: AuditSummary | null;
  run_id: number;
  target_results: number;
  /** What the candidate typed into the Jobs chat to steer this run, if they did. */
  focus: string;
}

/** The `result` event of `POST /api/jobs/import` — one pasted link. */
export interface ImportResult {
  job: Job;
  /** The saved row, so the page can scroll to and open the card it just added. */
  job_id: number;
  saved: { saved: number; created: number; updated: number };
  /** The link was already on the list; this run re-read and re-scored it. */
  already_saved: boolean;
  /** It had been dismissed, and pasting it brought it back to the deck. */
  restored: boolean;
  /** It was already an application, in the Tracker's trash, and pasting it took
   *  it back out — so it returns to the board with everything it had. */
  untrashed: boolean;
  /** The application the paste created, or the one the posting already had.
   *  Pasting a posting *is* the right swipe: the candidate went and found this
   *  one, so it goes straight to the Tracker rather than onto the deck to be
   *  asked about again. Null only when nothing was saved. */
  application_id: number | null;
  /** This import is what put it on the Tracker. False on a re-paste, where the
   *  application was already there. */
  tracked: boolean;
  url_check: Record<string, number>;
  /** Pasted text only: what became of a link the text did or did not carry.
   *  Empty when a link was found and proved — there is nothing to report then. */
  link_note?: string;
  audit: AuditSummary | null;
  run_id: number;
}

/** The `result` event of `POST /api/strategy/hr-expert`. */
export interface HrExpertResult {
  playbook: Record<string, any>;
  prompt: AgentPrompt;
  /** The advisory verdict — `{}` when the audit itself failed, so every field is optional. */
  audit: { overall?: number; reasoning?: string } | null;
  run_id: number;
}

/** The `result` event of `POST /api/applications/{id}/generate`. */
export interface GenerateResult {
  artifacts: Record<string, { id: number; kind: string; version: number }>;
  run_id: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  author: string;
  text: string;
  pending?: boolean;
}

export interface AgentPrompt {
  id: number;
  kind: string;
  version: number;
  title: string;
  content: string;
  structured: Record<string, any>;
  is_active: boolean;
  author: string;
  note: string;
  created_at: string;
  /** The Critic's verdict on this version, kept with it so the score is
   *  readable long after the run that produced it. `null` for hand edits,
   *  which are never re-scored. */
  audit: AuditSummary | null;
}

export interface AuditSummary {
  overall: number;
  threshold?: number;
  verdict: string;
  rubric?: string;
  fixes?: string[];
  scores?: { criteria?: { criterion: string; score: number; justification: string }[]; reasoning?: string };
  revision?: number;
}

export interface Job {
  id: number;
  title: string;
  company: string;
  location: string;
  remote: string;
  url: string;
  apply_url: string;
  source: string;
  description: string;
  /** The one-line form of `description` — the only prose a deck card shows. */
  summary: string;
  requirements: string[];
  nice_to_have: string[];
  contract_type: string;
  start_date: string;
  duration: string;
  compensation: string;
  language: string;
  /** What the posting says about its own date, in its own words. */
  posted_at: string;
  /** That date parsed to ISO, or "" when the posting never said. */
  posted_on: string;
  /** Age in days, recomputed server-side on every read. Null when undated. */
  posted_days_ago: number | null;
  deadline: string;
  fit_score: number;
  fit_rationale: string;
  strengths: string[];
  risks: string[];
  keywords: string[];
  confidence: string;
  url_status: "ok" | "blocked" | "index" | "dead" | "error" | "unchecked";
  url_http_status: number;
  dismissed: boolean;
  /** When the candidate swiped down on it. Set means "not now": the deck sends
   *  it behind everything undecided, longest-deferred first. */
  deferred_at: string | null;
  run_id: number | null;
  invocation_id: string;
  discovered_at: string;
  application_id: number | null;
}

/** `screening` was removed on 2026-08-28 — it described the employer's internal
 *  state, which the candidate can only guess at. Legacy rows were rewritten to
 *  `applied` by the backend's own retirement migration. `interview` was split
 *  into the four rounds on 2026-10-05, its rows moved to `hr_pre_call` the same
 *  way. Labels and the group are in `lib/statuses.ts`. */
export type ApplicationStatus =
  | "saved"
  | "preparing"
  | "applied"
  | "hr_pre_call"
  | "hr_interview"
  | "technical_test"
  | "manager_interview"
  | "offer"
  | "rejected"
  | "ghosted"
  | "withdrawn";

export type ArtifactKind =
  | "resume"
  | "cover_letter"
  | "follow_up"
  | "interview_prep"
  | "contacts";

export interface ArtifactSummary {
  id: number;
  kind: ArtifactKind;
  version: number;
  revisions: number;
  rendered_path: string;
  created_at: string;
}

export interface Artifact extends ArtifactSummary {
  content: Record<string, any>;
  run_id: number | null;
  invocation_id: string;
  audit: AuditSummary | null;
}

export type PackageLanguage = "en" | "fr";

export interface Application {
  id: number;
  job_posting_id: number;
  status: ApplicationStatus;
  /** A favourite, set by swiping the posting up. It sorts to the top of
   *  whatever Tracker column it is in, and survives every status change. */
  pinned: boolean;
  /** The language the résumé and cover letter are written in. */
  language: PackageLanguage;
  /** What the candidate knows about this employer that the posting does not
   *  say — typed into the dialog that opens when they press Generate, and kept
   *  so a regeneration months later still carries it. */
  personalisation: string;
  notes: string;
  next_action: string;
  next_action_date: string;
  applied_at: string | null;
  /** When it was moved to the Tracker's trash, or null while it is on the
   *  board. A timestamp rather than a flag: the trash reads newest-first, and
   *  the card says when you walked away. Nothing else about the application
   *  changes — the status, timeline, notes and artifacts are all still there. */
  trashed_at: string | null;
  created_at: string;
  updated_at: string;
  /** The whole posting, serialised exactly as the Jobs deck serialises it, so
   *  the application page can show what the card showed — the summary, the
   *  score and its rationale, the strengths, risks and requirements. */
  job: Job | null;
  artifacts: ArtifactSummary[];
  timeline?: { from: string; to: string; note: string; at: string }[];
  /** How quiet this application has been — detail endpoint only.
   *  `due` is what the Tracker raises unprompted; `sendable` is whether there
   *  is anything to follow up on at all (it has been sent). Both come from
   *  `services/follow_up.py`, so the browser never re-derives the rule. */
  silence?: {
    days: number;
    last_activity: string;
    after_days: number;
    waiting: boolean;
    sendable: boolean;
    due: boolean;
  };
}

/**
 * The chase email for an application that has gone quiet.
 *
 * Split the way a mail client is, because it is written to be sent unedited.
 * `to_hint` and `send_notes` are addressed to *the candidate* and must never be
 * rendered inside the message body — see `agents/schemas.py::FollowUpEmail`.
 */
export interface FollowUpEmail {
  recipient: string;
  to_hint: string;
  subject: string;
  greeting: string;
  paragraphs: string[];
  sign_off: string;
  signature: string;
  language: PackageLanguage;
  word_count: number;
  facts_used: string[];
  send_notes: string[];
}

export interface FollowUpDraft {
  id: number;
  version: number;
  revisions: number;
  run_id: number | null;
  created_at: string;
  content: FollowUpEmail;
}

/** One application that has been silent long enough to be worth chasing. */
export interface FollowUp {
  application_id: number;
  job_posting_id: number;
  status: ApplicationStatus;
  language: PackageLanguage;
  /** Whole days since the last event on this application. */
  days_silent: number;
  last_activity: string;
  job: { title: string; company: string; apply_url: string };
  /** Normally already written — the backend drafts it as the silence comes due. */
  draft: FollowUpDraft | null;
  /** The draft predates the last thing that happened, so it may be out of date. */
  draft_stale: boolean;
}

/**
 * The interview brief, written when an application first reaches an interview
 * round (`INTERVIEW_STATUSES`).
 *
 * Everything about the employer is backed by a URL in `sources` — the backend's
 * quality gate rejects a brief that describes a company it never looked up,
 * because the candidate is about to repeat it to someone who knows the answer.
 */
export interface InterviewPrep {
  company_brief: string;
  recent_developments: string[];
  role_brief: string;
  interview_process: string[];
  /** The answer to "tell me about yourself", for this role. */
  pitch: string;
  strengths_to_lead_with: string[];
  gaps: { gap: string; severity: string; honest_answer: string; preparation: string }[];
  likely_questions: {
    question: string;
    asked_by: string;
    why_asked: string;
    answer_outline: string[];
    evidence: string[];
  }[];
  questions_to_ask: string[];
  technical_topics: string[];
  logistics: string[];
  red_flags_to_probe: string[];
  sources: { title: string; url: string; takeaway: string }[];
  language: PackageLanguage;
}

/** The `result` event of `POST /api/applications/{id}/interview-prep`. */
export interface InterviewPrepResult {
  artifact: { id: number; kind: string; version: number };
  run_id: number;
}

/**
 * One person worth writing to about a posting.
 *
 * `linkedin_url` is present **only** when the backend fetched that profile and
 * the page came back titled with this person's name — see
 * `services/outreach.py`. When it could not prove it, the field is empty and
 * `search_url` finds them instead: a search cannot open the wrong person.
 */
export interface Contact {
  name: string;
  role: string;
  category: string;
  why: string;
  /** The message to send them — empty until **Write the message** is pressed.
   *  Written one person at a time by `POST /contacts/message` and stored back
   *  onto this shortlist, so it is still here tomorrow. */
  opening_line: string;
  /** Set by that run when what came back is longer than LinkedIn's 300. */
  opening_line_over_limit?: boolean;
  confidence: string;
  /** Proved to be this person's profile. Empty when it could not be proved. */
  linkedin_url: string;
  /** The page that named them, unless it turned out to be gone. */
  evidence_url: string;
  /** `verified` | `mismatch` | `unproved` | `gone` | "" (no URL was offered). */
  profile_status: string;
  evidence_status: string;
  /** A LinkedIn people search for their name at this employer. Always present. */
  search_url: string;
  /** The same search on the open web, for profiles LinkedIn hides. */
  web_url: string;
}

/** One search, built in Python from strings the app already knows. */
export interface ContactAngle {
  key: string;
  label: string;
  why: string;
  keywords: string;
  url: string;
}

/**
 * Who to contact about one posting, written the first time it is opened.
 *
 * Every link here is either constructed by the backend — a LinkedIn people
 * search, which cannot 404 — or was fetched and proved before it was saved.
 * Anyone the backend could not stand up appears in `dropped`, with why.
 */
export interface ContactPlan {
  people: Contact[];
  dropped: { name: string; role: string; reason: string }[];
  angles: ContactAngle[];
  /** Only present when the company slug resolved to a real LinkedIn page. */
  company: {
    slug?: string;
    url?: string;
    people_url?: string;
    recruiters_url?: string;
  };
  approach: string[];
  notes: string;
  sources: { title: string; url: string; takeaway: string }[];
  checked: {
    people_named: number;
    profiles_verified: number;
    dropped: number;
    searches: number;
  };
  /** Set when the research run did not finish and only the built searches are
   *  here. The searches are correct either way — they come from the posting and
   *  your own profile — but nobody was named, and the page must say so. */
  degraded?: string;
  language: PackageLanguage;
}

/** What `POST /api/applications/{id}/contacts/message` answers with.
 *
 * A plain POST, not a stream: one fast-model call writing two sentences is
 * seconds, not the minutes that make a proxy give up.
 */
export interface ContactMessageResult {
  opening_line: string;
  /** Measured in Python against LinkedIn's 300-character connection note. */
  over_limit: boolean;
  artifact_id: number;
  index: number;
  name: string;
  run_id: number;
}

/** The `result` event of `POST /api/applications/{id}/contacts`. */
export interface ContactsResult {
  artifact: { id: number; kind: string; version: number };
  run_id: number;
}

/** `GET /api/applications/follow-ups`. */
export interface FollowUpsResponse {
  /** The threshold in force, so the UI states the real number rather than "14". */
  after_days: number;
  follow_ups: FollowUp[];
}

/** The `result` event of `POST /api/applications/{id}/follow-up`. */
export interface FollowUpResult {
  artifact: { id: number; kind: string; version: number };
  run_id: number;
}

export interface PinnableItem {
  id: string;
  kind: string;
  label: string;
  anchor: string;
}

/** Everything the agents are allowed to say about the candidate. */
export interface MasterProfile {
  full_name: string;
  headline: string;
  email: string;
  phone: string;
  location: string;
  linkedin_url: string;
  github_url: string;
  portfolio_url: string;
  summary: string;
  experiences: any[];
  education: any[];
  projects: any[];
  skills: string[];
  languages: { language: string; level: string }[];
  certifications: string[];
  awards: string[];
  interests: string[];
  extraction_notes: string;
}

export interface AgentRun {
  id: number;
  kind: string;
  label: string;
  status: "running" | "succeeded" | "failed";
  session_id: string;
  invocation_id: string;
  input: Record<string, any>;
  output: Record<string, any>;
  error: string;
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
  llm_calls: number;
  tool_calls: number;
  cost_usd: number;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  event_count?: number;
}

export interface TraceEvent {
  id: number;
  seq: number;
  phase: string;
  agent_name: string;
  model: string;
  tool_name: string;
  summary: string;
  input_preview: string;
  output_preview: string;
  payload: Record<string, any>;
  prompt_tokens: number;
  output_tokens: number;
  total_tokens: number;
  latency_ms: number;
  error: string;
  invocation_id: string;
  prompt_version_id: number | null;
  created_at: string;
}

export interface AuditRecord extends AuditSummary {
  id: number;
  subject_kind: string;
  subject_id: string;
  blocking: boolean;
  run_id: number | null;
  created_at: string;
}

export interface TraceStats {
  runs: number;
  failed_runs: number;
  trace_events: number;
  total_tokens: number;
  total_cost_usd: number;
  llm_calls: number;
  tool_calls: number;
  by_kind: { kind: string; runs: number; cost_usd: number }[];
  audit_by_kind: { subject_kind: string; count: number; mean_overall: number }[];
}

export interface ProfileResponse {
  profile: Record<string, any>;
  has_profile: boolean;
  sources: ProfileSource[];
  /** The documents that actually get sent. Deliberately not part of
   *  `sources`: those are evidence merged into the profile, these are the
   *  résumé and the letter. */
  base_resumes: Record<PackageLanguage, BaseDocument | null>;
  base_cover_letters: Record<PackageLanguage, BaseDocument | null>;
}

/** Which of the two lists an item belongs to. */
export type CandidateListKind = "course" | "skill";

/**
 * One course the candidate took, or one skill they have, in both languages.
 *
 * They were two free-text boxes until 2026-09-08, one item per line, written
 * once in whichever language the candidate thought in — which left the résumé
 * Tailor translating course titles mid-run, inside a blank measured in
 * characters. Both spellings are required, and a run is shown only the one it
 * is writing in, so filling the coursework blank is a copy rather than a
 * translation. See `services/candidate_lists.py`.
 */
export interface CandidateListItem {
  id: number;
  kind: CandidateListKind;
  en: string;
  fr: string;
  position: number;
}

/** Both lists, as `/api/profile/lists` reports them. */
export interface CandidateLists {
  lists: Record<CandidateListKind, CandidateListItem[]>;
}

/**
 * One uploaded base document — a résumé or a cover letter — as `/api/profile`
 * and `/api/config` report it.
 *
 * The same shape for both since 2026-09-09, because they are the same thing:
 * the candidate's own .docx, with blanks an applying run fills and nothing else
 * it may touch. Only the words around the card differ.
 */
export interface BaseDocument {
  id: number;
  label: string;
  status: string;
  error: string;
  /** False when the row survives but the file does not — the app treats that
   *  as "not uploaded", because the row is not the document. */
  on_disk: boolean;
  created_at: string;
  /** How many blanks the document leaves for the tailoring to fill. */
  placeholders: number;
  /** One sentence about how full the page is, estimated by
   *  `services/page_fit.py` — a percentage rather than a verdict, because it
   *  is an estimate and the candidate is holding the file. */
  page: string;
  /** Characters of room left on the page once the blanks are filled. */
  room: number;
  /** True when there is not enough room to fill the blanks at all, which is
   *  what makes `POST …/generate` answer 409 for that language. */
  crowded: boolean;
  /** Set when the document reads as the other language — a warning to the
   *  candidate, never a gate on a run. */
  language_warning: string;
}

export interface ProfileSource {
  id: number;
  kind: string;
  label: string;
  status: string;
  error: string;
  source_url: string;
  /** The stored document's filename, or "" when it is no longer on disk. */
  file_name: string;
  /** Whether the browser can render it in a tab, rather than download it. */
  can_preview: boolean;
  created_at: string;
}

