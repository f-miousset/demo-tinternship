/**
 * The backend's read side, in the browser.
 *
 * Each function here is the counterpart of one in `app/backend` and says which.
 * They are deliberately small: the seed was serialised by the real backend, so
 * what is left to compute is only what depends on *today* (ages, silences) or
 * on what the visitor has changed since (which posting has an application).
 */
import type {
  AppConfig,
  Application,
  ArtifactSummary,
  FollowUp,
  FollowUpEmail,
  TraceStats,
} from "../../../app/frontend/src/lib/types";
import type { State, StoredApplication, StoredJob } from "./types";

const DAY = 86_400_000;

export function nowIso(): string {
  return new Date().toISOString();
}

/** `services/recency.py::days_since` — whole days, floored. */
export function daysSince(iso: string | null | undefined, now = Date.now()): number | null {
  if (!iso) return null;
  const at = Date.parse(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(at) ? null : Math.max(0, Math.floor((now - at) / DAY));
}

/** `api/jobs.py::serialise_job` — the age is recomputed on every read. */
export function jobOut(state: State, job: StoredJob) {
  const { key: _key, purged: _purged, ...rest } = job as StoredJob & { pool?: string };
  delete (rest as { pool?: string }).pool;
  const application = state.applications.find((item) => item.job_posting_id === job.id);
  return { ...rest, posted_days_ago: daysSince(job.posted_on), application_id: application?.id ?? null };
}

function setting(state: State, key: string, fallback: number): number {
  const field = state.settings.fields.find((item) => item.key === key);
  return field ? Number(field.value) : fallback;
}

/** `services/recency.py::score` — the match, discounted by age. */
export function rankScore(state: State, fit: number, age: number | null): number {
  const FLOOR = 0.3;
  const UNKNOWN_AGE_DAYS = 20;
  const halfLife = Math.max(1, setting(state, "posting_half_life_days", 21));
  const freshness = FLOOR + (1 - FLOOR) * 0.5 ** (Math.max(0, age ?? UNKNOWN_AGE_DAYS) / halfLife);
  return Math.round(fit * freshness * 10_000) / 10_000;
}

/** `api/jobs.py::list_jobs` — the deck's order, the discard pile, or everything. */
export function listJobs(state: State, view: string) {
  const tracked = new Set(state.applications.map((application) => application.job_posting_id));
  let rows = state.jobs.filter((job) => !job.purged);
  if (view === "deck") rows = rows.filter((job) => !job.dismissed && !tracked.has(job.id));
  else if (view === "discarded") rows = rows.filter((job) => job.dismissed);
  const serialised = rows.map((job) => jobOut(state, job));
  const key = (job: (typeof serialised)[number]) => rankScore(state, job.fit_score, job.posted_days_ago);
  const waiting = serialised.filter((job) => !job.deferred_at).sort((a, b) => key(b) - key(a) || b.fit_score - a.fit_score);
  const deferred = serialised
    .filter((job) => job.deferred_at)
    .sort((a, b) => Date.parse(a.deferred_at ?? "") - Date.parse(b.deferred_at ?? ""));
  return { jobs: [...waiting, ...deferred], sources: ["Google Search (grounded)"] };
}

/** `api/applications.py::_latest_artifacts` — the newest version of each kind. */
function latestArtifacts(state: State, applicationId: number): ArtifactSummary[] {
  const seen = new Set<string>();
  return state.artifacts
    .filter((artifact) => artifact.application_id === applicationId)
    .sort((a, b) => b.version - a.version)
    .filter((artifact) => (seen.has(artifact.kind) ? false : (seen.add(artifact.kind), true)))
    .map(({ id, kind, version, revisions, rendered_path, created_at }) => ({
      id,
      kind,
      version,
      revisions,
      rendered_path,
      created_at,
    }));
}

const WAITING = ["applied", "hr_pre_call", "hr_interview", "technical_test", "manager_interview"];
const UNSENT = ["saved", "preparing"];

/** `services/follow_up.py::silence_of`. */
export function silenceOf(state: State, application: StoredApplication) {
  const last = application.events.at(-1)?.at ?? application.applied_at ?? application.created_at;
  const afterDays = Math.max(1, setting(state, "follow_up_after_days", 14));
  const days = daysSince(last) ?? 0;
  const waiting = WAITING.includes(application.status);
  return {
    days,
    last_activity: last,
    after_days: afterDays,
    waiting,
    sendable: !UNSENT.includes(application.status),
    due: waiting && days >= afterDays,
  };
}

/** `api/applications.py::_serialise_application`, plus the detail endpoint's extras. */
export function applicationOut(state: State, application: StoredApplication, detail = false): Application {
  const { job_key: _key, events, ...row } = application;
  const job = state.jobs.find((item) => item.id === application.job_posting_id);
  const out: Application = {
    ...row,
    job: job ? jobOut(state, job) : null,
    artifacts: latestArtifacts(state, application.id),
  };
  if (detail) {
    out.timeline = events;
    out.silence = silenceOf(state, application);
  }
  return out;
}

/** `api/applications.py::list_applications`. */
export function listApplications(state: State, view: string) {
  let rows = state.applications;
  if (view === "board") rows = rows.filter((application) => !application.trashed_at);
  else if (view === "trashed") rows = rows.filter((application) => application.trashed_at);
  const order =
    view === "trashed"
      ? (a: StoredApplication, b: StoredApplication) => Date.parse(b.trashed_at ?? "") - Date.parse(a.trashed_at ?? "")
      : (a: StoredApplication, b: StoredApplication) => Date.parse(b.updated_at) - Date.parse(a.updated_at);
  return { applications: [...rows].sort(order).map((application) => applicationOut(state, application)) };
}

/** `services/follow_up.py::due` — silent long enough, most silent first. */
export function followUps(state: State): { after_days: number; follow_ups: FollowUp[] } {
  const afterDays = Math.max(1, setting(state, "follow_up_after_days", 14));
  const found: FollowUp[] = [];
  for (const application of state.applications) {
    if (application.trashed_at) continue;
    const silence = silenceOf(state, application);
    if (!silence.due) continue;
    const job = state.jobs.find((item) => item.id === application.job_posting_id);
    const draft = state.artifacts
      .filter((artifact) => artifact.application_id === application.id && artifact.kind === "follow_up")
      .sort((a, b) => b.version - a.version)[0];
    found.push({
      application_id: application.id,
      job_posting_id: application.job_posting_id,
      status: application.status,
      language: application.language,
      days_silent: silence.days,
      last_activity: silence.last_activity,
      job: { title: job?.title ?? "", company: job?.company ?? "", apply_url: job?.apply_url ?? "" },
      draft: draft
        ? {
            id: draft.id,
            version: draft.version,
            revisions: draft.revisions,
            run_id: draft.run_id,
            created_at: draft.created_at,
            content: draft.content as FollowUpEmail,
          }
        : null,
      draft_stale: draft ? Date.parse(draft.created_at) < Date.parse(silence.last_activity) : false,
    });
  }
  found.sort((a, b) => b.days_silent - a.days_silent);
  return { after_days: afterDays, follow_ups: found };
}

/** `services/onboarding.py::setup_state`. */
export function progress(state: State): AppConfig["progress"] {
  const both = (documents: Record<string, unknown>) => ["en", "fr"].every((language) => Boolean(documents[language]));
  const active = (kind: string) => state.prompts.some((prompt) => prompt.kind === kind && prompt.is_active);
  const flags = {
    has_base_resumes: both(state.profile.base_resumes),
    has_base_letters: both(state.profile.base_cover_letters),
    has_profile: Boolean(state.profile.profile?.full_name),
    has_lists: state.lists.course.length > 0 && state.lists.skill.length > 0,
    has_interview: state.interview.some((message) => message.role === "assistant"),
    has_brief: active("search_brief"),
    has_playbook: active("playbook"),
  };
  const { has_interview: _interview, ...required } = flags;
  return { ...flags, complete: Object.values(required).every(Boolean) };
}

/** `api/system.py::config` — what the layout and the setup gate read. */
export function config(state: State, seedConfig: AppConfig): AppConfig {
  const model = (key: string, fallback: string) => String(state.settings.fields.find((f) => f.key === key)?.value ?? fallback);
  return {
    ...seedConfig,
    models: {
      primary: model("model_primary", seedConfig.models.primary),
      fast: model("model_fast", seedConfig.models.fast),
      grounded: model("model_grounded", seedConfig.models.grounded),
    },
    base_resumes: state.profile.base_resumes,
    base_cover_letters: state.profile.base_cover_letters,
    audit: {
      threshold: setting(state, "audit_pass_threshold", seedConfig.audit.threshold),
      max_revisions: setting(state, "audit_max_revisions", seedConfig.audit.max_revisions),
    },
    progress: progress(state),
    // The seed's one warning is about a job-board key — true of a real install
    // without one, meaningless in a demo that searches nothing.
    warnings: [],
  };
}

/** `api/traces.py::stats`. */
export function traceStats(state: State): TraceStats {
  const byKind = new Map<string, { runs: number; cost_usd: number }>();
  for (const { run } of state.runs) {
    const entry = byKind.get(run.kind) ?? { runs: 0, cost_usd: 0 };
    entry.runs += 1;
    entry.cost_usd += run.cost_usd;
    byKind.set(run.kind, entry);
  }
  const audits = new Map<string, { count: number; total: number }>();
  for (const audit of state.audits) {
    const entry = audits.get(audit.subject_kind) ?? { count: 0, total: 0 };
    entry.count += 1;
    entry.total += audit.overall;
    audits.set(audit.subject_kind, entry);
  }
  const sum = (pick: (run: State["runs"][number]["run"]) => number) =>
    state.runs.reduce((total, { run }) => total + pick(run), 0);
  return {
    runs: state.runs.length,
    failed_runs: state.runs.filter(({ run }) => run.status === "failed").length,
    trace_events: state.runs.reduce((total, run) => total + run.events.length, 0),
    total_tokens: sum((run) => run.total_tokens),
    total_cost_usd: Math.round(sum((run) => run.cost_usd) * 1e6) / 1e6,
    llm_calls: sum((run) => run.llm_calls),
    tool_calls: sum((run) => run.tool_calls),
    by_kind: [...byKind].map(([kind, entry]) => ({ kind, runs: entry.runs, cost_usd: Math.round(entry.cost_usd * 1e6) / 1e6 })),
    audit_by_kind: [...audits].map(([subject_kind, entry]) => ({
      subject_kind,
      count: entry.count,
      mean_overall: Math.round((entry.total / entry.count) * 100) / 100,
    })),
  };
}
