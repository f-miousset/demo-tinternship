import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNote,
  FloatingAction,
  Modal,
  RunProgress,
  ScoreBadge,
  Spinner,
} from "../components/ui";
import { AddPostingBox, type AddMode } from "../components/jobs/AddPostingBox";
import { replyTo, type ChatTurn } from "../components/jobs/searchReply";
import { DiscardPile } from "../components/jobs/DiscardPile";
import { JobDetails } from "../components/jobs/JobDetails";
import { SwipeDeck } from "../components/jobs/SwipeDeck";
import { InlineMarkdown } from "../components/Markdown";
import { api } from "../lib/api";
import type { AppConfig, ImportResult, Job, SearchResult } from "../lib/types";
import type { SwipeDirection } from "../lib/useSwipe";
import { useRunStream } from "../lib/useRunStream";

/** Used until `/api/config` answers, so the slider never renders without a range. */
const RESULT_BOUNDS = { default: 15, min: 5, max: 40 };

/** What the confirmation line says after each verdict. */
const CONFIRMATION: Record<SwipeDirection, (job: Job) => string> = {
  right: (job) => `${job.company} saved to your Tracker.`,
  up: (job) => `${job.company} pinned — it is first in its Tracker column.`,
  left: (job) => `${job.company} discarded. It is in the trash, and no run will bring it back.`,
  down: (job) => `${job.company} moved to the back of the deck.`,
};

export function JobsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [details, setDetails] = useState<Job | null>(null);
  const [showTrash, setShowTrash] = useState(false);
  const [showAddPosting, setShowAddPosting] = useState(false);
  // Which half of the add box is showing, and the conversation in it. Both live
  // here rather than in the box: the box is rendered twice — a card on a laptop,
  // a sheet on a phone — and a transcript held inside it would be thrown away
  // every time the sheet closed.
  const [addMode, setAddMode] = useState<AddMode>("link");
  const [chat, setChat] = useState<ChatTurn[]>([]);
  // Whether the search now on screen was asked for in the chat. One run stream
  // serves the button and the chat, so this is what decides *where* a failure
  // is reported: beside the control that started it, and only there. Without it
  // the same red note renders twice on a laptop, and on a phone a failure the
  // button caused would hide inside a sheet that is closed.
  const [searchWasAsked, setSearchWasAsked] = useState(false);
  const [lastVerdict, setLastVerdict] = useState<{ text: string; applicationId: number | null } | null>(
    null,
  );
  // Null until the user moves the slider, so it tracks the RESULTS_PER_RUN
  // default from .env instead of freezing whatever rendered first.
  const [chosenResults, setChosenResults] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["jobs", "deck"],
    queryFn: () => api.get<{ jobs: Job[]; sources: string[] }>("/api/jobs?view=deck"),
  });

  const { data: trash } = useQuery({
    queryKey: ["jobs", "discarded"],
    queryFn: () => api.get<{ jobs: Job[] }>("/api/jobs?view=discarded"),
  });

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => api.get<AppConfig>("/api/config"),
  });

  const bounds = config?.results ?? RESULT_BOUNDS;
  const targetResults = chosenResults ?? bounds.default;

  const search = useRunStream<SearchResult>();
  // One hook for both paste forms — a link and a text import are the same run
  // with a different input, and they can never be in flight at once.
  const addPosting = useRunStream<ImportResult>();

  /**
   * Where a paste ends: on the application, with the package already running.
   *
   * Pasting a posting answers every question the app would otherwise ask about
   * it. *Is it worth your time?* — you went and fetched it, so yes, and the
   * import tracks it. *Which language?* — the one the posting is written in,
   * which `language_check.posting_language` reads off it and stores on the
   * application. What is left is a page to watch it on, so the paste goes there
   * rather than leaving a card with buttons on it.
   *
   * `?generate=auto` is what starts the run, and it is only added when this
   * paste is what created the application. A re-paste of something already on
   * the Tracker opens it and stops: it may already have a résumé and a letter,
   * and two model runs is not what "I pasted that again" means.
   */
  function openTheApplication(result: ImportResult) {
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    queryClient.invalidateQueries({ queryKey: ["applications"] });
    if (typeof result.application_id !== "number") return;
    navigate(`/applications/${result.application_id}${result.tracked ? "?generate=auto" : ""}`);
  }

  /**
   * One Investigator run, steered or not.
   *
   * The button passes nothing and gets the run this page has always done. The
   * chat passes what the candidate typed, and it rides the same hook rather than
   * a second one — which is what makes it impossible to have two searches in
   * flight, and what puts a chat run's badges in the same result card.
   */
  async function runSearch(ask = "") {
    const focus = ask.trim();
    // Everything they have asked for so far, so a follow-up like "and also in
    // Berlin" has something to resolve against. Read before the new turn goes
    // up: the ask itself travels in `focus`, not twice.
    const earlier = chat.filter((turn) => turn.role === "you").map((turn) => turn.text);
    setSearchWasAsked(Boolean(focus));
    // The question appears the moment it is asked. A run takes minutes, and a
    // chat that shows nothing until it ends looks like it lost the message.
    if (focus) setChat((turns) => [...turns, { role: "you", text: focus }]);

    const result = await search.start(
      `/api/jobs/search?target_results=${targetResults}`,
      focus ? { focus, earlier } : undefined,
    );
    // Whatever happened. The postings are saved before the audit runs, so even
    // a run that fell over at the last step has something to show.
    queryClient.invalidateQueries({ queryKey: ["jobs"] });
    if (focus) {
      queryClient.invalidateQueries({ queryKey: ["search-history"] });
      setChat((turns) => [...turns, { role: "agents", text: replyTo(result) }]);
    }
  }

  /**
   * One mutation for all four verdicts.
   *
   * Each writes something different, but they share everything around the
   * write — the confirmation line, the two invalidations, and the fact that the
   * deck must not navigate anywhere. Swiping right used to open the application
   * page; on a deck that would end the session on every yes.
   */
  const verdict = useMutation({
    mutationFn: async ({ job, direction }: { job: Job; direction: SwipeDirection }) => {
      if (direction === "left") {
        await api.post(`/api/jobs/${job.id}/dismiss?dismissed=true`);
        return null;
      }
      if (direction === "down") {
        await api.post(`/api/jobs/${job.id}/defer`);
        return null;
      }
      const application = await api.post<{ id: number }>("/api/applications", {
        job_posting_id: job.id,
        pinned: direction === "up",
      });
      return application.id;
    },
    onSuccess: (applicationId, { job, direction }) => {
      setLastVerdict({ text: CONFIRMATION[direction](job), applicationId });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["applications"] });
    },
  });

  const jobs = data?.jobs ?? [];
  const discarded = trash?.jobs.length ?? 0;
  // Postings the run threw away for having no link, or a link to a careers
  // page rather than the posting. Summed over the reasons so the badge is one
  // number; the reasons themselves are only useful in the logs.
  const linkDrops = Object.values(search.result?.link_drops ?? {}).reduce(
    (total, count) => total + count,
    0,
  );
  const answeredDrops = Object.values(search.result?.answered_drops ?? {}).reduce(
    (total, count) => total + count,
    0,
  );

  return (
    <div className="space-y-4">
      {/* The heading stays in the DOM at every size — it is the page's landmark
          and the screen reader's anchor — but on a phone the deck is what the
          screen is for, so it does not spend a line on it. */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h2 className="sr-only text-lg font-semibold tracking-tight sm:not-sr-only">
            Job postings
          </h2>
          <p className="hidden max-w-lg text-sm text-ink-500 sm:block dark:text-ink-400">
            One posting at a time. Swipe right to save it, left to discard, up to pin it, down to
            decide later — a run never brings back one you answered.
          </p>
        </div>

        <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 sm:w-auto sm:justify-end">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setShowTrash(true)}
            title="Postings you discarded. Nothing is deleted — you can put any of them back."
          >
            Trash{discarded > 0 ? ` (${discarded})` : ""}
          </Button>
          <label
            className="flex flex-1 items-center gap-2 text-sm text-ink-500 sm:flex-none"
            title="How many ranked postings one run comes back with. More results means more searches, so the run costs more and takes longer."
          >
            <span className="whitespace-nowrap">
              results{" "}
              <span className="font-semibold tabular-nums text-ink-700 dark:text-ink-200">
                {targetResults}
              </span>
            </span>
            <input
              type="range"
              min={bounds.min}
              max={bounds.max}
              step={5}
              value={targetResults}
              disabled={search.running}
              onChange={(event) => setChosenResults(Number(event.target.value))}
              className="w-full accent-accent-600 disabled:opacity-50 sm:w-24"
            />
          </label>
          <Button onClick={() => void runSearch()} disabled={search.running}>
            {search.running ? "Searching…" : "Run Investigator"}
          </Button>
        </div>
      </div>

      {/* On a laptop the add box is a card that can sit here permanently. On a
          phone it lives behind the "+" instead — see below. */}
      <Card className="hidden sm:block">
        <AddPostingBox
          mode={addMode}
          onMode={setAddMode}
          add={addPosting}
          onAdded={openTheApplication}
          turns={chat}
          searching={search.running}
          phases={search.phases}
          searchError={searchWasAsked ? search.error : null}
          onAsk={(text) => void runSearch(text)}
        />
      </Card>


      {/* A run the chat asked for reports its failure inside the conversation
          that asked, so this would be the same sentence twice. */}
      <ErrorNote error={searchWasAsked ? null : search.error} />
      <ErrorNote error={verdict.error} />
      <RunProgress
        phases={search.phases}
        running={search.running}
        hint={
          search.running
            ? `Scouting job boards for ${targetResults} postings, de-duplicating and scoring — this can take a few minutes. Postings are saved as they are found, so leaving this page does not lose the run.`
            : undefined
        }
      />

      {search.result && (
        <Card className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <Badge tone="good">
              {search.result.saved?.saved ?? 0} saved ({search.result.saved?.created ?? 0} new)
            </Badge>
            {search.result.target_results &&
            (search.result.jobs?.length ?? 0) < search.result.target_results ? (
              <Badge
                tone="info"
                title="Fewer than you asked for, which a run that adds to an existing deck often is: postings already here are excluded, so a later run has less left to find. It can also mean the Matcher refused to pad the ranking with weak matches, or that too many links were broken to backfill from. Widen the brief, or check strategy notes below."
              >
                {search.result.jobs?.length ?? 0} of {search.result.target_results} requested
              </Badge>
            ) : null}
            {answeredDrops > 0 ? (
              <Badge
                tone="info"
                title="Postings the run found again that you had already answered — discarded, or already on your Tracker. They are dropped before the count is cut, so a posting you have never seen takes each freed slot."
              >
                {answeredDrops} already answered
              </Badge>
            ) : null}
            {search.result.audit?.overall ? (
              <ScoreBadge score={search.result.audit.overall} label="Ranking audit" />
            ) : null}
            {search.result.freshness ? (
              <Badge
                tone={
                  search.result.freshness.week + search.result.freshness.month > 0 ? "good" : "warn"
                }
                title="Recency is weighted heavily: a posting loses half its score every few weeks, so a stale one only reaches you when nothing fresher matched. Undated postings are treated as middle-aged — neither promoted nor buried."
              >
                fresh: {search.result.freshness.week} this week,{" "}
                {search.result.freshness.month} this month
                {search.result.freshness.older
                  ? `, ${search.result.freshness.older} over 3 months old`
                  : ""}
              </Badge>
            ) : null}
            {search.result.url_check ? (
              <Badge
                tone={search.result.url_check.dead || search.result.url_check.index ? "bad" : "good"}
                title="Every posting URL is fetched before it is saved, and judged on the page it returns — not just its status code. Boards behind bot protection (Welcome to the Jungle among them) answer the check with a challenge page, so those links cannot be checked at all and are counted as unchecked rather than verified."
              >
                links: {search.result.url_check.ok ?? 0} verified
                {search.result.url_check.dead ? `, ${search.result.url_check.dead} dead` : ""}
                {search.result.url_check.index
                  ? `, ${search.result.url_check.index} miss the posting`
                  : ""}
                {search.result.url_check.blocked
                  ? `, ${search.result.url_check.blocked} unchecked`
                  : ""}
              </Badge>
            ) : null}
            {linkDrops > 0 ? (
              <Badge
                tone="info"
                title="Postings thrown away because their link did not reach the posting — no link at all, a 404, or the company's careers page. You never see these: the ranking is asked for spares so a real posting takes each freed slot."
              >
                {linkDrops} dropped, broken links
              </Badge>
            ) : null}
            {search.result.feedback_applied?.summary ? (
              <Badge tone="info" title={search.result.feedback_applied.summary}>
                feedback applied
              </Badge>
            ) : null}
            <Link to={`/traces/${search.result.run_id}`} className="text-sm text-accent-600 underline">
              view trace
            </Link>
          </div>
          {search.result.strategy_notes && (
            <p className="text-sm text-ink-500 dark:text-ink-400">
              <InlineMarkdown>{search.result.strategy_notes}</InlineMarkdown>
            </p>
          )}
        </Card>
      )}

      {isLoading && <Spinner label="Loading postings…" />}

      {!isLoading && jobs.length === 0 && (
        <EmptyState
          title={discarded > 0 ? "Nothing left to swipe" : "No postings yet"}
          hint={
            discarded > 0
              ? "Every posting has been answered. Run the Investigator for more, or take one back out of the trash."
              : "Run the Investigator. It works from the search brief and hiring playbook your account setup produced."
          }
          action={
            <Button onClick={() => void runSearch()} disabled={search.running}>
              {search.running ? "Searching…" : "Run Investigator"}
            </Button>
          }
        />
      )}

      {jobs.length > 0 && (
        <SwipeDeck
          jobs={jobs}
          busy={verdict.isPending}
          onDetails={setDetails}
          onVerdict={(job, direction) => verdict.mutate({ job, direction })}
        />
      )}

      {lastVerdict && (
        <p className="text-center text-sm text-ink-500 dark:text-ink-400">
          {lastVerdict.text}{" "}
          {lastVerdict.applicationId !== null && (
            <Link
              to={`/applications/${lastVerdict.applicationId}`}
              className="text-accent-600 underline dark:text-accent-400"
            >
              open it
            </Link>
          )}
        </p>
      )}

      {/* The phone's way to the add box: out of the way until it is wanted, and
          in the corner a thumb already rests on. */}
      <FloatingAction
        label="Add a posting, or ask the agents for one"
        onClick={() => setShowAddPosting(true)}
        className="sm:hidden"
      >
        +
      </FloatingAction>

      <Modal
        open={showAddPosting}
        onClose={() => setShowAddPosting(false)}
        title="Add a posting"
      >
        <AddPostingBox
          mode={addMode}
          onMode={setAddMode}
          add={addPosting}
          autoFocus
          onAdded={(result) => {
            setShowAddPosting(false);
            openTheApplication(result);
          }}
          turns={chat}
          searching={search.running}
          phases={search.phases}
          searchError={searchWasAsked ? search.error : null}
          // Deliberately not closed on send, unlike an added link: the answer to
          // a question belongs in the conversation that asked it, and closing
          // the sheet would hide the run the candidate is waiting on.
          onAsk={(text) => void runSearch(text)}
        />
      </Modal>

      <Modal open={showTrash} onClose={() => setShowTrash(false)} title="Discarded postings">
        <DiscardPile />
      </Modal>

      <Modal
        open={details !== null}
        onClose={() => setDetails(null)}
        title={details ? `${details.company} — ${details.title}` : ""}
      >
        {details && <JobDetails job={details} />}
      </Modal>
    </div>
  );
}
