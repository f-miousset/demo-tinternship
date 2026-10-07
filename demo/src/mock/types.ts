/**
 * The shapes the mock stores, typed against the real app's own contracts.
 *
 * Everything public-facing is the app's type (`app/frontend/src/lib/types.ts`),
 * so a resync that changes a response shape fails `tsc` here instead of
 * rendering a page that throws (documentation/syncing-from-v2.md).
 */
import type {
  AgentPrompt,
  AgentRun,
  AppConfig,
  Application,
  Artifact,
  AuditRecord,
  AuditSummary,
  CandidateListItem,
  CandidateListKind,
  ChatMessage,
  EditableConfig,
  FollowUpEmail,
  Job,
  ProfileResponse,
  TraceEvent,
} from "../../../app/frontend/src/lib/types";

export type { AgentPrompt, AgentRun, Application, Artifact, AuditRecord, Job, TraceEvent };

/** A posting as stored: the serialised job plus the world's name for it. */
export type StoredJob = Job & { key: string; purged?: boolean };

/** A posting not yet on the deck — a canned search or paste reveals it. */
export type HiddenJob = StoredJob & { pool: string };

export interface StoredApplication extends Omit<Application, "job" | "artifacts" | "timeline" | "silence"> {
  job_key: string;
  events: { from: string; to: string; note: string; at: string }[];
}

/** An artifact row, with what the API derives from it kept alongside. */
export interface StoredArtifact extends Artifact {
  application_id: number;
  /** The Copy-text answer for a letter — computed by the real backend at seed time. */
  text?: string;
}

export interface StoredRun {
  run: AgentRun;
  events: TraceEvent[];
  audits: AuditRecord[];
}

export interface SearchHistoryItem {
  id: string;
  text: string;
  created_at: string;
  updated_at: string;
  timestamp: number;
}

/** What `scripts/build_seed.py` writes to `demo-data/seed.json`. */
export interface Seed {
  epoch: string;
  version: string;
  config: AppConfig;
  account: Record<string, unknown>;
  profile: ProfileResponse;
  lists: { lists: Record<CandidateListKind, CandidateListItem[]> };
  prompts: AgentPrompt[];
  settings_data: { summary: Record<string, number>; scopes: { key: string; label: string; description: string }[]; confirm_phrase: string };
  settings_config: EditableConfig;
  jobs: StoredJob[];
  hidden_jobs: HiddenJob[];
  applications: (Application & { job_key: string; artifacts_full: (Artifact & { text?: string })[] })[];
  runs: StoredRun[];
  audits: AuditRecord[];
  interview: ChatMessage[];
  searches: { key: string; prompt: string; notes: string }[];
  link_import: string;
  text_import: string;
  personalisation: Record<"en" | "fr", string>;
  messages: {
    /** In the order the pipeline runs them — pairs, because the seed's keys are sorted. */
    investigator: [string, string][];
    link_intake: [string, string][];
    hr_expert: [string, string][];
    stages: Record<string, string>;
    tracks: Record<string, string>;
    follow_up: Record<string, string>;
    interview_prep: Record<string, string>;
    contacts: Record<string, string>;
  };
}

/** One canned document, as the real renderer produced it. */
export interface CannedDocument {
  id: number;
  content: Record<string, any>;
  text: string;
  audit: AuditSummary;
}

/** Everything a demo run can "write" for one posting (`demo-data/canned.json`). */
export interface Canned {
  documents: Record<string, CannedDocument>;
  interview_prep: Record<string, any>;
  contacts: Record<string, any>;
  contact_messages: Record<string, string>;
  follow_up: FollowUpEmail;
}

/** The whole of one visitor's demo, as kept in their browser. */
export interface State {
  version: string;
  nextId: number;
  jobs: StoredJob[];
  hidden: HiddenJob[];
  applications: StoredApplication[];
  artifacts: StoredArtifact[];
  profile: ProfileResponse;
  lists: Record<CandidateListKind, CandidateListItem[]>;
  prompts: AgentPrompt[];
  runs: StoredRun[];
  audits: AuditRecord[];
  history: SearchHistoryItem[];
  interview: ChatMessage[];
  settings: EditableConfig;
  /** How many canned searches have been revealed, by key. */
  searched: string[];
}
