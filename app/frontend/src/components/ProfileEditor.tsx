/**
 * The master profile, fully editable.
 *
 * These are the facts the agents may state about the candidate — in the cover
 * letter, in the interview brief, in the matcher's read of who this person is.
 * They are no longer what a résumé is built from: that is the candidate's own
 * .docx, uploaded above.
 *
 * **Non-negotiable pins were removed on 2026-08-28** along with the design that
 * needed them. A pin meant "the Résumé agent may re-word this but may not drop
 * it", which was a real guarantee while the agent chose what went on the page.
 * It now edits lines of a document the candidate laid out themselves and has no
 * way to remove an experience, so the guarantee is structural and a star would
 * promise something that is already true.
 *
 * Edits are staged locally and saved in one PUT, so reordering and deleting
 * behave the way an editor should rather than firing a request per keystroke.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { InlineMarkdown } from "./Markdown";
import { api } from "../lib/api";
import type { MasterProfile } from "../lib/types";
import { Button, Card, ErrorNote, Field, SectionTitle, inputClass } from "./ui";

function TextRow({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
}) {
  return (
    <Field label={label}>
      <input
        className={inputClass}
        value={value ?? ""}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </Field>
  );
}

/**
 * The reorder, delete and "+ add" controls.
 *
 * A glyph at text-xs is a 12px target. These sit in dense rows where the wrong
 * one deletes an entry, so they get a finger-sized box on a phone and stay
 * visually small on a laptop, where the pointer is exact.
 */
const ICON_BUTTON =
  "inline-grid h-9 w-9 shrink-0 place-items-center rounded-lg text-xs transition sm:h-6 sm:w-6";

/** A list of plain strings — bullets, coursework, technologies, skills. */
function StringList({
  label,
  items,
  onChange,
  placeholder,
  renderExtra,
}: {
  label: string;
  items: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  renderExtra?: (value: string, index: number) => React.ReactNode;
}) {
  const list = items ?? [];
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-ink-500">{label}</span>
        <button
          type="button"
          onClick={() => onChange([...list, ""])}
          className="-my-1 px-2 py-1.5 text-xs text-accent-600 hover:underline"
        >
          + add
        </button>
      </div>
      {list.map((value, index) => (
        <div key={index} className="flex items-center gap-2">
          <textarea
            rows={1}
            className={`${inputClass} min-h-[2.25rem] resize-y`}
            value={value}
            placeholder={placeholder}
            onChange={(event) => {
              const next = [...list];
              next[index] = event.target.value;
              onChange(next);
            }}
          />
          {renderExtra?.(value, index)}
          <button
            type="button"
            onClick={() => onChange(list.filter((_, i) => i !== index))}
            className={`${ICON_BUTTON} text-ink-400 hover:text-red-600`}
            title="Remove"
          >
            ✕
          </button>
        </div>
      ))}
      {list.length === 0 && <p className="text-xs text-ink-400">None yet.</p>}
    </div>
  );
}

function EntryShell({
  title,
  onRemove,
  onMove,
  children,
}: {
  title: string;
  onRemove: () => void;
  onMove: (delta: number) => void;
  children: React.ReactNode;
}) {
  return (
    <div className="squircle rounded-card border border-ink-200 p-3 dark:border-ink-700">
      <div className="mb-2 flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {title || <span className="text-ink-400">Untitled</span>}
        </span>
        <button
          type="button"
          onClick={() => onMove(-1)}
          className={`${ICON_BUTTON} text-ink-400 hover:text-ink-700`}
          title="Move up"
        >
          ↑
        </button>
        <button
          type="button"
          onClick={() => onMove(1)}
          className={`${ICON_BUTTON} text-ink-400 hover:text-ink-700`}
          title="Move down"
        >
          ↓
        </button>
        <button
          type="button"
          onClick={onRemove}
          className={`${ICON_BUTTON} text-ink-400 hover:text-red-600`}
          title="Delete"
        >
          ✕
        </button>
      </div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

const EMPTY: MasterProfile = {
  full_name: "",
  headline: "",
  email: "",
  phone: "",
  location: "",
  linkedin_url: "",
  github_url: "",
  portfolio_url: "",
  summary: "",
  experiences: [],
  education: [],
  projects: [],
  skills: [],
  languages: [],
  certifications: [],
  awards: [],
  interests: [],
  extraction_notes: "",
};

export function ProfileEditor({ profile }: { profile: MasterProfile }) {
  const queryClient = useQueryClient();
  // `base` is what the server last told us it holds; `draft` is what is on
  // screen. Dirtiness is the distance between the two, which is why `base` is
  // kept rather than re-derived from the query: an import landing mid-edit
  // moves the query result, and comparing against that would call every field
  // changed and then throw the real changes away.
  const [base, setBase] = useState<MasterProfile>(() => ({ ...EMPTY, ...profile }));
  const [draft, setDraft] = useState<MasterProfile>(base);

  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(base), [draft, base]);

  // Re-seed when a new document is imported and the merged profile changes
  // underneath us — but not while there are unsaved edits to lose.
  const fingerprint = JSON.stringify({ ...EMPTY, ...profile });
  useEffect(() => {
    if (dirty) return;
    const next = { ...EMPTY, ...profile };
    setBase(next);
    setDraft(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fingerprint]);

  // The saved profile moved while there were edits on screen — an import that
  // finished, or the contact-details form above. Neither side can be dropped
  // silently, so the edits stay and the note at the foot says what happened.
  const serverMoved = dirty && fingerprint !== JSON.stringify(base);

  const seed = (saved: MasterProfile) => {
    const next = { ...EMPTY, ...saved };
    setBase(next);
    setDraft(next);
  };

  const save = useMutation({
    mutationFn: () =>
      api.put<{ profile: MasterProfile }>("/api/profile/master", { profile: draft }),
    onSuccess: (result) => {
      // Seed from what came back rather than from the draft: the server
      // validates against `MasterProfile` and may normalise what it stores.
      seed(result.profile);
      queryClient.invalidateQueries({ queryKey: ["profile"] });
    },
  });

  const set = <K extends keyof MasterProfile>(key: K, value: MasterProfile[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  /** Add / remove / reorder helpers for a list-valued field. */
  function listOps<T>(key: keyof MasterProfile) {
    const list = (draft[key] as unknown as T[]) ?? [];
    return {
      list,
      update: (index: number, patch: Partial<T>) =>
        set(
          key,
          list.map((item, i) => (i === index ? { ...item, ...patch } : item)) as never,
        ),
      remove: (index: number) => set(key, list.filter((_, i) => i !== index) as never),
      add: (blank: T) => set(key, [...list, blank] as never),
      move: (index: number, delta: number) => {
        const target = index + delta;
        if (target < 0 || target >= list.length) return;
        const next = [...list];
        [next[index], next[target]] = [next[target], next[index]];
        set(key, next as never);
      },
    };
  }

  const experiences = listOps<any>("experiences");
  const education = listOps<any>("education");
  const projects = listOps<any>("projects");
  const languages = listOps<any>("languages");

  return (
    <Card className="space-y-6">
      <SectionTitle
        title="Master profile"
        subtitle="The facts the agents are allowed to state about you. Your résumé is the document that gets sent; this is what the cover letter, the interview brief and the matching are argued from."
        action={
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
            {save.isSuccess && !dirty && <span className="text-xs text-emerald-600">Saved</span>}
            <Button
              className="flex-1 sm:flex-none"
              onClick={() => save.mutate()}
              disabled={!dirty || save.isPending}
            >
              {save.isPending ? "Saving…" : "Save profile"}
            </Button>
          </div>
        }
      />
      <ErrorNote error={save.error} />

      <div className="grid gap-3 md:grid-cols-2">
        <TextRow label="Full name" value={draft.full_name} onChange={(v) => set("full_name", v)} />
        <TextRow label="Headline" value={draft.headline} onChange={(v) => set("headline", v)} />
        <TextRow label="Email" value={draft.email} onChange={(v) => set("email", v)} />
        <TextRow label="Phone" value={draft.phone} onChange={(v) => set("phone", v)} />
        <TextRow label="Location" value={draft.location} onChange={(v) => set("location", v)} />
        <TextRow label="LinkedIn" value={draft.linkedin_url} onChange={(v) => set("linkedin_url", v)} />
        <TextRow label="GitHub" value={draft.github_url} onChange={(v) => set("github_url", v)} />
        <TextRow label="Portfolio" value={draft.portfolio_url} onChange={(v) => set("portfolio_url", v)} />
      </div>

      <Field label="Summary">
        <textarea
          rows={3}
          className={`${inputClass} resize-y`}
          value={draft.summary ?? ""}
          onChange={(event) => set("summary", event.target.value)}
        />
      </Field>

      <Section
        title="Experience"
        onAdd={() =>
          experiences.add({ title: "", organisation: "", location: "", start_date: "", end_date: "", description: "", highlights: [], skills: [] })
        }
      >
        {experiences.list.map((entry, index) => (
          <EntryShell
            key={index}
            title={[entry.organisation, entry.title].filter(Boolean).join(" — ")}
            onRemove={() => experiences.remove(index)}
            onMove={(delta) => experiences.move(index, delta)}
          >
            <div className="grid gap-2 md:grid-cols-2">
              <TextRow label="Organisation" value={entry.organisation} onChange={(v) => experiences.update(index, { organisation: v })} />
              <TextRow label="Title" value={entry.title} onChange={(v) => experiences.update(index, { title: v })} />
              <TextRow label="Location" value={entry.location} onChange={(v) => experiences.update(index, { location: v })} />
              <div className="grid grid-cols-2 gap-2">
                <TextRow label="From" value={entry.start_date} onChange={(v) => experiences.update(index, { start_date: v })} placeholder="Sept 2025" />
                <TextRow label="To" value={entry.end_date} onChange={(v) => experiences.update(index, { end_date: v })} placeholder="Présent" />
              </div>
            </div>
            <StringList
              label="Highlights — what the Cover Letter agent and the Interview Coach draw on"
              items={entry.highlights}
              onChange={(next) => experiences.update(index, { highlights: next })}
            />
          </EntryShell>
        ))}
      </Section>

      <Section
        title="Education"
        onAdd={() => education.add({ degree: "", institution: "", location: "", start_date: "", end_date: "", details: "", coursework: [] })}
      >
        {education.list.map((entry, index) => (
          <EntryShell
            key={index}
            title={[entry.institution, entry.degree].filter(Boolean).join(" — ")}
            onRemove={() => education.remove(index)}
            onMove={(delta) => education.move(index, delta)}
          >
            <div className="grid gap-2 md:grid-cols-2">
              <TextRow label="Institution" value={entry.institution} onChange={(v) => education.update(index, { institution: v })} />
              <TextRow label="Degree" value={entry.degree} onChange={(v) => education.update(index, { degree: v })} />
              <TextRow label="Location" value={entry.location} onChange={(v) => education.update(index, { location: v })} />
              <div className="grid grid-cols-2 gap-2">
                <TextRow label="From" value={entry.start_date} onChange={(v) => education.update(index, { start_date: v })} />
                <TextRow label="To" value={entry.end_date} onChange={(v) => education.update(index, { end_date: v })} />
              </div>
            </div>
            <TextRow label="Details (GPA, rank, thesis)" value={entry.details} onChange={(v) => education.update(index, { details: v })} />
            <StringList label="Coursework" items={entry.coursework} onChange={(next) => education.update(index, { coursework: next })} />
          </EntryShell>
        ))}
      </Section>

      <Section title="Projects" onAdd={() => projects.add({ name: "", description: "", url: "", highlights: [], technologies: [] })}>
        {projects.list.map((entry, index) => (
          <EntryShell
            key={index}
            title={entry.name}
            onRemove={() => projects.remove(index)}
            onMove={(delta) => projects.move(index, delta)}
          >
            <div className="grid gap-2 md:grid-cols-2">
              <TextRow label="Name" value={entry.name} onChange={(v) => projects.update(index, { name: v })} />
              <TextRow label="URL" value={entry.url} onChange={(v) => projects.update(index, { url: v })} />
            </div>
            <TextRow label="Description" value={entry.description} onChange={(v) => projects.update(index, { description: v })} />
            <StringList label="Highlights" items={entry.highlights} onChange={(next) => projects.update(index, { highlights: next })} />
            <StringList label="Technologies" items={entry.technologies} onChange={(next) => projects.update(index, { technologies: next })} />
          </EntryShell>
        ))}
      </Section>

      <Section title="Languages" onAdd={() => languages.add({ language: "", level: "" })}>
        {languages.list.map((entry, index) => (
          <div key={index} className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <div className="grid flex-1 grid-cols-2 gap-2">
              <TextRow label="Language" value={entry.language} onChange={(v) => languages.update(index, { language: v })} />
              <TextRow label="Level" value={entry.level} onChange={(v) => languages.update(index, { level: v })} placeholder="C2 / natif" />
            </div>
            <div className="flex items-center gap-2 sm:pb-2">
              <button
                type="button"
                onClick={() => languages.remove(index)}
                className={`${ICON_BUTTON} text-ink-400 hover:text-red-600`}
                title="Remove"
              >
                ✕
              </button>
            </div>
          </div>
        ))}
      </Section>

      {(
        [
          ["Skills", "skills"],
          ["Certifications", "certifications"],
          ["Awards", "awards"],
          ["Interests", "interests"],
        ] as const
      ).map(([label, key]) => (
        <StringList
          key={key}
          label={label}
          items={(draft[key] as string[]) ?? []}
          onChange={(next) => set(key, next as never)}
        />
      ))}

      {draft.extraction_notes && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
          Extraction notes: <InlineMarkdown>{draft.extraction_notes}</InlineMarkdown>
        </p>
      )}

      {dirty && (
        <p className="text-xs text-ink-500">
          Unsaved changes — the button above writes them.
          {serverMoved && (
            <>
              {" "}
              The saved profile changed while you were editing — an import finishing, or the
              contact details above. What is on screen is yours and wins when you save; reload to
              take the other version instead.
            </>
          )}
        </p>
      )}
    </Card>
  );
}

function Section({
  title,
  onAdd,
  children,
}: {
  title: string;
  onAdd: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">{title}</h3>
        <button
          type="button"
          onClick={onAdd}
          className="-my-1 px-2 py-1.5 text-xs text-accent-600 hover:underline"
        >
          + add
        </button>
      </div>
      {children}
    </div>
  );
}
