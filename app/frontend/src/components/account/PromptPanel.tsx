import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  ScoreBadge,
  SectionTitle,
  Spinner,
} from "../ui";
import { AuditPanel } from "../AuditPanel";
import { api } from "../../lib/api";
import type { AgentPrompt } from "../../lib/types";

/**
 * One of the two steering prompts: its score, its text, its versions.
 *
 * The search brief and the hiring playbook are their own steps of the account
 * setup — different producers, different inputs, one shown under the other —
 * but what you do with either once it exists is identical, so the panel below
 * the heading is one component used twice.
 */
export function PromptPanel({
  kind,
  label,
  emptyHint,
}: {
  kind: "search_brief" | "playbook";
  label: string;
  emptyHint: string;
}) {
  const { data: active, isLoading } = useQuery({
    queryKey: ["prompts", "active"],
    queryFn: () => api.get<Record<string, AgentPrompt | null>>("/api/strategy/prompts/active"),
  });
  const { data: versions } = useQuery({
    queryKey: ["prompts", "all"],
    queryFn: () => api.get<{ prompts: AgentPrompt[] }>("/api/strategy/prompts"),
  });

  const current = active?.[kind] ?? null;
  const history = (versions?.prompts ?? []).filter((prompt) => prompt.kind === kind);

  if (isLoading) return <Spinner label={`Loading the ${label.toLowerCase()}…`} />;
  if (!current) return <EmptyState title={`No ${label.toLowerCase()} yet`} hint={emptyHint} />;

  return (
    <div className="space-y-4">
      <AuditPanel audit={current.audit} title={`${label} v${current.version}`} />
      <PromptEditor prompt={current} history={history} />
    </div>
  );
}

function PromptEditor({ prompt, history }: { prompt: AgentPrompt; history: AgentPrompt[] }) {
  const queryClient = useQueryClient();
  const [content, setContent] = useState(prompt.content);
  const [showJson, setShowJson] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => setContent(prompt.content), [prompt.id, prompt.content]);

  // Grow the field to its content instead of scrolling inside a fixed box.
  // These prompts are read far more often than they are edited, and a window
  // onto a third of one — with its own scrollbar, inside a page that already
  // scrolls — hid most of what the agents are actually being told.
  useLayoutEffect(() => {
    const field = textarea.current;
    if (!field) return;
    field.style.height = "auto";
    // `scrollHeight` is content plus padding, and the box is border-box, so the
    // border has to be added back or the last line loses two pixels to it.
    const border = field.offsetHeight - field.clientHeight;
    field.style.height = `${field.scrollHeight + border}px`;
  }, [content, showJson]);

  const save = useMutation({
    mutationFn: () =>
      api.put(`/api/strategy/prompts/${prompt.kind}`, {
        content,
        note: "Edited by hand.",
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  });

  const activate = useMutation({
    mutationFn: (id: number) => api.post(`/api/strategy/prompts/${id}/activate`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["prompts"] }),
  });

  const dirty = content !== prompt.content;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_260px]">
      <Card>
        <SectionTitle
          title={prompt.title || prompt.kind}
          subtitle={`Version ${prompt.version} · written by ${prompt.author} · ${new Date(
            prompt.created_at,
          ).toLocaleString()}`}
          action={
            <div className="flex w-full flex-wrap gap-2 sm:w-auto">
              <Button variant="ghost" size="sm" onClick={() => setShowJson((value) => !value)}>
                {showJson ? "Show prompt" : "Show structured data"}
              </Button>
              <Button
                size="sm"
                className="flex-1 sm:flex-none"
                onClick={() => save.mutate()}
                disabled={!dirty || save.isPending}
              >
                {save.isPending ? "Saving…" : dirty ? "Save as new version" : "Saved"}
              </Button>
            </div>
          }
        />
        <ErrorNote error={save.error} />
        {showJson ? (
          <pre className="overflow-x-auto rounded-lg bg-ink-100 p-3 text-xs dark:bg-ink-950">
            {JSON.stringify(prompt.structured, null, 2)}
          </pre>
        ) : (
          <textarea
            ref={textarea}
            value={content}
            onChange={(event) => setContent(event.target.value)}
            spellCheck={false}
            // `resize-none` and no height: the effect above owns the height, and
            // a drag handle would fight it on the next keystroke.
            className="w-full resize-none overflow-hidden rounded-lg border border-ink-200 bg-white p-3 font-mono text-xs leading-relaxed outline-none focus:border-accent-500 dark:border-ink-700 dark:bg-ink-950"
          />
        )}
      </Card>

      <Card>
        <h3 className="mb-3 text-sm font-semibold">Version history</h3>
        <div className="space-y-2">
          {history.map((version) => (
            <div
              key={version.id}
              className={`rounded-lg border px-3 py-2 text-sm ${
                version.is_active
                  ? "border-accent-500 bg-accent-500/5"
                  : "border-ink-200 dark:border-ink-800"
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">v{version.version}</span>
                <div className="flex items-center gap-1.5">
                  {/* Only agent versions carry one: a hand-edited version is
                      never re-scored, so its absence is information too. */}
                  {version.audit && (
                    <ScoreBadge score={version.audit.overall} threshold={version.audit.threshold} />
                  )}
                  <Badge tone={version.author === "user" ? "info" : "neutral"}>
                    {version.author}
                  </Badge>
                </div>
              </div>
              <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">
                {new Date(version.created_at).toLocaleString()}
              </p>
              {version.note && <p className="mt-1 text-xs text-ink-500">{version.note}</p>}
              {!version.is_active && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => activate.mutate(version.id)}
                  disabled={activate.isPending}
                >
                  Restore
                </Button>
              )}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
