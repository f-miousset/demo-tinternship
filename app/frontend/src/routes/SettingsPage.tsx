import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ConfigForm } from "../components/ConfigForm";
import { GlassSlider, ThemeSwitch } from "../components/ThemeSwitch";
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  SectionTitle,
  Spinner,
  inputClass,
} from "../components/ui";
import { api } from "../lib/api";
import { systemTheme, useTheme } from "../lib/theme";
import type { AppConfig } from "../lib/types";

interface ResetScope {
  key: string;
  label: string;
  description: string;
}

interface StoredData {
  summary: Record<string, number>;
  scopes: ResetScope[];
  confirm_phrase: string;
}

const SUMMARY_LABELS: [string, string][] = [
  ["profile_sources", "imported documents"],
  ["prompts", "prompt versions"],
  ["jobs", "job postings"],
  ["applications", "applications"],
  ["artifacts", "generated documents"],
  ["runs", "agent runs"],
  ["trace_events", "logged decisions"],
  ["audits", "quality audits"],
];

export function SettingsPage() {
  const queryClient = useQueryClient();
  const { choice, theme } = useTheme();
  const [selected, setSelected] = useState<Set<string> | null>(null);
  const [confirm, setConfirm] = useState("");
  const [result, setResult] = useState<Record<string, number> | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["settings", "data"],
    queryFn: () => api.get<StoredData>("/api/settings/data"),
  });
  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => api.get<AppConfig>("/api/config"),
  });

  // Default to everything selected — "start from a blank page" is the common case.
  const scopes = data?.scopes ?? [];
  const chosen = selected ?? new Set(scopes.map((scope) => scope.key));

  const reset = useMutation({
    mutationFn: () =>
      api.post<{ deleted: Record<string, number> }>("/api/settings/reset", {
        scopes: [...chosen],
        confirm,
      }),
    onSuccess: (response) => {
      setResult(response.deleted);
      setConfirm("");
      // Everything on screen may now be stale.
      queryClient.invalidateQueries();
    },
  });

  function toggle(key: string) {
    const next = new Set(chosen);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
    setResult(null);
  }

  const phrase = data?.confirm_phrase ?? "DELETE";
  const summary = data?.summary ?? {};
  const nothingStored = Object.entries(summary).every(([, value]) => !value);
  const canReset = chosen.size > 0 && confirm === phrase && !reset.isPending;

  return (
    <div className="space-y-5">
      <SectionTitle
        title="Settings"
        subtitle="What this app has stored on your machine, and how to clear it."
      />

      {/* First, and above Configuration, because it is the one thing on this
          page that changes nothing about how the agents run — and the one most
          likely to be the reason the page was opened at all. */}
      <Card className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold">Appearance</h3>
            <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">
              {choice === "system"
                ? `Following your device, which is ${theme} right now.`
                : `Overriding your device, which is ${systemTheme()} right now.`}{" "}
              Both settings are stored in this browser — nothing about them reaches the API.
            </p>
          </div>
          <ThemeSwitch />
        </div>

        {/* Under the theme rather than beside it: the two are one card because
            they are the same kind of setting, but this one is watched rather
            than clicked — the header and the tab bar are the preview, and they
            are directly above and below the slider while it moves. */}
        <div className="flex flex-col gap-2 border-t border-ink-900/10 pt-4 sm:flex-row sm:items-center sm:justify-between dark:border-white/10">
          <p className="min-w-0 text-xs text-ink-500 dark:text-ink-400">
            How much of the page shows through the glass — the header, the tab bar, the sheets.
            Your device wins if it asks for reduced transparency.
          </p>
          <GlassSlider />
        </div>
      </Card>

      <Card className="space-y-5">
        <div>
          <h3 className="text-sm font-semibold">Configuration</h3>
          <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">
            The models the agents run on and how strict the quality gate is. Changing one here
            beats editing <code>.env</code> and restarting, so you can try a value and look at
            the next run.
          </p>
        </div>

        <ConfigForm />

        <div>
          <h4 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-500 dark:text-ink-400">
            Not editable here
          </h4>
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            <Row
              label="Gemini key"
              value={config?.gemini_configured ? "configured" : "missing"}
              tone={config?.gemini_configured ? "good" : "bad"}
            />
            <Row
              label="Job boards"
              value={
                config?.job_sources.length
                  ? config.job_sources.join(", ")
                  : "grounded search only"
              }
              tone={config?.job_sources.length ? "good" : "neutral"}
            />
            <Row
              label="Searched first"
              value={
                config?.priority_platforms.length
                  ? config.priority_platforms.join(", ")
                  : "no priority platforms — open web only"
              }
              tone={config?.priority_platforms.length ? "good" : "neutral"}
            />
            <Row
              label="Base résumés"
              value={
                config?.progress.has_base_resumes
                  ? "French and English uploaded"
                  : "missing — applications cannot be produced"
              }
              tone={config?.progress.has_base_resumes ? "good" : "warn"}
            />
            <Row
              label="Base cover letters"
              value={
                config?.progress.has_base_letters
                  ? "French and English uploaded"
                  : "missing — applications cannot be produced"
              }
              tone={config?.progress.has_base_letters ? "good" : "warn"}
            />
          </div>
          <p className="mt-3 text-xs text-ink-500 dark:text-ink-400">
            These come from <code>.env</code> at the repo root, and are read once at startup —
            changing one needs a backend restart.
          </p>
        </div>
      </Card>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">Traces &amp; audit</h3>
            <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">
              Every agent, model and tool call with its inputs, outputs, tokens and latency, and
              the quality score of every generated document.
            </p>
          </div>
          <Link
            to="/traces"
            className="inline-flex min-h-10 w-full items-center justify-center rounded-lg border border-ink-200 px-3 text-sm font-medium transition hover:border-accent-400 sm:min-h-0 sm:w-auto sm:py-1.5 dark:border-ink-800"
          >
            Open traces →
          </Link>
        </div>
      </Card>

      <Card>
        <h3 className="mb-3 text-sm font-semibold">Stored data</h3>
        {isLoading && <Spinner label="Loading…" />}
        {!isLoading && (
          <div className="flex flex-wrap gap-2">
            {nothingStored ? (
              <p className="text-sm text-ink-500 dark:text-ink-400">
                Nothing stored yet — this is already a blank page.
              </p>
            ) : (
              SUMMARY_LABELS.map(([key, label]) =>
                summary[key] ? (
                  <Badge key={key}>
                    {summary[key]} {label}
                  </Badge>
                ) : null,
              )
            )}
          </div>
        )}
      </Card>

      <Card className="border-red-300 dark:border-red-900">
        <SectionTitle
          title="Start from a blank page"
          subtitle="Deletes the selected data from your machine. This cannot be undone — there is no backup and no undo."
        />

        <div className="space-y-2">
          {scopes.map((scope) => (
            <label
              key={scope.key}
              className="flex cursor-pointer items-start gap-3 rounded-lg border border-ink-200 px-3 py-3 transition hover:bg-ink-50 sm:py-2.5 dark:border-ink-800 dark:hover:bg-ink-800/50"
            >
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 shrink-0"
                checked={chosen.has(scope.key)}
                onChange={() => toggle(scope.key)}
              />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{scope.label}</span>
                <span className="block text-xs text-ink-500 dark:text-ink-400">
                  {scope.description}
                </span>
              </span>
            </label>
          ))}
        </div>

        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setSelected(new Set(scopes.map((s) => s.key)));
              setResult(null);
            }}
          >
            Select all
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setSelected(new Set());
              setResult(null);
            }}
          >
            Select none
          </Button>
          <Button
            size="sm"
            variant="ghost"
            title="Clears the search and its results but keeps your profile and your four base documents"
            onClick={() => {
              setSelected(new Set(["strategy", "jobs", "conversations", "traces"]));
              setResult(null);
            }}
          >
            Keep profile & résumés, clear the rest
          </Button>
        </div>

        <div className="mt-4 flex flex-col items-stretch gap-3 sm:flex-row sm:flex-wrap sm:items-end">
          <label className="block sm:min-w-56 sm:flex-1">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-ink-500">
              Type {phrase} to confirm
            </span>
            <input
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              placeholder={phrase}
              className={inputClass}
            />
          </label>
          <Button variant="danger" disabled={!canReset} onClick={() => reset.mutate()}>
            {reset.isPending
              ? "Deleting…"
              : `Delete ${chosen.size} categor${chosen.size === 1 ? "y" : "ies"}`}
          </Button>
        </div>

        <ErrorNote error={reset.error} />

        {result && (
          <div className="mt-4 rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2.5 text-sm dark:border-emerald-900 dark:bg-emerald-950/30">
            <p className="font-medium text-emerald-900 dark:text-emerald-300">Deleted.</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {Object.entries(result)
                .filter(([, value]) => value > 0)
                .map(([key, value]) => (
                  <Badge key={key} tone="good">
                    {value} {key.replace(/_/g, " ")}
                  </Badge>
                ))}
              {Object.values(result).every((value) => !value) && (
                <span className="text-emerald-800 dark:text-emerald-300">
                  There was nothing left to delete.
                </span>
              )}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value?: string;
  tone?: "good" | "bad" | "warn" | "neutral";
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-ink-100 py-1 dark:border-ink-800">
      <span className="text-ink-500 dark:text-ink-400">{label}</span>
      {tone && tone !== "neutral" ? (
        <Badge tone={tone}>{value ?? "—"}</Badge>
      ) : (
        <span className="font-medium">{value ?? "—"}</span>
      )}
    </div>
  );
}
