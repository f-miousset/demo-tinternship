import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import {
  Badge,
  BulletList,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  Modal,
  SectionTitle,
  Spinner,
  inputClass,
} from "../components/ui";
import { InlineMarkdown, Markdown } from "../components/Markdown";
import { AuditPanel } from "../components/AuditPanel";
import { ApplicationFollowUp } from "../components/FollowUp";
import { JobDetails } from "../components/jobs/JobDetails";
import { JobHeading } from "../components/jobs/JobHeading";
import { api } from "../lib/api";
import type {
  Application,
  ApplicationStatus,
  Artifact,
  Contact,
  ContactMessageResult,
  ContactPlan,
  ContactsResult,
  GenerateResult,
  InterviewPrep,
  InterviewPrepResult,
  PackageLanguage,
  RunPhase,
} from "../lib/types";
import { downloadDocuments } from "../lib/download";
import { isInterview, STATUS_LABEL } from "../lib/statuses";
import { useRunStream } from "../lib/useRunStream";

/** The one document every run writes. The résumé is the application. */
const RESUME_TAB = { key: "resume", label: "Tailored résumé" } as const;

/** The other half of the package, and the optional half: written only when the
 *  box in the Generate dialog is ticked, because most applications are a form
 *  with nowhere to attach a letter and that lane is the long, expensive one.
 *  Its tab appears when there is a letter, or while one is being written. */
const LETTER_TAB = { key: "cover_letter", label: "Cover letter" } as const;

/** The interview brief is a tab too, but not part of the package: it is written
 *  by a different run, triggered by reaching `interview` rather than by asking
 *  for documents, so it must not make the package tab bar appear on its own. */
const PREP_TAB = { key: "interview_prep", label: "Interview prep" } as const;

/** Who to write to about this posting. Like the brief it is not part of the
 *  package, and like every other run here it is started by hand: it costs a
 *  grounded search, and opening an application to re-read the posting is not
 *  the same as asking for one. */
const CONTACTS_TAB = { key: "contacts", label: "People to contact" } as const;

const LANGUAGES: { key: PackageLanguage; label: string; hint: string }[] = [
  { key: "en", label: "English", hint: "Fill in your English résumé and cover letter" },
  { key: "fr", label: "Français", hint: "Remplir votre CV et votre lettre de motivation en français" },
];

type TabKey =
  | typeof RESUME_TAB.key
  | typeof LETTER_TAB.key
  | typeof PREP_TAB.key
  | typeof CONTACTS_TAB.key;

export function ApplicationPage() {
  const { applicationId } = useParams();
  const id = Number(applicationId);
  const queryClient = useQueryClient();
  // Null until the artifacts load, so we can open on one that actually exists
  // rather than showing an empty tab.
  const [tab, setTab] = useState<TabKey | null>(null);
  // Null until the user picks, so the application's own last choice wins.
  const [chosenLanguage, setChosenLanguage] = useState<PackageLanguage | null>(null);
  // The personalisation dialog, which opens on the way to generating rather
  // than sitting on the page: the moment you have decided to apply is the one
  // moment you are actually thinking about who you know there. Its value is
  // *which run it is about* — the package, or the cover letter on its own —
  // because both buttons ask the same question before they start.
  const [personalising, setPersonalising] = useState<"package" | "letter" | null>(null);
  // Which documents the run in flight was asked for. The phase events cannot
  // say — a lane that is not running sends nothing — and without this the
  // progress card would leave a "waiting to start…" line under a document that
  // is never coming.
  const [writing, setWriting] = useState({ resume: false, coverLetter: false });
  // The one query parameter this page reads: `?generate=en|fr`, written by the
  // card a paste produces on the Jobs page. See the effect below.
  const [searchParams, setSearchParams] = useSearchParams();

  const { data: application, isLoading } = useQuery({
    queryKey: ["application", id],
    queryFn: () => api.get<Application>(`/api/applications/${id}`),
    enabled: Number.isFinite(id),
  });
  const { data: artifactData } = useQuery({
    queryKey: ["artifacts", id],
    queryFn: () => api.get<{ artifacts: Artifact[] }>(`/api/applications/${id}/artifacts`),
    enabled: Number.isFinite(id),
  });

  const language = chosenLanguage ?? application?.language ?? "en";

  const generate = useRunStream<GenerateResult>();
  // Pulled out because the hook hands back a fresh object every render while
  // `start` itself is stable, and `runGenerate` has to be stable enough to be a
  // dependency of the effect that reads `?generate=` below.
  const startGenerate = generate.start;
  const prep = useRunStream<InterviewPrepResult>();
  const contacts = useRunStream<ContactsResult>();

  const refresh = useCallback(() => {
    // Whatever happened. Each artifact is saved the moment it clears its gate,
    // so a run that failed on the cover letter still produced a résumé.
    queryClient.invalidateQueries({ queryKey: ["artifacts", id] });
    queryClient.invalidateQueries({ queryKey: ["application", id] });
    queryClient.invalidateQueries({ queryKey: ["applications"] });
  }, [queryClient, id]);

  /**
   * Start the Applying team.
   *
   * `personalisation` is `null` on the fast path from a pasted posting, which
   * the backend reads as "leave whatever is stored alone" — the dialog is how
   * that note is written, and a path whose whole point is not stopping cannot
   * stop to ask for one.
   *
   * `docs` is which documents to write. `{resume: true}` is the default
   * package; the letter joins it from the dialog's box; `{coverLetter: true}`
   * alone is *Add a cover letter*, which leaves the résumé already on the row
   * as it is rather than spending a run to produce it again.
   *
   * `chosen` is passed explicitly rather than read from `language` for the same
   * fast path: `setChosenLanguage` has not landed yet on the tick the URL is
   * read, and generating in the wrong language is two minutes and two files.
   *
   * **The documents download themselves when the run ends.** Every one of them
   * is on its way to a form or an attachment field, and the Download .docx link
   * on the tab was a step between the candidate and what they asked for. It
   * happens after the run, not per lane: the `result` event is the only one
   * carrying artifact ids.
   */
  const runGenerate = useCallback(
    async (
      personalisation: string | null,
      docs: { resume?: boolean; coverLetter?: boolean },
      chosen: PackageLanguage = language,
    ) => {
      const resume = docs.resume ?? false;
      const coverLetter = docs.coverLetter ?? false;
      setPersonalising(null);
      setWriting({ resume, coverLetter });
      setTab(resume ? "resume" : "cover_letter");
      // The backend moves a `saved` application to `preparing` as it starts, so
      // the Tracker column is right without the candidate maintaining it by hand.
      const result = await startGenerate(`/api/applications/${id}/generate`, {
        language: chosen,
        personalisation,
        resume,
        cover_letter: coverLetter,
      });
      refresh();
      await downloadDocuments(result?.artifacts);
    },
    [startGenerate, id, language, refresh],
  );

  async function runPrep() {
    setTab(PREP_TAB.key);
    await prep.start(`/api/applications/${id}/interview-prep`);
    refresh();
  }

  async function runContacts() {
    setTab(CONTACTS_TAB.key);
    await contacts.start(`/api/applications/${id}/contacts`);
    refresh();
  }

  const artifacts = artifactData?.artifacts ?? [];
  const latestByKind = new Map<string, Artifact>();
  for (const artifact of artifacts) {
    const existing = latestByKind.get(artifact.kind);
    if (!existing || artifact.version > existing.version) latestByKind.set(artifact.kind, artifact);
  }

  // The follow-up is an artifact of this application but not part of the
  // package, so it has no tab and must not make the tab bar appear: an
  // application that was only ever chased would otherwise render empty tabs
  // over "not produced in the last run".
  const followUp = latestByKind.get("follow_up");
  const packageCount = artifacts.filter(
    (artifact) => artifact.kind === "resume" || artifact.kind === "cover_letter",
  ).length;
  const hasPrep = latestByKind.has(PREP_TAB.key) || prep.running;
  const hasContacts = latestByKind.has(CONTACTS_TAB.key) || contacts.running;
  // The letter earns its tab the same way the brief and the shortlist do: it
  // exists, or it is being written right now. An application generated without
  // one shows no empty Cover letter tab — and one generated with a letter keeps
  // it after a résumé-only regeneration, because that letter is still on the
  // row at the version it reached.
  const hasLetter =
    latestByKind.has(LETTER_TAB.key) || (generate.running && writing.coverLetter);
  const tabs = [
    RESUME_TAB,
    ...(hasLetter ? [LETTER_TAB] : []),
    ...(hasContacts ? [CONTACTS_TAB] : []),
    ...(hasPrep ? [PREP_TAB] : []),
  ];

  const firstAvailable: TabKey =
    tabs.find((entry) => latestByKind.has(entry.key))?.key ?? (hasPrep ? PREP_TAB.key : "resume");
  const activeTab = tab && tabs.some((entry) => entry.key === tab) ? tab : firstAvailable;
  const current = latestByKind.get(activeTab);

  /**
   * The fast path in from a pasted posting.
   *
   * A paste answers every question this page would have asked. Whether the
   * posting is worth applying to: the candidate went and fetched it. Which
   * language to write in: the one the posting is written in, measured off it in
   * Python and already stored on the application. So `?generate=auto` on the
   * URL means *start*, and the page opens on the progress rather than on an
   * empty tab and a button. It starts the résumé alone — the cover letter is a
   * box you tick, and a path whose whole point is not asking cannot tick it.
   *
   * `auto` takes the application's own language — the guess — while `en` and
   * `fr` name one explicitly. The explicit form stays because a link that says
   * what it will do is worth keeping and costs one branch; the paste uses
   * `auto`, so the guess has exactly one home rather than being re-derived in
   * the browser from a posting the browser would have to fetch.
   *
   * Two guards, and both matter. The parameter is stripped the moment it is
   * read, so a reload or a back-button is a reload and not a second two-minute
   * run over the same posting; and the ref makes it once per mount whatever the
   * effect's dependencies do, since `language` and `searchParams` both change as
   * a direct result of what happens inside it.
   *
   * Anything that makes the run impossible — a base document missing, a page
   * with no room left on it — is a 409 before the stream opens, and it lands in
   * the same `ErrorNote` a button would have put it in.
   */
  const autoStarted = useRef(false);
  useEffect(() => {
    if (autoStarted.current || !application) return;
    const asked = searchParams.get("generate");
    if (asked !== "en" && asked !== "fr" && asked !== "auto") return;
    autoStarted.current = true;
    setSearchParams({}, { replace: true });
    // `language` is already the application's own by now — the effect waits for
    // the application to load — so `auto` needs nothing set and nothing fetched.
    if (asked !== "auto") setChosenLanguage(asked);
    void runGenerate(null, { resume: true }, asked === "auto" ? language : asked);
  }, [application, searchParams, setSearchParams, runGenerate, language]);

  /** Fired after a status change lands. Reaching any interview round starts the brief. */
  function onStatusChanged(status: ApplicationStatus) {
    if (!isInterview(status)) return;
    // Only the first time, whichever round that is — a process may have no HR
    // interview at all, so the brief cannot wait for a particular one, and
    // moving on from the pre-call to the manager interview must not write a
    // second. A later round is worth its own version, but that is a decision —
    // and a grounded research run — the candidate asks for.
    if (latestByKind.has(PREP_TAB.key) || prep.running) return;
    void runPrep();
  }

  if (isLoading) return <Spinner label="Loading application…" />;
  if (!application) return <EmptyState title="Application not found" />;

  const job = application.job;

  return (
    <div className="space-y-5">
      {/* First thing on the page, because everything under it still works: a
          trashed application generates, streams and edits exactly as it did,
          and without this line there is nothing to say why the Tracker no
          longer shows it. */}
      {application.trashed_at && <TrashedBanner application={application} />}

      {/* Who this is with and what the role is — the same two lines, in the
          same order and at the same weight, as the deck card you swiped right
          on. This page used to open on the job title in small grey type, which
          made deciding to apply the moment the app stopped showing you what you
          were applying to. */}
      <Card className="space-y-4">
        {job ? (
          <JobHeading job={job} />
        ) : (
          <SectionTitle
            title="Application"
            subtitle="The posting behind this application is no longer in the database."
          />
        )}

        <div className="flex flex-wrap items-center gap-2">
          {job?.apply_url && (
            <a
              href={job.apply_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-11 items-center rounded-lg border border-ink-200 px-3 text-sm hover:bg-ink-50 sm:min-h-0 sm:py-2 dark:border-ink-700 dark:hover:bg-ink-800"
            >
              Open posting ↗
            </a>
          )}
          <LanguagePicker
            value={language}
            onChange={setChosenLanguage}
            disabled={generate.running}
          />
          <Button
            className="w-full sm:w-auto"
            onClick={() => setPersonalising("package")}
            disabled={generate.running}
          >
            {generate.running
              ? "Generating…"
              : packageCount
                ? "Regenerate package"
                : "Generate application package"}
          </Button>
          {/* The way back to a letter you did not ask for the first time. It
              writes the letter *only*: the résumé on the row is the one that was
              reviewed and downloaded, and rewriting it to get a letter beside it
              would spend a whole run on a document that already exists. Gone
              once there is a letter — from then on the package button
              regenerates both, with its box already ticked. */}
          {latestByKind.has(RESUME_TAB.key) && !latestByKind.has(LETTER_TAB.key) && (
            <Button
              variant="secondary"
              className="w-full sm:w-auto"
              onClick={() => setPersonalising("letter")}
              disabled={generate.running}
              title="Writes the cover letter for this posting and leaves your résumé exactly as it is"
            >
              Add a cover letter
            </Button>
          )}
          {/* Only until there is a shortlist. After that the tab's own "Look
              again" is the way to re-run it, and two buttons meaning the same
              thing in two places is worse than one in the right place. */}
          {!hasContacts && job && (
            <Button
              variant="secondary"
              className="w-full sm:w-auto"
              onClick={() => void runContacts()}
              disabled={contacts.running}
              title="Recruiters, whoever runs their internships, the team, and anyone there who went to your school — with every link checked"
            >
              Find people to contact
            </Button>
          )}
        </div>
      </Card>

      <PersonaliseDialog
        open={personalising !== null}
        letterOnly={personalising === "letter"}
        initial={application.personalisation}
        company={job?.company ?? "this employer"}
        // Ticked to start with only when this application already has a letter:
        // regenerating must not quietly drop a document that is on the page,
        // and for every other application the answer is the honest default.
        initialCoverLetter={latestByKind.has(LETTER_TAB.key)}
        onCancel={() => setPersonalising(null)}
        onGenerate={(value, coverLetter) =>
          void runGenerate(
            value,
            personalising === "letter" ? { coverLetter: true } : { resume: true, coverLetter },
          )
        }
      />

      <ErrorNote error={generate.error} />
      <TrackProgress
        phases={generate.phases}
        running={generate.running}
        writing={writing}
        language={LANGUAGES.find((entry) => entry.key === language)?.label ?? language}
      />

      <ErrorNote error={prep.error} />
      <PrepProgress phases={prep.phases} running={prep.running} />

      <ErrorNote error={contacts.error} />
      <ContactsProgress phases={contacts.phases} running={contacts.running} />

      <StatusBar application={application} onStatusChanged={onStatusChanged} />

      <NotesCard application={application} />

      <ApplicationFollowUp application={application} artifact={followUp} />

      {/* Everything the deck card and its details sheet showed, rendered by the
          same component. Open by default — this is the posting, not an
          appendix — but collapsible, because on a phone it is a long read and
          the tabs below it are what you came back for. */}
      {job && (
        <Card>
          <details open>
            <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-wide text-ink-500">
              The posting
            </summary>
            <div className="mt-3">
              <JobDetails job={job} heading={false} />
            </div>
          </details>
        </Card>
      )}

      {packageCount === 0 && !generate.running && !hasPrep && !hasContacts && (
        <EmptyState
          title="Nothing generated yet"
          hint="Pick a language, then generate: the Résumé agent fills in the blanks of the CV you uploaded — nothing else on the page is touched — behind a quality gate that sends weak output back for one revision. Tick the box in the dialog to have the Cover Letter agent write a letter too; it runs in parallel, behind a gate of its own."
        />
      )}

      {(packageCount > 0 || hasPrep || hasContacts) && (
        <>
          <div className="flex flex-wrap gap-1">
            {tabs.map((entry) => {
              const artifact = latestByKind.get(entry.key);
              return (
                <button
                  key={entry.key}
                  onClick={() => setTab(entry.key)}
                  className={`flex min-h-10 items-center gap-2 rounded-lg px-3 text-sm font-medium transition sm:min-h-0 sm:py-1.5 ${
                    activeTab === entry.key
                      ? "bg-ink-900 text-white dark:bg-ink-100 dark:text-ink-900"
                      : "text-ink-600 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-ink-800"
                  } ${artifact ? "" : "opacity-50"}`}
                >
                  {entry.label}
                  {artifact?.audit && (
                    <span className="opacity-70">{artifact.audit.overall.toFixed(1)}</span>
                  )}
                </button>
              );
            })}
          </div>

          {current ? (
            <ArtifactView
              artifact={current}
              applicationId={id}
              onRerun={
                activeTab === PREP_TAB.key
                  ? () => void runPrep()
                  : activeTab === CONTACTS_TAB.key
                    ? () => void runContacts()
                    : undefined
              }
              rerunning={activeTab === PREP_TAB.key ? prep.running : contacts.running}
              rerunLabel={activeTab === PREP_TAB.key ? "Prepare again" : "Look again"}
              rerunBusyLabel={activeTab === PREP_TAB.key ? "Researching…" : "Looking…"}
            />
          ) : activeTab === PREP_TAB.key ? (
            <EmptyState
              title="Researching the employer…"
              hint="The brief is saved the moment it clears the Critic."
            />
          ) : activeTab === CONTACTS_TAB.key ? (
            <EmptyState
              title="Looking for people to write to…"
              hint="Every link is opened before you see it, so none of them wastes your time."
            />
          ) : (
            <EmptyState title="This artifact was not produced in the last run." />
          )}
        </>
      )}
    </div>
  );
}

/**
 * Asked once, on the way to generating: what do you know that the posting does
 * not — and do you want a cover letter with this?
 *
 * A dialog rather than fields on the page, because both answers are only in
 * mind at one moment — when you have just decided to apply — and a permanently
 * visible empty box is a permanently ignored one. What is typed here reaches
 * the Résumé and Cover Letter agents as privileged information: the research
 * cannot find that you met their lead engineer at a careers fair, and it is
 * usually the most useful sentence in the whole prompt.
 *
 * The note is stored on the application, so the next regeneration starts from
 * what you wrote last time rather than a blank box. The letter box is not
 * stored: it is a question about *this* run, and it starts ticked only when the
 * application already has a letter to keep.
 */
function PersonaliseDialog({
  open,
  letterOnly,
  initial,
  initialCoverLetter,
  company,
  onCancel,
  onGenerate,
}: {
  open: boolean;
  letterOnly: boolean;
  initial: string;
  initialCoverLetter: boolean;
  company: string;
  onCancel: () => void;
  onGenerate: (personalisation: string, coverLetter: boolean) => void;
}) {
  const [value, setValue] = useState(initial);
  const [coverLetter, setCoverLetter] = useState(initialCoverLetter);
  // The stored note arrives after the dialog component first mounts, and a
  // second application opened in the same session would otherwise show the
  // first one's note.
  const lastInitial = useRef(initial);
  if (lastInitial.current !== initial) {
    lastInitial.current = initial;
    setValue(initial);
  }
  // Same for the box: it follows the application, not the component.
  const lastCoverLetter = useRef(initialCoverLetter);
  if (lastCoverLetter.current !== initialCoverLetter) {
    lastCoverLetter.current = initialCoverLetter;
    setCoverLetter(initialCoverLetter);
  }

  return (
    <Modal open={open} onClose={onCancel} title="Anything they should know?">
      <div className="space-y-3">
        <p className="text-sm text-ink-600 dark:text-ink-300">
          Before {letterOnly ? "the letter is written" : "the agents write"}, tell them what you
          know about {company} that the posting does not say. Someone you know on the team, a
          conversation at a careers fair, a project of theirs you have actually used, an angle
          you want taken.
        </p>
        <textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          rows={5}
          autoFocus
          aria-label="What you know about this employer"
          placeholder="e.g. I met Claire Dupont, their data lead, at the Forum INSA in March — she suggested I mention the ingest pipeline work."
          className={`${inputClass} min-h-32 resize-y`}
        />
        <p className="text-xs text-ink-500">
          It goes to the agents as something they may rely on but not embellish — a conversation
          stays a conversation, never a referral. It is kept with the application, so regenerating
          later starts from what you wrote here.
        </p>
        {letterOnly ? (
          <p className="rounded-lg border border-ink-200 px-3 py-3 sm:py-2.5 dark:border-ink-800">
            <span className="block text-sm font-medium">Writing the cover letter only</span>
            <span className="block text-xs text-ink-500 dark:text-ink-400">
              The résumé already on this application is left exactly as it is — same file, same
              version, same audit. The employer&rsquo;s postal address is looked up while the
              letter is written.
            </span>
          </p>
        ) : (
          <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-ink-200 px-3 py-3 transition hover:bg-ink-50 sm:py-2.5 dark:border-ink-800 dark:hover:bg-ink-800/50">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0"
              checked={coverLetter}
              onChange={(event) => setCoverLetter(event.target.checked)}
            />
            <span className="min-w-0">
              <span className="block text-sm font-medium">Write a cover letter too</span>
              <span className="block text-xs text-ink-500 dark:text-ink-400">
                Off by default: most forms have nowhere to attach one, and the letter is the long
                half of the run — the employer&rsquo;s postal address is searched for, the letter
                is written, rewritten so it does not read as generated, then reviewed. Your résumé
                is filled in either way.
              </span>
            </span>
          </label>
        )}
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={() => onGenerate(value.trim(), letterOnly || coverLetter)}>
            {letterOnly
              ? "Write the cover letter"
              : coverLetter
                ? "Generate both"
                : "Generate résumé"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/**
 * The interview brief's run, which is one lane but a long one.
 *
 * The research stage is where most of the wall-clock goes — grounded searches
 * against the open web — so it gets its own line rather than being folded into
 * "working…". Same vocabulary as the package's lanes, rendered the same way.
 */
function PrepProgress({ phases, running }: { phases: RunPhase[]; running: boolean }) {
  if (!running && phases.length === 0) return null;
  const latest = phases[phases.length - 1];

  return (
    <Card className="space-y-2">
      <p className="text-sm text-ink-500 dark:text-ink-400">
        The Interview Coach is researching this employer and writing your brief — everything it
        says about the company has to come with a link you can open.
      </p>
      <div className="flex items-start gap-2 text-sm">
        {running ? (
          <Spinner />
        ) : (
          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
        )}
        <span className="min-w-0 flex-1">{latest?.message ?? "starting…"}</span>
      </div>
    </Card>
  );
}

/**
 * The contact search's run.
 *
 * It starts by itself when the page opens, which makes this line the only thing
 * telling the candidate why the app is busy — so it says what it is doing and,
 * more importantly, what it is doing it for. The `links` stage is worth naming:
 * it is the one that fetches every profile the research produced, and it is the
 * whole reason the shortlist can be trusted.
 */
function ContactsProgress({ phases, running }: { phases: RunPhase[]; running: boolean }) {
  if (!running && phases.length === 0) return null;
  const latest = phases[phases.length - 1];

  return (
    <Card className="space-y-2">
      <p className="text-sm text-ink-500 dark:text-ink-400">
        Looking for people worth writing to about this posting — recruiters, whoever runs their
        internships, the team, and anyone who went to your school. Every link is opened before you
        see it.
      </p>
      <div className="flex items-start gap-2 text-sm">
        {running ? (
          <Spinner />
        ) : (
          <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
        )}
        <span className="min-w-0 flex-1">{latest?.message ?? "starting…"}</span>
      </div>
    </Card>
  );
}

/**
 * The run, as a lane per document rather than one log.
 *
 * With both documents there are two lanes, produced in parallel, each going
 * round its own produce → critique → gate loop, so their progress events
 * interleave. Showing the latest line per artifact is the only reading of them
 * that is not misleading: a chronological list looks like one thing happening
 * at a time.
 *
 * `writing` is what the run was *asked* for, not what has reported in. A lane
 * that was never started emits no events at all, so without it a document would
 * sit at "waiting to start…" for a run that has already finished.
 */
function TrackProgress({
  phases,
  running,
  writing,
  language,
}: {
  phases: RunPhase[];
  running: boolean;
  writing: { resume: boolean; coverLetter: boolean };
  language: string;
}) {
  if (!running && phases.length === 0) return null;

  const latest = new Map<string, RunPhase>();
  for (const phase of phases) {
    if (phase.track) latest.set(phase.track, phase);
  }
  const lanes = [
    ...(writing.resume ? [RESUME_TAB] : []),
    ...(writing.coverLetter ? [LETTER_TAB] : []),
  ];

  return (
    <Card className="space-y-3">
      <p className="text-sm text-ink-500 dark:text-ink-400">
        {writing.resume && writing.coverLetter
          ? `Two agents are working in parallel — the résumé and the cover letter, in ${language} — each reviewed by the Critic before you see it.`
          : writing.resume
            ? `The Résumé agent is filling in your CV, in ${language}, and the Critic reviews it before you see it.`
            : `The Cover Letter agent is looking up the employer and filling in your letter, in ${language}. Your résumé is left exactly as it is.`}{" "}
        Each is saved the moment it clears its gate, and downloads itself when the run ends.
      </p>
      <ul className="space-y-1.5">
        {lanes.map((entry) => {
          const phase = latest.get(entry.key);
          const done = phase?.phase === "saved";
          return (
            <li key={entry.key} className="flex items-start gap-2 text-sm">
              {running && !done ? (
                <Spinner />
              ) : (
                <span
                  className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                    done ? "bg-emerald-500" : "bg-ink-300 dark:bg-ink-600"
                  }`}
                />
              )}
              {/* Lane name over its line on a phone: side by side, the message
                  gets a column three words wide. */}
              <span className="flex min-w-0 flex-1 flex-col sm:flex-row sm:gap-2">
                <span className="shrink-0 text-ink-500 sm:w-36 dark:text-ink-400">
                  {entry.label}
                </span>
                <span className="min-w-0 flex-1">{phase?.message ?? "waiting to start…"}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/**
 * Chosen before generating, because it is not a formatting toggle — it changes
 * what the three agents write, so it cannot be applied to output after the fact.
 */
function LanguagePicker({
  value,
  onChange,
  disabled,
}: {
  value: PackageLanguage;
  onChange: (language: PackageLanguage) => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Language of the generated package"
      className="flex items-center gap-1 rounded-lg border border-ink-200 p-0.5 dark:border-ink-700"
    >
      {LANGUAGES.map((option) => (
        <button
          key={option.key}
          role="radio"
          aria-checked={value === option.key}
          title={option.hint}
          disabled={disabled}
          onClick={() => onChange(option.key)}
          className={`min-h-10 rounded-md px-3 text-sm font-medium transition disabled:opacity-50 sm:min-h-0 sm:px-2.5 sm:py-1.5 ${
            value === option.key
              ? "bg-ink-900 text-white dark:bg-ink-100 dark:text-ink-900"
              : "text-ink-600 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-ink-800"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/**
 * The line an application in the Tracker's trash wears.
 *
 * It says the two things the page cannot say for itself: that this is why the
 * board no longer shows it, and that nothing was lost. Everything below is
 * still live — the status, the timeline, the notes, and every document ever
 * generated — which is the whole difference between this and a delete.
 */
function TrashedBanner({ application }: { application: Application }) {
  const queryClient = useQueryClient();
  const restore = useMutation({
    mutationFn: () => api.post(`/api/applications/${application.id}/trash?trashed=false`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["application", application.id] });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
    },
  });

  return (
    <Card className="flex flex-col gap-3 border-amber-300 sm:flex-row sm:items-center sm:justify-between dark:border-amber-800">
      <div className="min-w-0">
        <p className="text-sm font-medium">This application is in the trash</p>
        <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">
          Thrown away
          {application.trashed_at
            ? ` on ${new Date(application.trashed_at).toLocaleDateString()}`
            : ""}
          , so it is off the board and no Investigator run will propose the posting again. Nothing
          was deleted, and putting it back returns it to the “{application.status}” column.
        </p>
      </div>
      <Button
        variant="secondary"
        className="sm:shrink-0"
        onClick={() => restore.mutate()}
        disabled={restore.isPending}
      >
        Put back on the board
      </Button>
    </Card>
  );
}

function StatusBar({
  application,
  onStatusChanged,
}: {
  application: Application;
  onStatusChanged: (status: ApplicationStatus) => void;
}) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");

  // Its own mutation rather than a field on the PATCH: trashing writes no
  // `ApplicationEvent`, and `updated_at` is left alone. See the endpoint.
  const trash = useMutation({
    mutationFn: (trashed: boolean) =>
      api.post(`/api/applications/${application.id}/trash?trashed=${trashed}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["application", application.id] });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
    },
  });

  const update = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api.patch(`/api/applications/${application.id}`, body),
    onSuccess: (_data, body) => {
      setNote("");
      queryClient.invalidateQueries({ queryKey: ["application", application.id] });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
      const status = (body as { status?: ApplicationStatus }).status;
      // Reaching the first interview round is the one transition that starts a
      // run: the Interview Coach researches the employer and writes the brief.
      // Fired after the PATCH lands, so the agent reads a timeline that already
      // records the interview.
      if (status && status !== application.status) onStatusChanged(status);
    },
  });

  // `screening` was removed on 2026-08-28: it described the employer's internal
  // state, so it was a column that either sat empty or held applications nobody
  // could honestly place. `interview` became four rounds on 2026-10-05.
  // `withdrawn` has never been one of these buttons.
  const statuses = (Object.keys(STATUS_LABEL) as ApplicationStatus[]).filter(
    (status) => status !== "withdrawn",
  );

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-ink-500">Status</span>
        {statuses.map((status) => (
          <button
            key={status}
            onClick={() => update.mutate({ status, note })}
            className={`min-h-9 rounded-full px-3 text-xs font-medium transition sm:min-h-0 sm:px-2.5 sm:py-1 ${
              application.status === status
                ? "bg-accent-600 text-white"
                : "bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-ink-800 dark:text-ink-300"
            }`}
          >
            {STATUS_LABEL[status]}
          </button>
        ))}
        {/* The pin lives beside the status because it is the other thing you
            can say about where this application sits — one moves it across the
            board, the other moves it to the top of wherever it landed. */}
        <button
          onClick={() => update.mutate({ pinned: !application.pinned })}
          title={
            application.pinned
              ? "Pinned — first in its Tracker column. Click to unpin."
              : "Pin it to the top of its Tracker column"
          }
          aria-pressed={application.pinned}
          className={`ml-auto min-h-9 rounded-full px-3 text-xs font-medium transition sm:min-h-0 sm:px-2.5 sm:py-1 ${
            application.pinned
              ? "brand-gradient text-white"
              : "bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-ink-800 dark:text-ink-300"
          }`}
        >
          {application.pinned ? "★ pinned" : "☆ pin"}
        </button>
      </div>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="What happened? This note feeds the Investigator's next search."
          className={inputClass}
        />
        <Button
          variant="secondary"
          className="sm:shrink-0"
          onClick={() => update.mutate({ note })}
          disabled={!note.trim() || update.isPending}
        >
          Add note
        </Button>
      </div>
      {/* Giving up on an application lives here rather than on a Tracker card,
          and that is deliberate. A deck swipe is triage — four seconds on a
          posting you have never seen, so it has to be a gesture. This is the
          opposite: by the time you throw one of these away you have a status,
          a timeline and possibly two generated documents, and the decision is
          worth the tap it takes to open the thing you are deciding about. It
          also keeps a destructive-looking control off a board of small cards
          you scroll with a thumb. */}
      {!application.trashed_at && (
        <div className="flex justify-end">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => trash.mutate(true)}
            disabled={trash.isPending}
            title="Move it to the Tracker's trash. Nothing is deleted — the status, this timeline, your notes and every generated document stay on the row, and you can put it back."
          >
            Move to trash
          </Button>
        </div>
      )}
      {application.timeline && application.timeline.length > 0 && (
        <ol className="space-y-1 text-xs text-ink-500 dark:text-ink-400">
          {application.timeline.map((entry, index) => (
            <li key={index}>
              {new Date(entry.at).toLocaleString()} · {entry.from || "—"} → {entry.to}
              {entry.note && <span className="text-ink-700 dark:text-ink-300"> · {entry.note}</span>}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

/**
 * Everything you know about this application that nothing else records.
 *
 * Separate from the note beside the status buttons, and the difference is what
 * each one is for. A timeline note is an **event** — "recruiter called", "took
 * the technical test" — stamped with when it happened and never edited again;
 * it is what the Feedback Analyst reads to work out what actually moves an
 * application. This is the **standing** note: the salary they mentioned, the
 * name of the person on the phone, the three questions to ask, what you decided
 * about the commute. It is one field you keep rewriting, and until 2026-09-03
 * the column existed in the database and the app gave you nowhere to type it.
 *
 * It is not private in the sense of hidden — `services/follow_up.py` and the
 * feedback digest both read it — but it never leaves the app inside anything an
 * employer receives. `services/context_blocks.py` says so to every agent that
 * gets it.
 */
function NotesCard({ application }: { application: Application }) {
  const queryClient = useQueryClient();
  // Seeded once, then owned by the textarea. Re-syncing it from the query would
  // throw away what you are in the middle of typing every time something else
  // on the page refetches.
  const [draft, setDraft] = useState(application.notes ?? "");
  const textarea = useRef<HTMLTextAreaElement>(null);

  // Auto-resize the field to its content instead of scrolling inside a fixed box.
  // CSS field-sizing provides native auto-sizing where supported, while the
  // layout effect ensures consistent sizing across all engines (including
  // mobile Safari) and recomputes on input or window resize.
  useLayoutEffect(() => {
    const field = textarea.current;
    if (!field) return;

    const resize = () => {
      field.style.height = "auto";
      if (!field.scrollHeight) return;
      const border = field.offsetHeight - field.clientHeight;
      field.style.height = `${field.scrollHeight + border}px`;
    };

    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [draft]);

  const save = useMutation({
    mutationFn: (notes: string) => api.patch(`/api/applications/${application.id}`, { notes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["application", application.id] });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
    },
  });

  const stored = application.notes ?? "";
  const dirty = draft !== stored;

  return (
    <Card className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium">Your notes</h3>
        <p className="text-xs text-ink-500 dark:text-ink-400">
          Kept and edited — the note beside the status buttons is the timeline, this is what you
          know.
        </p>
      </div>
      <textarea
        ref={textarea}
        rows={4}
        // The heading above says it, but a heading is not a label: without this
        // a screen reader announces an unnamed multi-line field.
        aria-label="Your notes"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder="The salary they mentioned, who you spoke to, what to ask next time, why you want this one."
        className={`${inputClass} min-h-24 resize-none overflow-hidden [field-sizing:content]`}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          onClick={() => save.mutate(draft)}
          disabled={!dirty || save.isPending}
        >
          {save.isPending ? "Saving…" : "Save notes"}
        </Button>
        {dirty && !save.isPending && (
          <span className="text-xs text-amber-600 dark:text-amber-400">unsaved</span>
        )}
        {!dirty && stored && !save.isPending && (
          <span className="text-xs text-ink-500">saved</span>
        )}
      </div>
      <ErrorNote error={save.error} />
    </Card>
  );
}

/**
 * One control on a document's toolbar row.
 *
 * Two of the three are links and one is a button, and they have to read as one
 * row of things you can do with this document rather than as two kinds of
 * thing — so the class lives here rather than being typed out per control.
 */
const DOCUMENT_CHIP =
  "inline-flex min-h-9 items-center rounded-lg border border-ink-200 px-2.5 text-xs hover:bg-ink-50 sm:min-h-0 sm:py-1 dark:border-ink-700 dark:hover:bg-ink-800";

function ArtifactView({
  artifact,
  applicationId,
  onRerun,
  rerunning,
  rerunLabel = "Run again",
  rerunBusyLabel = "Working…",
}: {
  artifact: Artifact;
  applicationId: number;
  /** Present for the two researched artifacts — the brief and the shortlist —
   *  which are the ones worth producing a second time months later. */
  onRerun?: () => void;
  rerunning?: boolean;
  rerunLabel?: string;
  rerunBusyLabel?: string;
}) {
  const queryClient = useQueryClient();

  const reaudit = useMutation({
    mutationFn: () => api.post<any>(`/api/applications/artifacts/${artifact.id}/reaudit`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["artifacts", applicationId] }),
  });

  // Only these two become a file an employer receives. The interview brief is
  // read in the app, so it has no document layout and nothing to download.
  const isDocument = artifact.kind === "resume" || artifact.kind === "cover_letter";
  // A filled document's download is the candidate's own .docx with its blanks
  // completed; the preview is its text with those lines marked. Saying so
  // matters, because the preview deliberately does not reproduce their layout.
  // True for a résumé since 2026-08-28 and a cover letter since 2026-09-09;
  // false for anything generated before, which was laid out by a renderer.
  const isFilled = isDocument && Array.isArray(artifact.content?.blocks);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge>v{artifact.version}</Badge>
        {artifact.revisions > 0 && (
          <Badge tone="warn" title="The Critic sent this back for revision before you saw it">
            {artifact.revisions} auto-revision(s)
          </Badge>
        )}
        {isDocument && (
          <>
            <a
              href={`/api/applications/artifacts/${artifact.id}/export`}
              className={DOCUMENT_CHIP}
            >
              Download .docx
            </a>
            <a
              href={`/api/applications/artifacts/${artifact.id}/preview`}
              target="_blank"
              rel="noreferrer"
              className={DOCUMENT_CHIP}
            >
              Full size ↗
            </a>
          </>
        )}
        {artifact.kind === "cover_letter" && <CopyLetterButton artifactId={artifact.id} />}
        {onRerun && (
          <Button size="sm" variant="secondary" onClick={onRerun} disabled={rerunning}>
            {rerunning ? rerunBusyLabel : rerunLabel}
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => reaudit.mutate()} disabled={reaudit.isPending}>
          {reaudit.isPending ? "Re-auditing…" : "Re-audit"}
        </Button>
        {artifact.run_id && (
          <Link to={`/traces/${artifact.run_id}`} className="text-xs text-accent-600 underline">
            trace
          </Link>
        )}
      </div>

      <ErrorNote error={reaudit.error} />

      <AuditPanel audit={artifact.audit} />

      {artifact.kind === "interview_prep" && <InterviewPrepView content={artifact.content} />}
      {artifact.kind === "contacts" && (
        <ContactsView content={artifact.content} applicationId={applicationId} />
      )}
      {isFilled && (
        <p className="text-xs text-ink-500 dark:text-ink-400">
          Your own Word {artifact.kind === "resume" ? "CV" : "cover letter"} with its{" "}
          <strong>{(artifact.content?.fills ?? []).length} blank(s)</strong> filled in for this
          posting. Below is its text with those lines highlighted — every other character is
          yours, and the download keeps your layout, fonts and spacing exactly as you made them.
        </p>
      )}
      {isDocument && (
        <DocumentPreview
          src={`/api/applications/artifacts/${artifact.id}/preview`}
          title={`${artifact.kind} preview`}
        />
      )}
      {artifact.kind === "resume" && <ResumeInsights content={artifact.content} />}
    </div>
  );
}

/**
 * The finished letter, on the clipboard — because half of applying is a textarea.
 *
 * Plenty of application forms have no attachment field for a letter: they have
 * a "motivation" box you paste into. Neither of the two controls beside this
 * one serves that. The download is a file, and the preview is a same-origin
 * iframe scaled down to fit the screen, so there is nothing on the page to
 * select. What lands on the clipboard is the actual content of the letter —
 * starting from the salutation ("Cher Monsieur, ...", "Dear Recruiter",
 * "Madame, Monsieur,") until the sign-off goodbye ("Sincerely...",
 * "Dans cette perspective, veuillez agréer..."), with the candidate's name
 * appended at the end. Header blocks (letterhead, date, recipient address,
 * subject line) are omitted so the text can be pasted straight into a form.
 *
 * **The text is fetched when the tab opens, not when the button is pressed.**
 * Safari refuses a `writeText` issued after an `await`: by then the tap that
 * allowed it has expired, and the copy fails on the one browser this app is
 * installed to a home screen on. Holding the text means the call that copies
 * happens in the same tick as the click.
 */
function CopyLetterButton({ artifactId }: { artifactId: number }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const { data: text } = useQuery({
    queryKey: ["artifact-text", artifactId],
    queryFn: () => api.getText(`/api/applications/artifacts/${artifactId}/text`),
    // An artifact row never changes: regenerating writes a new version with a
    // new id, and a re-audit scores what is there rather than rewriting it. So
    // switching tabs back and forth costs one fetch, not one per visit.
    staleTime: Infinity,
  });

  async function copy() {
    try {
      // Nothing may be awaited above this line: this call has to be the first
      // thing the click does, or Safari has already forgotten the gesture.
      await navigator.clipboard.writeText(text ?? "");
      setState("copied");
      window.setTimeout(() => setState("idle"), 2000);
    } catch {
      // An insecure origin, or a permission denied. Say so: unlike the other
      // copy buttons in this app there is no text on screen to fall back to,
      // so "nothing happened" would be the whole message.
      setState("failed");
    }
  }

  return (
    <button
      type="button"
      disabled={!text}
      title="Copy the letter's content, from salutation to sign-off with your name, for a form that wants it pasted rather than attached"
      onClick={() => void copy()}
      className={`${DOCUMENT_CHIP} disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {state === "copied" ? "Copied" : state === "failed" ? "Clipboard refused" : "Copy text"}
    </button>
  );
}


/** US Letter at 96dpi — the page these previews are laid out on. */
const PAGE_WIDTH = 816;
const PAGE_HEIGHT = 1056;

/**
 * The document preview, at true proportions, scaled to whatever width there is.
 *
 * A page laid out in inches cannot reflow to a 360px screen, and should not: it
 * stands in for the artifact an employer will read, and a version of it that
 * fits the phone would be a different document. It is laid out at full width
 * and scaled down whole, the way a phone shows a PDF. On a laptop the width is
 * already there and nothing is scaled at all.
 *
 * For a tailored résumé this is a *reading* of the document, not a facsimile:
 * the .docx that gets downloaded carries the candidate's own formatting, which
 * no HTML rendering would reproduce honestly. The caller says so above it.
 */
function DocumentPreview({ src, title }: { src: string; title: string }) {
  const box = useRef<HTMLDivElement>(null);
  // 0 until measured. useLayoutEffect measures before the browser paints, so
  // the unscaled first frame is never shown.
  const [width, setWidth] = useState(0);
  const [height, setHeight] = useState(PAGE_HEIGHT);

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth);
    measure();
    // The only thing that changes this width is the window: rotating the phone,
    // or dragging a laptop window narrower.
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const scale = width ? Math.min(1, width / PAGE_WIDTH) : 1;

  return (
    <div
      ref={box}
      className="overflow-hidden squircle rounded-card border border-ink-200 bg-white shadow-sm dark:border-ink-800"
      style={{ height: height * scale }}
    >
      <iframe
        title={title}
        src={src}
        // Same origin, so the letter's real length is readable and a two-page
        // one is shown in full rather than cut at the fold.
        onLoad={(event) => {
          const document_ = event.currentTarget.contentDocument;
          if (document_) {
            setHeight(Math.max(PAGE_HEIGHT, document_.documentElement.scrollHeight));
          }
        }}
        style={{
          width: PAGE_WIDTH,
          height,
          transform: `scale(${scale})`,
          transformOrigin: "top left",
        }}
        className="bg-white"
      />
    </div>
  );
}

/**
 * The interview brief, laid out in the order it is actually used.
 *
 * The pitch first, because "tell me about yourself" is the first question and
 * the one worth having ready word-for-word-ish. Then what to lead with, then
 * the gaps — the two halves of the same honest account of the candidate. The
 * questions come next because they are the longest read, and the sources last
 * because they are what you check afterwards rather than before.
 *
 * Every claim about the employer is supposed to be behind one of those links.
 * If `sources` is empty the page says so rather than staying quiet: the backend
 * gate should have caught it, and a brief with no sources is one to re-run
 * rather than repeat out loud.
 */
function InterviewPrepView({ content }: { content: Record<string, any> }) {
  const prep = content as Partial<InterviewPrep>;
  const gaps = prep.gaps ?? [];
  const questions = prep.likely_questions ?? [];
  const sources = (prep.sources ?? []).filter((source) => source?.url);

  return (
    <div className="space-y-4">
      {prep.pitch && (
        <Card>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
            “Tell me about yourself”
          </h4>
          <Markdown className="text-sm">{prep.pitch}</Markdown>
        </Card>
      )}

      {(prep.company_brief || (prep.recent_developments ?? []).length > 0) && (
        <Card>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
            The employer
          </h4>
          {prep.company_brief && <Markdown className="text-sm">{prep.company_brief}</Markdown>}
          {(prep.recent_developments ?? []).length > 0 && (
            <>
              <h4 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-ink-500">
                Recent
              </h4>
              <BulletList items={prep.recent_developments} />
            </>
          )}
          {prep.role_brief && (
            <>
              <h4 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-ink-500">
                The role
              </h4>
              <Markdown className="text-sm">{prep.role_brief}</Markdown>
            </>
          )}
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {(prep.strengths_to_lead_with ?? []).length > 0 && (
          <Card>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-emerald-700">
              Lead with these
            </h4>
            <BulletList items={prep.strengths_to_lead_with} tone="good" />
          </Card>
        )}
        {(prep.technical_topics ?? []).length > 0 && (
          <Card>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
              Revise before you go
            </h4>
            <BulletList items={prep.technical_topics} />
          </Card>
        )}
      </div>

      {gaps.length > 0 && (
        <Card className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-red-700">
            What they will press on, and what to say
          </h4>
          {gaps.map((gap, index) => (
            <div key={index} className="border-l-2 border-red-200 pl-3 dark:border-red-900">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">
                  <InlineMarkdown>{gap.gap}</InlineMarkdown>
                </span>
                {gap.severity && <Badge tone="warn">{gap.severity}</Badge>}
              </div>
              <p className="mt-1 text-sm text-ink-600 dark:text-ink-300">
                <InlineMarkdown>{gap.honest_answer}</InlineMarkdown>
              </p>
              {gap.preparation && (
                <p className="mt-1 text-xs text-ink-500">
                  Before the interview: <InlineMarkdown>{gap.preparation}</InlineMarkdown>
                </p>
              )}
            </div>
          ))}
        </Card>
      )}

      {questions.length > 0 && (
        <Card className="space-y-3">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Likely questions
          </h4>
          {questions.map((item, index) => (
            <div key={index} className="border-l-2 border-ink-200 pl-3 dark:border-ink-700">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">
                  <InlineMarkdown>{item.question}</InlineMarkdown>
                </span>
                {item.asked_by && <Badge>{item.asked_by}</Badge>}
              </div>
              {item.why_asked && (
                <p className="mt-0.5 text-xs text-ink-500">
                  They are testing: <InlineMarkdown>{item.why_asked}</InlineMarkdown>
                </p>
              )}
              {(item.answer_outline ?? []).length > 0 && (
                <div className="mt-1">
                  <BulletList items={item.answer_outline} />
                </div>
              )}
            </div>
          ))}
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {[
          ["Ask them", prep.questions_to_ask],
          ["Their process", prep.interview_process],
          ["Practical", prep.logistics],
          ["Satisfy yourself about", prep.red_flags_to_probe],
        ].map(([label, items]) =>
          (items as string[])?.length ? (
            <Card key={label as string}>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
                {label as string}
              </h4>
              <BulletList items={items as string[]} />
            </Card>
          ) : null,
        )}
      </div>

      <Card>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
          Where this came from
        </h4>
        {sources.length === 0 ? (
          <p className="text-sm text-amber-700 dark:text-amber-400">
            This brief cites nothing. Do not repeat anything it says about the employer without
            checking it yourself — run “Prepare again” instead.
          </p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {sources.map((source, index) => (
              <li key={index}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent-600 underline dark:text-accent-400"
                >
                  {source.title || source.url}
                </a>
                {source.takeaway && (
                  <span className="text-ink-600 dark:text-ink-300"> — {source.takeaway}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}


/** What each kind of contact is, in words, and how much it is worth. */
const CATEGORIES: Record<string, { label: string; tone: "good" | "info" | "neutral" }> = {
  alumnus: { label: "Same school", tone: "good" },
  campus: { label: "Runs their internships", tone: "good" },
  hiring_manager: { label: "Hiring manager", tone: "good" },
  recruiter: { label: "Recruiter", tone: "info" },
  team: { label: "On the team", tone: "info" },
  other: { label: "", tone: "neutral" },
};

/** A link that looks like a button, which is what all of these are. */
function LinkButton({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="squircle inline-flex min-h-9 items-center rounded-control border border-ink-200 px-2.5 text-xs hover:bg-ink-50 sm:min-h-0 sm:py-1 dark:border-ink-700 dark:hover:bg-ink-800"
    >
      {children}
    </a>
  );
}

/** The opening line is written to be sent, so the useful control is Copy. */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size="sm"
      variant="ghost"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 2000);
        } catch {
          // A browser that refuses the clipboard — an insecure origin, a
          // permission denied — is not worth an error banner over. The text is
          // on the screen and can be selected.
        }
      }}
    >
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

/**
 * One person, and everything you can do about them.
 *
 * The badge says which of the two kinds of link this is. **Profile checked**
 * means the backend fetched that profile and the page came back titled with
 * this person's name — so it opens them and nobody else. Without it there is no
 * profile link at all, only a search: an unproved URL is dropped rather than
 * shown with a caveat, because a link that opens a stranger costs exactly the
 * time this feature exists to save.
 */
function ContactRow({
  person,
  applicationId,
  index,
}: {
  person: Contact;
  applicationId: number;
  /** Their position on the saved shortlist — half of what the backend needs to
   *  write onto the right person. The other half is their name, which it checks
   *  against the position before writing anything. */
  index: number;
}) {
  const queryClient = useQueryClient();
  const category = CATEGORIES[person.category] ?? CATEGORIES.other;
  const verified = person.profile_status === "verified";

  // Written on request, one person at a time. The shortlist run used to write a
  // line for everybody it named, which meant eight drafts to send one — so this
  // is a button, for the same reason finding the people at all is one.
  const write = useMutation({
    mutationFn: () =>
      api.post<ContactMessageResult>(`/api/applications/${applicationId}/contacts/message`, {
        index,
        name: person.name,
      }),
    // The message is stored on the shortlist itself, so re-reading the artifact
    // is what puts it on screen — and what keeps it there after a reload.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["artifacts", applicationId] }),
  });

  return (
    <div className="border-l-2 border-ink-200 pl-3 dark:border-ink-700">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{person.name}</span>
        {category.label && <Badge tone={category.tone}>{category.label}</Badge>}
        {verified ? (
          <Badge tone="good" title="Their LinkedIn page was opened and it is titled with their name">
            profile checked
          </Badge>
        ) : (
          <Badge
            tone="neutral"
            title="Their profile URL could not be proved, so it was dropped — search for them instead"
          >
            search only
          </Badge>
        )}
      </div>
      {person.role && (
        <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">{person.role}</p>
      )}
      {person.why && (
        <p className="mt-1 text-sm text-ink-600 dark:text-ink-300">
          <InlineMarkdown>{person.why}</InlineMarkdown>
        </p>
      )}
      {person.opening_line ? (
        <div className="mt-2 rounded-lg bg-ink-50 p-2.5 dark:bg-ink-800/60">
          <div className="flex items-start justify-between gap-2">
            <p className="min-w-0 flex-1 text-sm italic text-ink-700 dark:text-ink-200">
              “{person.opening_line}”
            </p>
            <CopyButton text={person.opening_line} />
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
            <p
              className={`text-xs ${
                person.opening_line.length > 300
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-ink-500"
              }`}
            >
              {person.opening_line.length} characters — LinkedIn allows 300 in a connection note.
            </p>
            {/* The second draft is one click, which is why this run has no
                Critic loop: the candidate is looking at the text. */}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => write.mutate()}
              disabled={write.isPending}
            >
              {write.isPending ? "Writing…" : "Write it again"}
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-2">
          <Button size="sm" variant="secondary" onClick={() => write.mutate()} disabled={write.isPending}>
            {write.isPending ? "Writing the message…" : "Write the message"}
          </Button>
          <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">
            A connection note for {person.name.split(" ")[0] || "them"}, from this posting and
            what was found about them — written when you ask, not for everyone at once.
          </p>
        </div>
      )}
      <ErrorNote error={write.error} />
      <div className="mt-2 flex flex-wrap gap-1.5">
        {verified && person.linkedin_url && (
          <LinkButton href={person.linkedin_url}>Open their profile ↗</LinkButton>
        )}
        {person.search_url && (
          <LinkButton href={person.search_url}>
            {verified ? "Search LinkedIn ↗" : "Find them on LinkedIn ↗"}
          </LinkButton>
        )}
        {!verified && person.web_url && <LinkButton href={person.web_url}>Web search ↗</LinkButton>}
        {person.evidence_url && (
          <LinkButton href={person.evidence_url}>Where this name came from ↗</LinkButton>
        )}
      </div>
    </div>
  );
}

/**
 * Who to contact, laid out in the order it is used.
 *
 * People first — a name is the thing you cannot get any other way. Then the
 * searches, which are the floor: they are built in Python from the employer's
 * name, your own schools and the posting's vocabulary, so they exist and work
 * even when the research found nobody at all. Then how to approach them, then
 * what was thrown away.
 *
 * The one thing this page never does is show a link that was not either built
 * here or fetched and proved. That is the whole feature: a shortlist you have
 * to check yourself is the work you asked the app to do.
 */
function ContactsView({
  content,
  applicationId,
}: {
  content: Record<string, any>;
  applicationId: number;
}) {
  const plan = content as Partial<ContactPlan>;
  const people = plan.people ?? [];
  const angles = plan.angles ?? [];
  const dropped = plan.dropped ?? [];
  const company = plan.company ?? {};
  const approach = plan.approach ?? [];
  const sources = (plan.sources ?? []).filter((source) => source?.url);
  const checked = plan.checked;

  return (
    <div className="space-y-4">
      {/* A run whose writer failed still saves, because the searches are built
          rather than found and are worth having on their own. What it must not
          do is look like a run that simply found nobody. */}
      {plan.degraded && (
        <Card>
          <p className="text-sm text-amber-700 dark:text-amber-400">
            The research did not finish, so nobody could be named — the searches below are
            built from this posting and your own profile, and they work. Press{" "}
            <strong>Look again</strong> to retry the research.
          </p>
        </Card>
      )}

      <Card className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Worth writing to
          </h4>
          {checked && (
            <p className="text-xs text-ink-500">
              {checked.profiles_verified} profile(s) opened and confirmed · {checked.searches}{" "}
              searches built
            </p>
          )}
        </div>
        {people.length === 0 ? (
          <p className="text-sm text-ink-600 dark:text-ink-300">
            No individual could be named from anything readable — which is ordinary for a small
            employer. The searches below are the way in, and they work.
          </p>
        ) : (
          <div className="space-y-4">
            {people.map((person, index) => (
              <ContactRow
                key={`${person.name}-${index}`}
                person={person}
                applicationId={applicationId}
                index={index}
              />
            ))}
          </div>
        )}
      </Card>

      {(angles.length > 0 || company.url) && (
        <Card className="space-y-3">
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
              Searches to run
            </h4>
            <p className="mt-1 text-xs text-ink-500">
              Built here from the employer's name, your schools and this posting — so they open
              real results in your own LinkedIn session. Nothing on this list can be a dead link.
            </p>
          </div>
          {company.url && (
            <div className="flex flex-wrap gap-1.5">
              <LinkButton href={company.url}>Their LinkedIn page ↗</LinkButton>
              {company.people_url && (
                <LinkButton href={company.people_url}>Everyone who works there ↗</LinkButton>
              )}
              {company.recruiters_url && (
                <LinkButton href={company.recruiters_url}>Their recruiters ↗</LinkButton>
              )}
            </div>
          )}
          <ul className="space-y-2.5">
            {angles.map((angle, index) => (
              <li key={`${angle.keywords}-${index}`}>
                <a
                  href={angle.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm font-medium text-accent-600 underline dark:text-accent-400"
                >
                  {angle.label} ↗
                </a>
                {angle.why && (
                  <p className="text-xs text-ink-500 dark:text-ink-400">{angle.why}</p>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {approach.length > 0 && (
        <Card>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
            How to approach them
          </h4>
          <BulletList items={approach} />
        </Card>
      )}

      {plan.notes && (
        <Card>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
            What it could not find
          </h4>
          <Markdown className="text-sm">{plan.notes}</Markdown>
        </Card>
      )}

      {dropped.length > 0 && (
        <Card>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
            Left off this list
          </h4>
          {/* Said out loud rather than swallowed: a list that silently shrank
              looks exactly like a search that found less, and "the page naming
              them is gone" is usually worth knowing — it means their team page
              moved, not that they left. */}
          <ul className="space-y-1 text-sm text-ink-600 dark:text-ink-300">
            {dropped.map((entry, index) => (
              <li key={index}>
                <span className="font-medium">{entry.name}</span>
                {entry.role && <span className="text-ink-500"> · {entry.role}</span>} — {entry.reason}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {sources.length > 0 && (
        <Card>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
            Pages this was read off
          </h4>
          <ul className="space-y-1.5 text-sm">
            {sources.map((source, index) => (
              <li key={index}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent-600 underline dark:text-accent-400"
                >
                  {source.title || source.url}
                </a>
                {source.takeaway && (
                  <span className="text-ink-600 dark:text-ink-300"> — {source.takeaway}</span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function ResumeInsights({ content }: { content: Record<string, any> }) {
  const covered = (content.keywords_covered ?? []) as string[];
  const missing = (content.keywords_missing ?? []) as string[];
  const gaps = (content.gap_analysis ?? []) as string[];
  const changes = (content.changes_made ?? []) as string[];
  if (!covered.length && !missing.length && !gaps.length && !changes.length) return null;

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
          Keyword coverage
        </h4>
        <div className="flex flex-wrap gap-1">
          {covered.map((keyword) => (
            <Badge key={keyword} tone="good">
              {keyword}
            </Badge>
          ))}
          {missing.map((keyword) => (
            <Badge key={keyword} tone="bad" title="The posting asks for this but your profile does not support it">
              {keyword}
            </Badge>
          ))}
        </div>
        {gaps.length > 0 && (
          <>
            <h4 className="mb-1 mt-4 text-xs font-semibold uppercase tracking-wide text-ink-500">
              Honest gaps
            </h4>
            <BulletList items={gaps} />
          </>
        )}
      </Card>
      <Card>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500">
          What was changed vs your master profile
        </h4>
        <BulletList items={changes} />
      </Card>
    </div>
  );
}
