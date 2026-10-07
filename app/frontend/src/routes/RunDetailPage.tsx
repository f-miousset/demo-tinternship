import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Badge, Card, EmptyState, ScoreBadge, SectionTitle, Spinner } from "../components/ui";
import { api } from "../lib/api";
import type { AgentRun, AuditRecord, TraceEvent } from "../lib/types";

const PHASE_TONE: Record<string, "neutral" | "info" | "good" | "warn" | "bad"> = {
  run_start: "info",
  run_end: "info",
  agent_start: "neutral",
  agent_end: "neutral",
  model_request: "info",
  model_response: "good",
  tool_start: "warn",
  tool_end: "warn",
  user_message: "neutral",
  event: "neutral",
  error: "bad",
};

export function RunDetailPage() {
  const { runId } = useParams();
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState<string>("all");

  const { data, isLoading } = useQuery({
    queryKey: ["traces", "run", runId],
    queryFn: () =>
      api.get<{ run: AgentRun; events: TraceEvent[]; audits: AuditRecord[] }>(
        `/api/traces/runs/${runId}`,
      ),
    enabled: Boolean(runId),
  });

  if (isLoading) return <Spinner label="Loading trace…" />;
  if (!data) return <EmptyState title="Run not found" />;

  const { run, events, audits } = data;
  const phases = Array.from(new Set(events.map((event) => event.phase)));
  const visible = filter === "all" ? events : events.filter((event) => event.phase === filter);

  function toggle(id: number) {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="space-y-5">
      <SectionTitle
        title={`${run.kind} · ${run.label}`}
        subtitle={`Run #${run.id} · invocation ${run.invocation_id || "—"} · session ${run.session_id || "—"}`}
        action={
          <Link to="/traces" className="text-sm text-accent-600 underline">
            ← all runs
          </Link>
        }
      />

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 lg:grid-cols-6">
        {[
          ["Status", run.status],
          ["Decisions", events.length],
          ["LLM calls", run.llm_calls],
          ["Tool calls", run.tool_calls],
          ["Tokens", run.total_tokens.toLocaleString()],
          ["Est. cost", `$${run.cost_usd.toFixed(4)}`],
        ].map(([label, value]) => (
          <Card key={label as string}>
            <p className="text-xs uppercase tracking-wide text-ink-500">{label as string}</p>
            <p className="mt-1 text-lg font-semibold tabular-nums">{value as string}</p>
          </Card>
        ))}
      </div>

      {run.error && (
        <Card className="border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/30">
          <p className="text-sm text-red-800 dark:text-red-300">{run.error}</p>
        </Card>
      )}

      {audits.length > 0 && (
        <Card>
          <h3 className="mb-2 text-sm font-semibold">Audits in this run</h3>
          <div className="flex flex-wrap gap-2">
            {audits.map((audit) => (
              <div
                key={audit.id}
                className="flex items-center gap-2 rounded-lg border border-ink-200 px-2.5 py-1.5 dark:border-ink-800"
              >
                <ScoreBadge score={audit.overall} threshold={audit.threshold || undefined} />
                <span className="text-sm">{audit.subject_kind.replace("_", " ")}</span>
                <Badge tone={audit.verdict === "pass" ? "good" : "warn"}>{audit.verdict}</Badge>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="flex flex-wrap gap-1">
        {["all", ...phases].map((phase) => (
          <button
            key={phase}
            onClick={() => setFilter(phase)}
            className={`min-h-9 rounded-lg px-2.5 text-xs font-medium transition sm:min-h-0 sm:py-1 ${
              filter === phase
                ? "bg-ink-900 text-white dark:bg-ink-100 dark:text-ink-900"
                : "text-ink-600 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-ink-800"
            }`}
          >
            {phase}
            {phase !== "all" && (
              <span className="ml-1.5 opacity-60">
                {events.filter((event) => event.phase === phase).length}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="space-y-1.5">
        {visible.map((event) => {
          const expanded = open.has(event.id);
          return (
            <div
              key={event.id}
              className="rounded-lg border border-ink-200 bg-white dark:border-ink-800 dark:bg-ink-900"
            >
              <button
                onClick={() => toggle(event.id)}
                className="flex w-full flex-wrap items-center gap-x-2.5 gap-y-1 px-3 py-2 text-left text-sm"
              >
                <span className="w-8 shrink-0 text-xs tabular-nums text-ink-400">{event.seq}</span>
                <Badge tone={PHASE_TONE[event.phase] ?? "neutral"}>{event.phase}</Badge>
                {event.agent_name && <span className="font-medium">{event.agent_name}</span>}
                <span className="w-full min-w-0 truncate text-ink-500 sm:w-auto sm:flex-1">
                  {event.summary}
                </span>
                {event.total_tokens > 0 && (
                  <span className="text-xs tabular-nums text-ink-400">
                    {event.prompt_tokens}→{event.output_tokens}
                  </span>
                )}
                {event.latency_ms > 0 && (
                  <span className="text-xs tabular-nums text-ink-400">{event.latency_ms}ms</span>
                )}
                <span className="text-xs text-ink-300">{expanded ? "▾" : "▸"}</span>
              </button>

              {expanded && (
                <div className="space-y-3 border-t border-ink-200 px-3 py-3 dark:border-ink-800">
                  {event.error && (
                    <pre className="rounded bg-red-50 p-2 text-xs text-red-800 dark:bg-red-950/30 dark:text-red-300">
                      {event.error}
                    </pre>
                  )}
                  {event.input_preview && (
                    <Section label="Input — exactly what the model or tool received">
                      {event.input_preview}
                    </Section>
                  )}
                  {event.output_preview && (
                    <Section label="Output">{event.output_preview}</Section>
                  )}
                  {Object.keys(event.payload ?? {}).length > 0 && (
                    <Section label="Metadata">
                      {JSON.stringify(event.payload, null, 2)}
                    </Section>
                  )}
                  <p className="text-xs text-ink-400">
                    {new Date(event.created_at).toLocaleString()}
                    {event.model && ` · ${event.model}`}
                    {event.prompt_version_id && ` · prompt v-id ${event.prompt_version_id}`}
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: string }) {
  return (
    <div>
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-500">{label}</h4>
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-ink-100 p-2.5 text-xs leading-relaxed dark:bg-ink-950">
        {children}
      </pre>
    </div>
  );
}
