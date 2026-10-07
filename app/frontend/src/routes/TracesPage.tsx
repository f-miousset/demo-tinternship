import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Badge, Card, EmptyState, ScoreBadge, SectionTitle, Spinner } from "../components/ui";
import { api } from "../lib/api";
import type { AgentRun, AuditRecord, TraceStats } from "../lib/types";

export function TracesPage() {
  const { data: stats } = useQuery({
    queryKey: ["traces", "stats"],
    queryFn: () => api.get<TraceStats>("/api/traces/stats"),
    refetchInterval: 10_000,
  });
  const { data: runData, isLoading } = useQuery({
    queryKey: ["traces", "runs"],
    queryFn: () => api.get<{ runs: AgentRun[] }>("/api/traces/runs"),
    refetchInterval: 10_000,
  });
  const { data: auditData } = useQuery({
    queryKey: ["traces", "audits"],
    queryFn: () => api.get<{ audits: AuditRecord[] }>("/api/traces/audits?limit=40"),
  });

  const runs = runData?.runs ?? [];

  return (
    <div className="space-y-5">
      <SectionTitle
        title="Traces & audit"
        subtitle="Every agent, model and tool call is logged with its inputs, outputs, tokens and latency. Every generated artifact is scored against a rubric."
      />

      {stats && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 lg:grid-cols-6">
          {[
            ["Runs", stats.runs],
            ["Failed", stats.failed_runs],
            ["Logged decisions", stats.trace_events],
            ["LLM calls", stats.llm_calls],
            ["Tokens", stats.total_tokens.toLocaleString()],
            ["Est. cost", `$${stats.total_cost_usd.toFixed(3)}`],
          ].map(([label, value]) => (
            <Card key={label as string}>
              <p className="text-xs uppercase tracking-wide text-ink-500">{label as string}</p>
              <p className="mt-1 text-xl font-semibold tabular-nums">{value as string}</p>
            </Card>
          ))}
        </div>
      )}

      {stats && stats.audit_by_kind.length > 0 && (
        <Card>
          <h3 className="mb-3 text-sm font-semibold">Mean quality score by artifact</h3>
          <div className="space-y-2">
            {stats.audit_by_kind.map((entry) => (
              <div key={entry.subject_kind} className="flex items-center gap-2 text-sm sm:gap-3">
                <span className="w-24 shrink-0 truncate text-xs text-ink-500 sm:w-32 sm:text-sm">
                  {entry.subject_kind.replace("_", " ")}
                </span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-200 dark:bg-ink-800">
                  <div
                    className={`h-full rounded-full ${
                      entry.mean_overall >= 7.5
                        ? "bg-emerald-500"
                        : entry.mean_overall >= 5.5
                          ? "bg-amber-500"
                          : "bg-red-500"
                    }`}
                    style={{ width: `${Math.max(2, Math.min(100, entry.mean_overall * 10))}%` }}
                  />
                </div>
                <span className="w-9 text-right tabular-nums">{entry.mean_overall.toFixed(1)}</span>
                <span className="w-10 text-right text-xs text-ink-400 sm:w-16">n={entry.count}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <h3 className="mb-3 text-sm font-semibold">Runs</h3>
        {isLoading && <Spinner label="Loading runs…" />}
        {!isLoading && runs.length === 0 && (
          <EmptyState title="No runs yet" hint="Every agent execution will appear here." />
        )}
        <div className="space-y-1.5">
          {runs.map((run) => (
            // What the run was stays on the first line and the numbers follow
            // it; on a laptop there is room for both on one.
            <Link
              key={run.id}
              to={`/traces/${run.id}`}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-ink-200 px-3 py-2 text-sm transition hover:border-accent-400 dark:border-ink-800"
            >
              <span className="flex w-full min-w-0 items-center gap-2 sm:w-auto sm:flex-1">
                <Badge
                  tone={
                    run.status === "succeeded" ? "good" : run.status === "failed" ? "bad" : "warn"
                  }
                >
                  {run.status}
                </Badge>
                <span className="shrink-0 font-medium">{run.kind}</span>
                <span className="min-w-0 flex-1 truncate text-ink-500">{run.label}</span>
              </span>
              <span className="text-xs tabular-nums text-ink-400">
                {run.event_count ?? 0} events
              </span>
              <span className="text-xs tabular-nums text-ink-400">
                {run.total_tokens.toLocaleString()} tok
              </span>
              <span className="text-xs tabular-nums text-ink-400">
                ${run.cost_usd.toFixed(4)}
              </span>
              <span className="text-xs tabular-nums text-ink-400">
                {run.duration_ms ? `${(run.duration_ms / 1000).toFixed(1)}s` : "—"}
              </span>
              <span className="text-xs text-ink-400">
                {new Date(run.started_at).toLocaleString()}
              </span>
            </Link>
          ))}
        </div>
      </Card>

      {auditData && auditData.audits.length > 0 && (
        <Card>
          <h3 className="mb-3 text-sm font-semibold">Recent audits</h3>
          <div className="space-y-1.5">
            {auditData.audits.map((audit) => (
              <div
                key={audit.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-ink-200 px-3 py-2 text-sm dark:border-ink-800"
              >
                <ScoreBadge score={audit.overall} threshold={audit.threshold || undefined} />
                <Badge
                  tone={audit.verdict === "pass" ? "good" : audit.verdict === "fail" ? "bad" : "warn"}
                >
                  {audit.verdict}
                </Badge>
                <span className="font-medium">{audit.subject_kind.replace("_", " ")}</span>
                <span className="text-xs text-ink-400">{audit.rubric}</span>
                {audit.blocking ? (
                  <Badge tone="info" title="A failing score here blocks the artifact until it is revised">
                    gated
                  </Badge>
                ) : (
                  <Badge title="Scored and logged, but never blocks">advisory</Badge>
                )}
                <span className="w-full min-w-0 truncate text-xs text-ink-500 sm:w-auto sm:flex-1">
                  {audit.scores?.reasoning}
                </span>
                {audit.run_id && (
                  <Link to={`/traces/${audit.run_id}`} className="text-xs text-accent-600 underline">
                    trace
                  </Link>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
