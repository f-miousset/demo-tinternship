/**
 * The trace a simulated run leaves behind.
 *
 * Every demo run is recorded on the Traces page like a real one — agent starts,
 * model calls, tool calls, the Critic's verdict — so the audit trail the app is
 * built around can be followed from a result back to how it was produced.
 * The agents and tools per kind are the real pipelines' (agents.md); the token
 * counts are invented, and the cost is computed from the Settings page's own
 * price list, which is the backend's fallback table.
 *
 * Mirrors `scripts/build_seed.py::add_run`, which wrote the seeded traces.
 */
import type { AuditRecord, AuditSummary } from "../../../app/frontend/src/lib/types";
import { newId } from "./store";
import type { State, StoredRun, TraceEvent } from "./types";

const AGENTS: Record<string, [string, "primary" | "fast" | "grounded", string[]][]> = {
  investigator: [
    ["query_planner", "primary", []],
    ["scout", "grounded", ["google_search", "search_job_board"]],
    ["normaliser", "fast", []],
    ["matcher", "primary", []],
  ],
  link_intake: [
    ["reader", "fast", ["fetch_page"]],
    ["matcher", "primary", []],
  ],
  text_intake: [
    ["reader", "fast", []],
    ["matcher", "primary", []],
  ],
  applying: [
    ["resume_agent", "primary", []],
    ["address_scout", "grounded", ["google_search"]],
    ["cover_letter_agent", "primary", []],
    ["cover_letter_humaniser", "fast", []],
  ],
  interview_prep: [
    ["interview_researcher", "grounded", ["google_search"]],
    ["interview_coach", "primary", []],
  ],
  contacts: [
    ["contact_scout", "grounded", ["google_search"]],
    ["contact_strategist", "primary", []],
  ],
  contact_message: [["message_writer", "fast", []]],
  follow_up: [["follow_up_agent", "primary", []]],
  interrogator: [["interrogator", "primary", []]],
  hr_expert: [
    ["hr_researcher", "grounded", ["google_search"]],
    ["playbook_writer", "primary", []],
  ],
  profile_parse: [["profile_extractor", "fast", []]],
};

/** A deterministic number in [0, 1) from a label — the same run reads the same. */
function stable(...parts: (string | number)[]): number {
  let hash = 2166136261;
  for (const char of parts.join("|")) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 0x100000000;
}

function modelFor(state: State, tier: "primary" | "fast" | "grounded"): string {
  const key = { primary: "model_primary", fast: "model_fast", grounded: "model_grounded" }[tier];
  return String(state.settings.fields.find((field) => field.key === key)?.value ?? "gemini-3.6-flash");
}

function price(state: State, model: string): [number, number] {
  const option = state.settings.model_options.find((item) => item.id === model);
  return [option?.input_price ?? 0, option?.output_price ?? 0];
}

/** Record one finished run and return its id. */
export function recordRun(
  state: State,
  kind: string,
  label: string,
  input: Record<string, unknown>,
  output: Record<string, unknown>,
): number {
  const runId = newId(state);
  const started = Date.now() - 1000 * (8 + 10 * stable(label));
  let clock = started;
  const events: TraceEvent[] = [];
  let promptTokens = 0;
  let outputTokens = 0;
  let llmCalls = 0;
  let toolCalls = 0;
  let cost = 0;
  const invocation = `e-demo-${runId}`;

  const emit = (fields: Partial<TraceEvent>) => {
    clock += (fields.latency_ms ?? 0) + 40;
    events.push({
      id: newId(state),
      seq: events.length,
      phase: "",
      agent_name: "",
      model: "",
      tool_name: "",
      summary: "",
      input_preview: "",
      output_preview: "",
      payload: { demo: "Simulated in the browser — no model was called." },
      prompt_tokens: 0,
      output_tokens: 0,
      total_tokens: 0,
      latency_ms: 0,
      error: "",
      invocation_id: invocation,
      prompt_version_id: null,
      created_at: new Date(clock).toISOString(),
      ...fields,
    });
  };

  emit({ phase: "run_start", agent_name: kind, summary: `Run started: ${label}`, input_preview: JSON.stringify(input).slice(0, 400) });
  for (const [name, tier, tools] of AGENTS[kind] ?? [[kind, "primary", []]]) {
    const model = modelFor(state, tier);
    emit({ phase: "agent_start", agent_name: name, model, summary: `${name} started` });
    for (let call = 0; call < (tools.length ? 2 : 1); call += 1) {
      const p = Math.round(2400 + 6000 * stable(label, name, call));
      const o = Math.round(300 + 1500 * stable(label, name, call, "o"));
      const latency = Math.round(1800 + 5200 * stable(label, name, call, "l"));
      emit({ phase: "model_request", agent_name: name, model, summary: `${name} → ${model}`, input_preview: "(instruction, context blocks, conversation so far)" });
      emit({
        phase: "model_response",
        agent_name: name,
        model,
        summary: `${model}: ${o} output tokens`,
        prompt_tokens: p,
        output_tokens: o,
        total_tokens: p + o,
        latency_ms: latency,
        output_preview: "(structured output, validated against the agent's schema)",
      });
      const [input_price, output_price] = price(state, model);
      cost += (p / 1e6) * input_price + (o / 1e6) * output_price;
      promptTokens += p;
      outputTokens += o;
      llmCalls += 1;
      if (call === 0) {
        for (const tool of tools) {
          emit({ phase: "tool_start", agent_name: name, tool_name: tool, summary: `${tool} called`, input_preview: JSON.stringify({ query: label }) });
          emit({ phase: "tool_end", agent_name: name, tool_name: tool, summary: `${tool} returned`, latency_ms: Math.round(600 + 2400 * stable(label, tool)), output_preview: "(results summarised for the next agent)" });
          toolCalls += 1;
        }
      }
    }
    emit({ phase: "agent_end", agent_name: name, summary: `${name} finished` });
  }
  emit({ phase: "run_end", agent_name: kind, summary: "Run finished", output_preview: JSON.stringify(output).slice(0, 400) });

  const run: StoredRun = {
    run: {
      id: runId,
      kind,
      label,
      status: "succeeded",
      session_id: `demo-${kind}`,
      invocation_id: invocation,
      input,
      output,
      error: "",
      prompt_tokens: promptTokens,
      output_tokens: outputTokens,
      total_tokens: promptTokens + outputTokens,
      llm_calls: llmCalls,
      tool_calls: toolCalls,
      cost_usd: Math.round(cost * 1e5) / 1e5,
      started_at: new Date(started).toISOString(),
      finished_at: new Date(clock).toISOString(),
      duration_ms: clock - started,
      event_count: events.length,
    },
    events,
    audits: [],
  };
  state.runs.unshift(run);
  return runId;
}

/** Record the Critic's verdict on what a run produced, and return it as the API shows it. */
export function recordAudit(
  state: State,
  runId: number | null,
  subjectKind: string,
  subjectId: string,
  verdict: AuditSummary,
): AuditSummary {
  const record: AuditRecord = {
    ...verdict,
    id: newId(state),
    subject_kind: subjectKind,
    subject_id: subjectId,
    blocking: subjectKind === "resume" || subjectKind === "cover_letter",
    run_id: runId,
    created_at: new Date().toISOString(),
  };
  state.audits.unshift(record);
  state.runs.find((run) => run.run.id === runId)?.audits.push(record);
  const { id: _id, subject_kind: _kind, subject_id: _subject, blocking: _blocking, run_id: _run, created_at: _at, ...summary } = record;
  return summary;
}

/** A verdict borrowed from the newest seeded one of the same kind — the rubric's real criteria. */
export function borrowVerdict(state: State, subjectKind: string): AuditSummary {
  const found = state.audits.find((audit) => audit.subject_kind === subjectKind);
  if (!found) return { overall: 8.4, threshold: 7.5, verdict: "pass", fixes: [], revision: 0 };
  const { id: _id, subject_kind: _kind, subject_id: _subject, blocking: _blocking, run_id: _run, created_at: _at, ...summary } = found;
  return summary;
}
