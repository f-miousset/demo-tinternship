import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useRef, useState } from "react";

import { ProfileEditor } from "../ProfileEditor";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Field,
  SectionTitle,
  Spinner,
  inputClass,
} from "../ui";
import { api } from "../../lib/api";
import type {
  BaseDocument,
  CandidateListItem,
  CandidateListKind,
  CandidateLists,
  MasterProfile,
  PackageLanguage,
  ProfileResponse,
  ProfileSource,
} from "../../lib/types";
import { jumpToSection } from "./sections";

const SOURCE_LABELS: Record<string, string> = {
  base_resume: "Base résumé",
  base_cover_letter: "Base cover letter",
  upload_pdf: "PDF",
  upload_docx: "Word",
  linkedin_pdf: "LinkedIn PDF",
  linkedin_archive: "LinkedIn export",
  manual: "Manual",
};

/**
 * The four uploads, as four cards.
 *
 * `kind` is the path segment `/api/profile/base-document/{kind}/{language}`
 * takes, and it is also the artifact kind an applying run produces from it —
 * one vocabulary end to end.
 */
const DOCUMENTS: {
  kind: "resume" | "cover_letter";
  code: PackageLanguage;
  label: string;
  hint: string;
}[] = [
  {
    kind: "resume",
    code: "fr",
    label: "French — CV",
    hint: "Your CV as you would send it to a French employer.",
  },
  {
    kind: "resume",
    code: "en",
    label: "English — résumé",
    hint: "The same career, written the way an English-language employer reads it.",
  },
  {
    kind: "cover_letter",
    code: "fr",
    label: "French — lettre de motivation",
    hint: "Your letterhead, your address block, your sign-off. Leave the three paragraphs blank.",
  },
  {
    kind: "cover_letter",
    code: "en",
    label: "English — cover letter",
    hint: "The same letter for an English-language employer, with the same blanks.",
  },
];

/** What each kind's upload box says about the blanks to leave in it. */
const BLANKS_HINT: Record<"resume" | "cover_letter", ReactNode> = {
  resume: (
    <>
      Leave <code>[a name in brackets]</code> anywhere you want something filled in per
      application: <code>[job_title]</code>, <code>[list_of_relevant_skills]</code>. The name is
      read, so say what you want there.
    </>
  ),
  cover_letter: (
    <>
      Leave <code>[cover_letter_opening_paragraph]</code>,{" "}
      <code>[cover_letter_middle_paragraph]</code> and{" "}
      <code>[cover_letter_closing_paragraph]</code> for the body, plus{" "}
      <code>[company_name]</code>, <code>[team_name]</code>, <code>[job_posting_name]</code> and{" "}
      <code>[current_date]</code> wherever your address block wants them. The date and the
      employer are filled from the posting itself; the paragraphs are written for it.
    </>
  ),
};

export function ProfileSection() {
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["profile"],
    queryFn: () => api.get<ProfileResponse>("/api/profile"),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["profile"] });
    queryClient.invalidateQueries({ queryKey: ["config"] });
  };

  const upload = useMutation({
    mutationFn: (file: File) => api.upload("/api/profile/upload", file),
    onSuccess: invalidate,
  });
  const removeSource = useMutation({
    mutationFn: (id: number) => api.del(`/api/profile/sources/${id}`),
    onSuccess: invalidate,
  });
  const saveLinks = useMutation({
    mutationFn: (body: Record<string, string>) => api.patch("/api/profile", body),
    onSuccess: invalidate,
  });

  const profile = data?.profile ?? {};
  const stored = {
    resume: data?.base_resumes,
    cover_letter: data?.base_cover_letters,
  };
  const ready = DOCUMENTS.every((entry) => stored[entry.kind]?.[entry.code]?.on_disk);

  return (
    <div className="space-y-5">
      <SectionTitle
        title="1 · Your documents"
        subtitle="Upload the CV and the cover letter you already wrote, once each per language. Those four files are what gets sent: an application generates neither document and edits neither — it fills the [blanks] you left in them and copies every other character straight through. Your CV is read for your profile at the same time, so the Interrogator, the letter and the Interview Coach all know your background."
        action={
          ready && data?.has_profile ? (
            <Button onClick={() => jumpToSection("interview")}>Continue to 2 · Interview ↓</Button>
          ) : undefined
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        {DOCUMENTS.map((entry) => (
          <BaseDocumentCard
            key={`${entry.kind}-${entry.code}`}
            document={entry}
            stored={stored[entry.kind]?.[entry.code] ?? null}
            onChange={invalidate}
          />
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ListCard
          kind="course"
          title="Courses you have taken"
          subtitle="Everything on your transcript, one at a time, written the way each language's transcript writes it. The résumé's coursework blank is filled by picking the ones closest to each posting — so what is not here can never be chosen, and nothing outside this list is ever written onto your CV."
          noun="course"
          placeholders={{ en: "Operations Research and Combinatorial Optimisation", fr: "Recherche opérationnelle, optimisation combinatoire" }}
        />
        <ListCard
          kind="skill"
          title="Skills you have"
          subtitle="Languages, frameworks, tools, methods — one at a time, in both languages. Most are the same word twice (Python is Python); the ones that are not are why this asks. The skills blank is filled from this and only this: a term that is not here will not appear, however well it would have matched."
          noun="skill"
          placeholders={{ en: "Data Analysis", fr: "Analyse de données" }}
        />
      </div>

      <Card>
        <SectionTitle
          title="Links & contact details"
          subtitle={
            data?.has_profile
              ? "Also editable, with everything else, in the master profile below."
              : "Documents often omit these."
          }
        />
        <form
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            saveLinks.mutate(Object.fromEntries(form) as Record<string, string>);
          }}
        >
          {[
            ["full_name", "Full name"],
            ["email", "Email"],
            ["phone", "Phone"],
            ["location", "Location"],
            ["linkedin_url", "LinkedIn URL"],
            ["github_url", "GitHub URL"],
            ["portfolio_url", "Portfolio URL"],
          ].map(([name, label]) => (
            <Field key={name} label={label}>
              <input name={name} defaultValue={profile[name] ?? ""} className={inputClass} />
            </Field>
          ))}
          <div className="flex items-end">
            <Button type="submit" className="w-full sm:w-auto" disabled={saveLinks.isPending}>
              {saveLinks.isPending ? "Saving…" : "Save"}
            </Button>
          </div>
        </form>
      </Card>

      <Card>
        <SectionTitle
          title="Other imported documents"
          subtitle="Optional extras that only add facts to the profile — a LinkedIn export, an older CV. They are never sent anywhere. Remove one and the profile is rebuilt from what remains."
        />
        <SupportingUpload
          onPick={(file) => upload.mutate(file)}
          busy={upload.isPending}
          error={upload.error}
        />
        {isLoading && <Spinner label="Loading…" />}
        {!isLoading && !data?.sources.length && (
          <EmptyState
            title="Nothing else imported"
            hint="Your base résumés above already fill in the profile. Add a LinkedIn data export here if you want the projects and certifications a one-page CV leaves out."
          />
        )}
        <div className="space-y-2">
          {data?.sources.map((source) => (
            <SourceRow
              key={source.id}
              source={source}
              onRemove={() => removeSource.mutate(source.id)}
              removing={removeSource.isPending}
            />
          ))}
        </div>
      </Card>

      {data?.has_profile && <ProfileEditor profile={profile as MasterProfile} />}
    </div>
  );
}

/**
 * One of the four mandatory documents.
 *
 * Deliberately loud when it is missing and quiet when it is not: without it no
 * application can be produced in that language at all, so an empty card is a
 * blocker rather than an option not taken. `.docx` is the only accepted format
 * and the card says why — the file is filled in place, and a PDF cannot be.
 *
 * One component for both kinds, because they are the same upload with different
 * words around it. The letter joined on 2026-09-09.
 */
function BaseDocumentCard({
  document,
  stored,
  onChange,
}: {
  document: { kind: "resume" | "cover_letter"; code: PackageLanguage; label: string; hint: string };
  stored: BaseDocument | null;
  onChange: () => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const endpoint = `/api/profile/base-document/${document.kind}/${document.code}`;

  const upload = useMutation({
    mutationFn: (file: File) => api.upload(endpoint, file),
    onSuccess: onChange,
  });
  const remove = useMutation({
    mutationFn: () => api.del(endpoint),
    onSuccess: onChange,
  });

  const present = Boolean(stored?.on_disk);

  return (
    <Card className={present ? undefined : "border-amber-400/60 dark:border-amber-500/40"}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-medium">{document.label}</h3>
        {present ? <Badge tone="good">uploaded</Badge> : <Badge tone="warn">required</Badge>}
      </div>
      <p className="mt-1 text-sm text-ink-500 dark:text-ink-400">{document.hint}</p>

      {present ? (
        <div className="mt-3 space-y-1">
          <p className="truncate text-sm font-medium" title={stored?.label}>
            {stored?.label}
          </p>
          <p className="text-xs text-ink-400">
            Added {new Date(stored!.created_at).toLocaleDateString()} ·{" "}
            {stored!.placeholders} blank{stored!.placeholders === 1 ? "" : "s"} to fill
            {document.kind === "resume" &&
              stored!.status === "failed" &&
              " · the profile extraction failed, the document is fine"}
          </p>
          {stored!.page && (
            <p
              className={
                stored!.crowded
                  ? "text-xs text-amber-700 dark:text-amber-400"
                  : "text-xs text-ink-400"
              }
            >
              {stored!.page}
              {stored!.crowded &&
                " Applications in this language are blocked until there is room — free up a line or two and upload it again."}
            </p>
          )}
          {stored!.language_warning && (
            <p className="text-xs text-amber-700 dark:text-amber-400">
              {stored!.language_warning}
            </p>
          )}
        </div>
      ) : (
        <p className="mt-3 text-sm text-amber-700 dark:text-amber-400">
          Applications in this language cannot be produced until this is uploaded.
        </p>
      )}

      <input
        ref={fileInput}
        type="file"
        accept=".docx"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) upload.mutate(file);
          event.target.value = "";
        }}
      />
      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={() => fileInput.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? "Reading…" : present ? "Replace" : "Upload .docx"}
        </Button>
        {present && (
          <Button variant="ghost" onClick={() => remove.mutate()} disabled={remove.isPending}>
            Remove
          </Button>
        )}
      </div>
      {/* Collapsed, and on purpose. This is the longest text on the card and
          the least often needed: it is read once, while the .docx is being
          prepared, and then never again — but it was printed in full four
          times, which on a phone made the four boxes about three screens of
          the same two paragraphs. Same disclosure as ApplicationPage's
          posting. */}
      <details className="group mt-2">
        <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-ink-500 sm:min-h-0">
          <span className="transition-transform group-open:rotate-90" aria-hidden="true">
            ›
          </span>
          What to leave blank
        </summary>
        <p className="mb-1 break-words text-xs text-ink-400">
          Word <code>.docx</code> only — the blanks are filled in place, so the file has to be
          editable. {BLANKS_HINT[document.kind]} Nothing outside the brackets is ever touched, and
          the result always stays on one page.
        </p>
      </details>
      <ErrorNote error={upload.error} />
      <ErrorNote error={remove.error} />
    </Card>
  );
}

/**
 * One of the two lists the résumé's blanks are filled from.
 *
 * A form that takes **one item at a time, in both languages**, and a list of
 * what has been saved. It was a single textarea per list until 2026-09-08 — one
 * item per line, written once in whichever language came to mind — and the cost
 * of that landed two layers away: the Tailor had to translate the list into the
 * language of the document it was filling, mid-run, inside a blank measured in
 * characters. "Recherche opérationnelle, optimisation combinatoire" came back
 * differently every time and never fitted the line.
 *
 * So the translating moved here, to the one person who knows what the course
 * was actually called. Both fields are required — the Add button stays disabled
 * until both are filled — because a missing side would put the other language's
 * wording on the page silently, which is the failure this replaced.
 *
 * Each saved item is an ordinary row until you press Edit, which is not a
 * secondary path: the 2026-09-08 migration copied every old line into *both*
 * languages, so the list arrives full of items whose other half is still to be
 * written, and this page is where that work gets done.
 */
function ListCard({
  kind,
  title,
  subtitle,
  noun,
  placeholders,
}: {
  kind: CandidateListKind;
  title: string;
  subtitle: string;
  noun: string;
  placeholders: Record<PackageLanguage, string>;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState({ en: "", fr: "" });
  const [editing, setEditing] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["candidate-lists"],
    queryFn: () => api.get<CandidateLists>("/api/profile/lists"),
  });

  // Every mutation answers with both lists, so the cache is written from the
  // response rather than refetched. `config` still has to be invalidated: the
  // first item saved is what flips `has_lists` and unlocks the rest of the app.
  const settle = (result: CandidateLists) => {
    queryClient.setQueryData(["candidate-lists"], result);
    queryClient.invalidateQueries({ queryKey: ["config"] });
  };

  const add = useMutation({
    mutationFn: (item: { en: string; fr: string }) =>
      api.post<CandidateLists>("/api/profile/lists", { kind, ...item }),
    onSuccess: (result) => {
      settle(result);
      setDraft({ en: "", fr: "" });
    },
  });
  const edit = useMutation({
    mutationFn: ({ id, ...item }: { id: number; en: string; fr: string }) =>
      api.patch<CandidateLists>(`/api/profile/lists/${id}`, item),
    onSuccess: (result) => {
      settle(result);
      setEditing(null);
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.del<CandidateLists>(`/api/profile/lists/${id}`),
    onSuccess: settle,
  });

  const items = data?.lists?.[kind] ?? [];
  const complete = items.length > 0;
  const ready = Boolean(draft.en.trim() && draft.fr.trim());

  return (
    <Card className={complete ? undefined : "border-amber-400/60 dark:border-amber-500/40"}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-medium">{title}</h3>
        {complete ? (
          <Badge tone="good">
            {items.length} saved
          </Badge>
        ) : (
          <Badge tone="warn">required</Badge>
        )}
      </div>
      <p className="mt-1 text-sm text-ink-500 dark:text-ink-400">{subtitle}</p>
      {!complete && !isLoading && (
        <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">
          No application can be produced until this list exists — there would be nothing to
          choose from.
        </p>
      )}

      <form
        className="mt-3 space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) add.mutate({ en: draft.en.trim(), fr: draft.fr.trim() });
        }}
      >
        <div className="grid gap-2 sm:grid-cols-2">
          <Field label="English">
            <input
              className={inputClass}
              placeholder={placeholders.en}
              value={draft.en}
              onChange={(event) => setDraft({ ...draft, en: event.target.value })}
            />
          </Field>
          <Field label="French">
            <input
              className={inputClass}
              placeholder={placeholders.fr}
              value={draft.fr}
              onChange={(event) => setDraft({ ...draft, fr: event.target.value })}
            />
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!ready || add.isPending}>
            {add.isPending ? "Saving…" : `Add ${noun}`}
          </Button>
          <span className="text-xs text-ink-400">
            Both languages. If it is the same word in both, write it twice.
          </span>
        </div>
        <ErrorNote error={add.error} />
      </form>

      {isLoading && <Spinner label="Loading…" />}
      <ul className="mt-3 space-y-1">
        {items.map((item) =>
          editing === item.id ? (
            <li key={item.id}>
              <ListItemForm
                item={item}
                placeholders={placeholders}
                saving={edit.isPending}
                error={edit.error}
                onSave={(values) => edit.mutate({ id: item.id, ...values })}
                onCancel={() => setEditing(null)}
              />
            </li>
          ) : (
            // `minmax(0, 1fr)` rather than `flex-1 min-w-0`, which is not
            // enough here: this card is a grid item, so it is sized by its
            // *min-content*, and a flex item's contribution to that is its
            // unwrapped text however small its min-width says it may get. One
            // long course title pushed the whole Account page 162px wider than
            // a 375px phone. The explicit zero minimum is what lets `truncate`
            // do its job — the full text is in the title attribute and in the
            // edit form.
            <li
              key={item.id}
              className="grid grid-cols-[minmax(0,1fr)] items-center gap-1 rounded-lg border border-ink-200 px-3 py-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-2 dark:border-ink-800"
            >
              <span className="min-w-0 text-sm">
                <span className="block truncate" title={item.en}>
                  {item.en}
                </span>
                <span
                  className="block truncate text-xs text-ink-500 dark:text-ink-400"
                  title={item.fr}
                >
                  {item.fr}
                </span>
              </span>
              <span className="flex justify-end gap-1">
                <Button size="sm" variant="ghost" onClick={() => setEditing(item.id)}>
                  Edit
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => remove.mutate(item.id)}
                  disabled={remove.isPending}
                >
                  Remove
                </Button>
              </span>
            </li>
          ),
        )}
      </ul>
      <ErrorNote error={remove.error} />
    </Card>
  );
}

/** One saved item, open for correction. Same two fields as the add form. */
function ListItemForm({
  item,
  placeholders,
  saving,
  error,
  onSave,
  onCancel,
}: {
  item: CandidateListItem;
  placeholders: Record<PackageLanguage, string>;
  saving: boolean;
  error: unknown;
  onSave: (values: { en: string; fr: string }) => void;
  onCancel: () => void;
}) {
  const [values, setValues] = useState({ en: item.en, fr: item.fr });
  const ready = Boolean(values.en.trim() && values.fr.trim());

  return (
    <form
      className="space-y-2 rounded-lg border border-accent-500/50 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) onSave({ en: values.en.trim(), fr: values.fr.trim() });
      }}
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label="English">
          <input
            className={inputClass}
            placeholder={placeholders.en}
            value={values.en}
            onChange={(event) => setValues({ ...values, en: event.target.value })}
          />
        </Field>
        <Field label="French">
          <input
            className={inputClass}
            placeholder={placeholders.fr}
            value={values.fr}
            onChange={(event) => setValues({ ...values, fr: event.target.value })}
          />
        </Field>
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!ready || saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
      <ErrorNote error={error} />
    </form>
  );
}

function SupportingUpload({
  onPick,
  busy,
  error,
}: {
  onPick: (file: File) => void;
  busy: boolean;
  error: unknown;
}) {
  const fileInput = useRef<HTMLInputElement>(null);

  return (
    <div className="mb-3">
      <input
        ref={fileInput}
        type="file"
        accept=".pdf,.docx,.txt,.md,.zip"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onPick(file);
          event.target.value = "";
        }}
      />
      <Button variant="secondary" onClick={() => fileInput.current?.click()} disabled={busy}>
        {busy ? "Reading…" : "Add a document"}
      </Button>
      <p className="mt-2 text-xs text-ink-400">
        A PDF or Word file, your LinkedIn profile saved as PDF, or the full LinkedIn data-export ZIP
        (the richest import — Settings → Data Privacy → Get a copy of your data).
      </p>
      <ErrorNote error={error} />
    </div>
  );
}

const linkClass =
  "inline-flex min-h-9 items-center rounded-lg border border-ink-200 px-2.5 text-xs hover:bg-ink-50 sm:min-h-0 sm:py-1 dark:border-ink-700 dark:hover:bg-ink-800";

/**
 * One imported document, with the document itself behind it.
 *
 * The row used to be the only trace of a file you had uploaded: a name, a
 * status and a Remove button, with no way to check *which* résumé this was or
 * what the extractor was given. Both routes to it are same-origin, so Authelia
 * covers them exactly like the rest of the app.
 */
function SourceRow({
  source,
  onRemove,
  removing,
}: {
  source: ProfileSource;
  onRemove: () => void;
  removing: boolean;
}) {
  const [open, setOpen] = useState(false);
  const href = `/api/profile/sources/${source.id}/file`;

  return (
    <div className="rounded-lg border border-ink-200 dark:border-ink-800">
      <div className="flex flex-wrap items-center gap-3 px-3 py-2">
        <Badge tone="info">{SOURCE_LABELS[source.kind] ?? source.kind}</Badge>
        <span className="min-w-0 flex-1 truncate text-sm" title={source.label}>
          {source.label}
        </span>
        <Badge tone={source.status === "parsed" ? "good" : "bad"}>{source.status}</Badge>
        <span className="text-xs text-ink-400">
          {new Date(source.created_at).toLocaleString()}
        </span>
        {source.can_preview && (
          // The inline preview is a page-size document in a box; that is worth
          // having on a laptop and unreadable at 375px, where the same document
          // opens full-screen in the browser's own viewer instead. The wrapper
          // is what hides it: `hidden` on the button would lose to the
          // `inline-flex` every Button already carries.
          <span className="hidden sm:inline-flex">
            <Button size="sm" variant="ghost" onClick={() => setOpen(!open)}>
              {open ? "Hide" : "Preview"}
            </Button>
          </span>
        )}
        {source.file_name && (
          <a href={href} target="_blank" rel="noreferrer" className={linkClass}>
            {source.can_preview ? "Open ↗" : "Download"}
          </a>
        )}
        <Button variant="ghost" size="sm" onClick={onRemove} disabled={removing}>
          Remove
        </Button>
        {source.error && <p className="w-full text-xs text-red-600">{source.error}</p>}
      </div>
      {open && source.can_preview && (
        <iframe
          title={source.label}
          src={href}
          className="hidden h-[70vh] w-full rounded-b-lg border-t border-ink-200 bg-white sm:block dark:border-ink-800"
        />
      )}
    </div>
  );
}
