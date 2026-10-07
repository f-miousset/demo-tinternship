/**
 * The settings you can change without redeploying.
 *
 * Which model reasons, which one does the cheap passes, and how strict the
 * quality gate is are the knobs worth turning between runs — so they are a form
 * rather than a read-only list of what the deployment happens to say. The
 * backend stores an override per changed field and assigns it onto the shared
 * settings object, so a save lands on the *next* run: nothing already in flight
 * changes model halfway through. See `services/runtime_config.py`.
 *
 * Edits are staged and saved in one PUT, and each field carries its default as a
 * one-click way back.
 *
 * That default is deliberately called "default" and not ".env". It is the
 * *baseline* — whatever the field started as before any override, which is the
 * code default unless the deployment set an environment variable. The copy used
 * to assert `.env says …`, which was simply false for the knobs `.env` does not
 * mention. See documentation/configuration.md.
 *
 * Models come from both providers — the Gemini API and the machine's own Ollama
 * — grouped in the dropdown and starred where the backend has evidence for the
 * pick. The star is per field: a model that scores artifacts well is not
 * automatically one that writes them.
 *
 * The models are a `select`, not an input with a `datalist`, because a datalist
 * only offers the options that match what is already in the box — and the box
 * always arrives holding the current model, so the popup showed exactly one
 * entry. Every model was in the DOM and none of them was reachable. A select
 * shows the whole list; "Something else…" keeps the free-text escape for a
 * model the listing does not have.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import { formatModelPrice } from "../lib/models";
import type { ConfigField, EditableConfig, ModelOption } from "../lib/types";
import { Badge, Button, ErrorNote, Spinner, inputClass } from "./ui";

type Draft = Record<string, string>;

/** Sentinel option: not a model, it switches the field to free text. */
const CUSTOM_MODEL = "__custom__";

/** Where a model runs, in the order the dropdown groups them. */
const PROVIDERS = [
  { key: "gemini", heading: "Gemini API" },
  { key: "ollama", heading: "On this machine — Ollama" },
] as const;

function toDraft(fields: ConfigField[]): Draft {
  return Object.fromEntries(fields.map((field) => [field.key, String(field.value)]));
}

/** The payload the backend wants: numbers as numbers, models as trimmed text. */
function toPayload(fields: ConfigField[], draft: Draft): Record<string, string | number> {
  return Object.fromEntries(
    fields.map((field) => [
      field.key,
      field.kind === "number" ? Number(draft[field.key]) : draft[field.key].trim(),
    ]),
  );
}

/** Why this value cannot be saved, or "" if it can. Mirrors the backend checks. */
function problem(field: ConfigField, raw: string): string {
  const value = raw.trim();
  if (field.kind === "model") return value ? "" : "Required";
  const number = Number(value);
  if (!value || Number.isNaN(number)) return "Must be a number";
  if (field.min !== null && number < field.min) return `Minimum ${field.min}`;
  if (field.max !== null && number > field.max) return `Maximum ${field.max}`;
  return "";
}

export function ConfigForm() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["settings", "config"],
    queryFn: () => api.get<EditableConfig>("/api/settings/config"),
  });

  const fields = useMemo(() => data?.fields ?? [], [data]);
  const [base, setBase] = useState<Draft>({});
  const [draft, setDraft] = useState<Draft>({});

  // Re-seed when the server's values change under us — a reset, or another tab.
  // `base` is kept rather than read from the query so dirtiness is the distance
  // from what was last saved, not from whatever the query most recently held.
  const fingerprint = JSON.stringify(fields.map((field) => [field.key, field.value]));
  useEffect(() => {
    const next = toDraft(fields);
    setBase(next);
    setDraft(next);
  }, [fingerprint]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = fields.some((field) => draft[field.key] !== base[field.key]);
  const invalid = fields.some((field) => problem(field, draft[field.key] ?? ""));
  const overridden = fields.some((field) => field.overridden);

  const seed = (result: EditableConfig) => {
    const next = toDraft(result.fields);
    setBase(next);
    setDraft(next);
    queryClient.setQueryData(["settings", "config"], result);
    // The read-only rows on this page, and anything else showing the models,
    // come from /api/config — which now answers differently.
    queryClient.invalidateQueries({ queryKey: ["config"] });
  };

  const save = useMutation({
    mutationFn: () => api.put<EditableConfig>("/api/settings/config", toPayload(fields, draft)),
    onSuccess: seed,
  });

  const restore = useMutation({
    mutationFn: () => api.del<EditableConfig>("/api/settings/config"),
    onSuccess: seed,
  });

  const pending = save.isPending || restore.isPending;

  if (isLoading) return <Spinner label="Loading settings…" />;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map((field) => (
          <FieldRow
            key={field.key}
            field={field}
            value={draft[field.key] ?? ""}
            models={data?.model_options ?? []}
            onChange={(next) => setDraft((current) => ({ ...current, [field.key]: next }))}
          />
        ))}
      </div>

      <p className="text-xs text-ink-500 dark:text-ink-400">
        ★ marks a tested pick for that field. The local ones are the models that passed the same
        golden cases <code>make eval</code> holds the Critic to; an unstarred model is untested,
        not rejected.
      </p>

      <OllamaNote ollama={data?.ollama} />

      <ErrorNote error={save.error ?? restore.error} />

      <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center">
        <Button onClick={() => save.mutate()} disabled={!dirty || invalid || pending}>
          {save.isPending ? "Saving…" : "Save configuration"}
        </Button>
        {overridden && (
          <Button
            variant="ghost"
            onClick={() => restore.mutate()}
            disabled={pending}
            title="Drop every change and go back to the defaults"
          >
            {restore.isPending ? "Restoring…" : "Restore defaults"}
          </Button>
        )}
        <p className="text-xs text-ink-500 sm:ml-auto dark:text-ink-400">
          {(save.isSuccess || restore.isSuccess) && !dirty ? (
            <span className="text-emerald-600 dark:text-emerald-400">
              Saved — applies to the next run.
            </span>
          ) : (
            "Applies to the next run; anything already running keeps its models."
          )}
        </p>
      </div>
    </div>
  );
}

/**
 * Where the local models come from, and whether anything is there.
 *
 * Silent when Ollama is answering and unused — that is just a machine with
 * Ollama installed, not something to report. It speaks up when a local model is
 * selected and nothing is listening, because that is a run about to fail.
 */
function OllamaNote({ ollama }: { ollama?: EditableConfig["ollama"] }) {
  if (!ollama) return null;

  if (ollama.in_use && !ollama.reachable) {
    return (
      <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
        A local model is selected, but nothing is answering at <code>{ollama.base_url}</code>.
        Start Ollama, or pick a Gemini model above — runs will fail until one or the other.
      </p>
    );
  }

  if (!ollama.reachable) {
    return (
      <p className="text-xs text-ink-500 dark:text-ink-400">
        No local models: nothing is answering at <code>{ollama.base_url}</code>. Start Ollama to
        run the writing on your own machine.
      </p>
    );
  }

  return null;
}

function FieldRow({
  field,
  value,
  models,
  onChange,
}: {
  field: ConfigField;
  value: string;
  models: ModelOption[];
  onChange: (next: string) => void;
}) {
  const invalid = problem(field, value);
  const isDefault = value.trim() === String(field.default);
  const chosen = models.find((model) => model.id === value.trim());
  // Unpriced models still run — they just have no entry in the cost table, so
  // every trace of theirs reads $0 and the spend column quietly lies. A local
  // model is the opposite case: the $0 is the truth, and worth saying.
  const unpriced = field.kind === "model" && value.trim().length > 0 && !chosen?.priced;
  // A `label` wrapping the whole row would forward a click on the revert link
  // to the control, popping the model dropdown open every time.
  const id = `config-${field.key}`;

  return (
    <div>
      <label htmlFor={id} className="mb-1 flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-ink-500 dark:text-ink-400">
          {field.label}
        </span>
        {field.overridden && <Badge tone="info">changed from default</Badge>}
      </label>

      {field.kind === "model" ? (
        <ModelPicker
          id={id}
          value={value}
          fieldKey={field.key}
          models={models.filter((model) => field.providers.includes(model.provider))}
          onChange={onChange}
        />
      ) : (
        <input
          id={id}
          className={inputClass}
          type="number"
          inputMode="decimal"
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          step={field.step ?? undefined}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}

      {/* No model name here: the select shows it, and repeating it under the
          field just pushed the id off the end of a 375px screen. */}
      <span className="mt-1 block text-xs text-ink-500 dark:text-ink-400">
        {field.help}
        {field.kind === "number" && field.min !== null && field.max !== null && (
          <span className="text-ink-400 dark:text-ink-500">
            {" "}
            ({field.min}–{field.max})
          </span>
        )}
      </span>

      {invalid && <span className="mt-1 block text-xs text-red-600">{invalid}</span>}

      {!isDefault && (
        <button
          type="button"
          onClick={() => onChange(String(field.default))}
          className="mt-1 text-xs text-ink-500 underline decoration-dotted underline-offset-2 transition hover:text-accent-600 dark:text-ink-400"
        >
          Default is {String(field.default)} — use it
        </button>
      )}

      {chosen?.provider === "ollama" &&
        (chosen.local ? (
          <span className="mt-1 block text-xs text-emerald-700 dark:text-emerald-400">
            Runs on your machine through Ollama — no API cost, and nothing leaves it.
          </span>
        ) : (
          // Ollama lists its `…-cloud` models exactly like the real local ones.
          // Promising privacy for one of those would be a lie.
          <span className="mt-1 block text-xs text-amber-600 dark:text-amber-500">
            Reached through your Ollama but running on {chosen.remote_host} — your profile and
            the postings leave this machine, and it is not free.
          </span>
        ))}

      {unpriced && (
        <span className="mt-1 block text-xs text-amber-600 dark:text-amber-500">
          No price on record for this model — its runs will show $0 in the traces.
        </span>
      )}
    </div>
  );
}

/**
 * Every model the key can run, plus a way to name one it did not list.
 *
 * The current value is always among the options, even when the listing has
 * never heard of it — a select whose value matches no option renders blank, and
 * a blank model field is the one thing this must never show.
 */
function ModelPicker({
  id,
  value,
  fieldKey,
  models,
  onChange,
}: {
  id: string;
  value: string;
  fieldKey: string;
  models: ModelOption[];
  onChange: (next: string) => void;
}) {
  const trimmed = value.trim();
  const listed = models.some((model) => model.id === trimmed);
  const [typing, setTyping] = useState(false);

  // Nothing to pick from — an unusable key, or a listing that failed twice over.
  if (typing || models.length === 0) {
    return (
      <div className="flex items-center gap-2">
        <input
          id={id}
          className={inputClass}
          value={value}
          spellCheck={false}
          autoComplete="off"
          placeholder="model id, e.g. gemini-3.6-flash"
          onChange={(event) => onChange(event.target.value)}
        />
        {models.length > 0 && (
          <button
            type="button"
            onClick={() => setTyping(false)}
            className="shrink-0 text-xs text-ink-500 underline decoration-dotted underline-offset-2 transition hover:text-accent-600 dark:text-ink-400"
          >
            Back to the list
          </button>
        )}
      </div>
    );
  }

  return (
    <select
      id={id}
      className={inputClass}
      value={trimmed}
      onChange={(event) => {
        if (event.target.value === CUSTOM_MODEL) {
          setTyping(true);
          return;
        }
        onChange(event.target.value);
      }}
    >
      {!listed && <option value={trimmed}>{trimmed || "— none —"} (not in the listing)</option>}
      {PROVIDERS.map(({ key, heading }) => {
        const group = models.filter((model) => model.provider === key);
        if (group.length === 0) return null;
        return (
          <optgroup key={key} label={heading}>
            {group.map((model) => {
              const priceTag = formatModelPrice(model);
              return (
                <option key={model.id} value={model.id}>
                  {model.recommended_for.includes(fieldKey) ? "★ " : ""}
                  {model.label ? `${model.label} — ${model.id}` : model.id}
                  {priceTag ? ` (${priceTag})` : ""}
                </option>
              );
            })}
          </optgroup>
        );
      })}
      <option value={CUSTOM_MODEL}>Something else…</option>
    </select>
  );
}
