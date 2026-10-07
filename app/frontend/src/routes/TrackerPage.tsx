import { useQuery } from "@tanstack/react-query";
import { type TouchEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { FollowUpsPanel } from "../components/FollowUp";
import { TrackerStats } from "../components/TrackerStats";
import { TrackerTrash } from "../components/TrackerTrash";
import {
  Badge,
  Button,
  EmptyState,
  Modal,
  ScoreBadge,
  SectionTitle,
  Spinner,
  inputClass,
} from "../components/ui";
import { api } from "../lib/api";
import { STATUS_COLOR } from "../lib/statusColors";
import { STATUS_LABEL } from "../lib/statuses";
import { searchApplications } from "../lib/trackerSearch";
import type { Application, ApplicationStatus } from "../lib/types";

/**
 * The order cards take inside a status: pinned first, then by fit score, best
 * first; an application whose posting was never scored goes last.
 *
 * A pin is not lifted into a favourites row of its own: the point of a pin is
 * that this is the application you care most about *right now*, and it has to
 * keep moving across the board as its status changes. A separate strip would
 * show it twice or take it out of the pipeline it is actually in. Below the
 * pins, the score is the one thing every card shows and the best reason to
 * look at one before another (2026-09-26). The sort is stable, so ties keep
 * the order the API sent.
 */
function ranked(applications: Application[]): Application[] {
  const score = (application: Application) => application.job?.fit_score || -1;
  return [...applications].sort(
    (a, b) => Number(b.pinned) - Number(a.pinned) || score(b) - score(a),
  );
}

/**
 * The first line of a note, short enough for a board card.
 *
 * Cut at a line break first: notes are written as a list far more often than as
 * a paragraph, and the first bullet says more than the first ninety characters
 * of a run-on would.
 */
function firstLine(notes: string): string {
  const [first = ""] = notes.trim().split("\n");
  return first.length > 90 ? `${first.slice(0, 87)}…` : first;
}

/** One application on the board. */
function ApplicationCard({ application }: { application: Application }) {
  return (
    <Link
      to={`/applications/${application.id}`}
      className={`squircle block rounded-card border bg-white p-3 transition hover:border-accent-400 dark:bg-ink-900 ${
        application.pinned
          ? "border-accent-400 shadow-sm shadow-accent-600/20"
          : "border-ink-200 dark:border-ink-800"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium">
          {application.pinned && (
            <span
              aria-label="pinned"
              title="Pinned — first in this column"
              className="mr-1 text-accent-600 dark:text-accent-400"
            >
              ★
            </span>
          )}
          {application.job?.title}
        </span>
        {application.job?.fit_score ? (
          <ScoreBadge score={application.job.fit_score} />
        ) : null}
      </div>
      <p className="mt-0.5 text-xs text-ink-500">{application.job?.company}</p>
      {application.job?.deadline && (
        <p className="mt-1 text-xs text-amber-600">
          deadline {application.job.deadline}
        </p>
      )}
      {application.artifacts.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {application.artifacts.map((artifact) => (
            <Badge key={artifact.id}>{artifact.kind.replace("_", " ")}</Badge>
          ))}
        </div>
      )}
      {application.next_action && (
        <p className="mt-2 text-xs text-ink-600 dark:text-ink-300">
          next: {application.next_action}
        </p>
      )}
      {/* One line of what you wrote, so the board says which
          applications you have thought about. The whole note is
          one click away and this card has room for a sentence —
          showing four would turn a column into a wall of text. */}
      {application.notes?.trim() && (
        <p
          className="mt-2 border-l-2 border-ink-200 pl-2 text-xs italic text-ink-500 dark:border-ink-700 dark:text-ink-400"
          title="Your notes on this application"
        >
          {firstLine(application.notes)}
        </p>
      )}
    </Link>
  );
}

/**
 * The two arrows either side of the status strip. 40px square: they are the
 * only way a mouse without a keyboard changes status, and on a phone they sit
 * right where a thumb rests.
 */
const STEP_BUTTON =
  "squircle inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-control text-ink-600 transition hover:bg-ink-100 disabled:cursor-not-allowed disabled:opacity-30 dark:text-ink-300 dark:hover:bg-ink-800";

/** How long the typing has to pause before the results are scrolled to. */
const SEARCH_SETTLE_MS = 600;

/** How much of the results must show above the tab bar to count as in view: about one card. */
const RESULTS_VISIBLE = 120;

/** How far a finger must travel sideways, and how much straighter than down, to count as a swipe. */
const SWIPE_DISTANCE = 60;

/** The board's statuses, in pipeline order. Their colours are `STATUS_COLOR`. */
const COLUMNS: { key: ApplicationStatus; label: string }[] = (
  Object.keys(STATUS_LABEL) as ApplicationStatus[]
).map((key) => ({ key, label: STATUS_LABEL[key] }));

export function TrackerPage() {
  const [showTrash, setShowTrash] = useState(false);

  // The search lives in the URL rather than in component state, so leaving the
  // board for an application and coming back with the browser's Back gesture
  // returns to the same narrowed board instead of to all of it — which on a
  // phone is the whole journey: search, open, back, open the next one. It is
  // `replace` because a keystroke is not a place you navigate to, and pushing
  // one entry per character would bury the page you came from.
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const setQuery = useCallback(
    (next: string) =>
      setParams(
        (previous) => {
          const updated = new URLSearchParams(previous);
          if (next) updated.set("q", next);
          else updated.delete("q");
          return updated;
        },
        { replace: true },
      ),
    [setParams],
  );

  const { data, isLoading } = useQuery({
    queryKey: ["applications"],
    queryFn: () => api.get<{ applications: Application[] }>("/api/applications"),
  });

  // Only for the count on the button. The pile itself is fetched by the panel
  // inside the sheet, which is where it is actually read.
  const { data: trash } = useQuery({
    queryKey: ["applications", "trashed"],
    queryFn: () => api.get<{ applications: Application[] }>("/api/applications?view=trashed"),
  });

  const applications = data?.applications ?? [];
  const trashed = trash?.applications.length ?? 0;
  // The charts read the whole board on purpose, never the search: they are
  // the honest tally of how the job hunt is going, and a response rate
  // computed over whatever four rows happen to match "nimbus" is not a rate at
  // all. Only the columns below the field narrow.
  const matches = searchApplications(applications, query);
  const searching = query.trim().length > 0;

  // Only the statuses with something in them, after the search — an empty tab
  // is a tap that shows nothing. The chosen one lives in the URL next to the
  // search, for the same reason: open an application, come back with Back,
  // land on the status you were reading.
  const columns = COLUMNS.map((column) => ({
    ...column,
    items: ranked(matches.filter((application) => application.status === column.key)),
  })).filter((column) => column.items.length > 0);
  const wanted = params.get("status");
  // A status the search just emptied falls back to the first one that is left
  // rather than to an empty board.
  const current = columns.find((column) => column.key === wanted) ?? columns[0];
  const index = current ? columns.indexOf(current) : -1;

  const setStatus = useCallback(
    (next: ApplicationStatus) =>
      setParams(
        (previous) => {
          const updated = new URLSearchParams(previous);
          updated.set("status", next);
          return updated;
        },
        { replace: true },
      ),
    [setParams],
  );
  // Stops at both ends rather than wrapping: the strip is in pipeline order,
  // and jumping from Withdrawn back to Saved would read as a bug.
  const step = useCallback(
    (delta: number) => {
      const next = columns[index + delta];
      if (next) setStatus(next.key);
    },
    [columns, index, setStatus],
  );

  // Typing a search scrolls its results into view when they are off screen.
  // The field is at the top of the page and the charts and the emails to send
  // sit between it and the board, so with a few follow-ups open the matches
  // can land a whole screen below the field — you type and nothing seems to
  // happen (reported 2026-09-26). Waits for a pause in the typing rather than
  // moving the page under every keystroke, and only reacts to the query
  // *changing*: arriving on `/tracker?q=…` with Back is the browser's scroll
  // to restore, not ours. "Off screen" is measured against what the floating
  // header and the tab bar leave visible, and the scroll stops just below the
  // header so the first match is not hidden under the glass.
  const results = useRef<HTMLDivElement>(null);
  const lastQuery = useRef(query);
  useEffect(() => {
    if (query === lastQuery.current) return;
    lastQuery.current = query;
    if (!query.trim()) return;
    const timer = window.setTimeout(() => {
      const block = results.current;
      if (!block) return;
      const top = block.getBoundingClientRect().top;
      const header = document.querySelector(".header-dock")?.getBoundingClientRect();
      const tabbar = document.querySelector(".tabbar-dock")?.getBoundingClientRect();
      const ceiling = header ? Math.max(0, header.bottom) : 0;
      const floor = tabbar && tabbar.height > 0 ? tabbar.top : window.innerHeight;
      // Visible means the block starts inside that band with room for a card.
      if (top >= ceiling && top <= floor - RESULTS_VISIBLE) return;
      const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      window.scrollBy({ top: top - ceiling - 12, behavior: still ? "auto" : "smooth" });
    }, SEARCH_SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [query]);

  // The strip scrolls sideways on a phone; keep the chosen tab in view when
  // the arrows or a swipe move past the edge of it. By hand rather than with
  // `scrollIntoView`, which also scrolls the *page* to the strip — and on
  // first load, with the strip below the charts, that jumped the whole page.
  // The strip is `relative`, so a tab's `offsetLeft` is measured from it.
  const strip = useRef<HTMLDivElement>(null);
  const selectedTab = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const box = strip.current;
    const tabEl = selectedTab.current;
    if (!box || !tabEl) return;
    const left = tabEl.offsetLeft;
    const right = left + tabEl.offsetWidth;
    if (left < box.scrollLeft) box.scrollLeft = left - 8;
    else if (right > box.scrollLeft + box.clientWidth) box.scrollLeft = right - box.clientWidth + 8;
  }, [current?.key]);

  // Arrow keys on the whole document, like the deck's: the board is what this
  // page is for, and needing to focus the strip first would make the keyboard
  // worse than the mouse. Not while typing in the search field, not with a
  // sheet open over the board, and not with a modifier (browser history).
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.altKey || event.metaKey || event.ctrlKey || event.shiftKey) return;
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (document.querySelector('[aria-modal="true"]')) return;
      event.preventDefault();
      step(event.key === "ArrowLeft" ? -1 : 1);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [step]);

  // A swipe is judged once, at the end: sideways enough and far enough.
  // Swiping left shows the next status, as turning a page does.
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  function onTouchStart(event: TouchEvent) {
    const touch = event.touches[0];
    touchStart.current = touch ? { x: touch.clientX, y: touch.clientY } : null;
  }
  function onTouchEnd(event: TouchEvent) {
    const start = touchStart.current;
    const touch = event.changedTouches[0];
    touchStart.current = null;
    if (!start || !touch) return;
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    if (Math.abs(dx) < SWIPE_DISTANCE || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    step(dx < 0 ? 1 : -1);
  }

  return (
    <div className="space-y-5">
      <SectionTitle
        title="Tracker"
        subtitle="Keep this honest. Every status change and note feeds the Feedback Analyst, which rewrites how the Investigator searches next time."
        action={
          // Right-aligned rather than stretched: `SectionTitle` stretches its
          // action below `sm`, and a full-width button would give the least
          // important control on the page the widest target on the phone.
          <div className="flex justify-end">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setShowTrash(true)}
              title="Applications you gave up on. Nothing is deleted — the status, the timeline, your notes and every generated document are still on the row, and you can put any of them back."
            >
              Trash{trashed > 0 ? ` (${trashed})` : ""}
            </Button>
          </div>
        }
      />

      {/* First on the page (2026-09-26): finding one application is the
          most common reason to open the Tracker. It scopes the board only —
          the charts and the follow-ups below it still count everything, and
          the `N of M shown` line under the field says which. Plain, not glass —
          this is content you read and type into, not a control floating over
          it. */}
      {applications.length > 0 && (
        <div>
          <div className="relative">
            <svg
              viewBox="0 0 24 24"
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.6-3.6" />
            </svg>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label="Search applications"
              placeholder="Search by role, company, city, note…"
              className={`${inputClass} pl-9 ${searching ? "pr-16" : ""}`}
            />
            {/* Our own, not the one WebKit draws inside a `type="search"` — that
                one exists on Safari and nowhere else, and index.css hides it so
                a phone does not show two crosses side by side. */}
            {searching && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setQuery("")}
                className="absolute right-1.5 top-1/2 -translate-y-1/2"
              >
                Clear
              </Button>
            )}
          </div>
          {searching && (
            <p className="mt-1.5 text-xs text-ink-500 dark:text-ink-400">
              {matches.length} of {applications.length} shown
            </p>
          )}
        </div>
      )}

      {/* Drawn, not listed: where everything is and how it is going, in one
          card so a phone reaches the board after one short block. It reads
          every application whatever the search says, and says so while one is
          active — the field above it no longer shows its scope by where it
          sits. */}
      {applications.length > 0 && (
        <TrackerStats applications={applications} columns={COLUMNS} searching={searching} />
      )}

      {/* After the charts and right above the board it comes from: the emails
          still to send are what to do next, and the board is where you go to
          do it (order set 2026-09-26). */}
      <FollowUpsPanel />

      {isLoading && <Spinner label="Loading applications…" />}
      {!isLoading && applications.length === 0 && (
        <EmptyState
          title="No applications yet"
          hint="Pick a posting on the Jobs page and click “Apply with agents”."
        />
      )}

      {/* The results — what the search field above scopes — as one block, so
          typing can bring them into view (see `results` above). */}
      {applications.length > 0 && (
        <div ref={results} className="space-y-5">
        {/* A search that found nothing says so, rather than leaving a blank space
            where the board was — and points at the trash, which it does not
            cover: an application you gave up on is still a row you might be
            looking for. */}
        {applications.length > 0 && matches.length === 0 && (
          <EmptyState
            title={`Nothing matches “${query.trim()}”`}
            hint={
              trashed > 0
                ? "This searches the board only. If you gave up on it, it is in the trash — which kept the status, the timeline, your notes and every document."
                : "Try the company, the role, the city, or a word from your own note."
            }
            action={
              <Button size="sm" variant="secondary" onClick={() => setQuery("")}>
                Clear the search
              </Button>
            }
          />
        )}

        {current && (
          <div className="space-y-3">
            {/* One status at a time (2026-09-26): seven columns stacked on a phone
                were one list as long as the whole board, and the status you
                wanted was a long scroll away. The strip names every status that
                has something in it, with its count, so nothing is hidden — it is
                one tap, one swipe or one arrow key away.

                Centred as one group — arrows and tabs together. The strip has no
                `flex-1`, so it is as wide as its tabs and the group sits in the
                middle; once the tabs outgrow the row, `min-w-0` lets it shrink
                and scroll between the arrows instead of pushing them off. The
                padding is room for the selected tab's shadow, which a scroll
                container would otherwise clip. The 8px fade at each end sits
                inside that padding, so it is invisible while everything fits,
                and once the row scrolls a tab cut by the edge fades out instead
                of ending in a hard line against the arrow — which read as the
                two overlapping. */}
            <div className="flex items-center justify-center gap-1">
              <button
                type="button"
                onClick={() => step(-1)}
                disabled={index <= 0}
                aria-label="Previous status"
                title="Previous status (←)"
                className={STEP_BUTTON}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m15 18-6-6 6-6" />
                </svg>
              </button>
              <div
                ref={strip}
                role="tablist"
                aria-label="Application status"
                className="relative flex min-w-0 gap-1.5 overflow-x-auto px-2 py-1 [mask-image:linear-gradient(to_right,transparent,black_8px,black_calc(100%-8px),transparent)] [scrollbar-width:none]"
              >
                {columns.map((column) => {
                  const selected = column.key === current.key;
                  return (
                    <button
                      key={column.key}
                      type="button"
                      role="tab"
                      aria-selected={selected}
                      ref={selected ? selectedTab : undefined}
                      onClick={() => setStatus(column.key)}
                      // The same colours as the bars above: the selected tab is
                      // the segment's solid fill, the rest wear it faintly with
                      // a dot of the full colour, so a tab and its segment are
                      // recognisably the same thing.
                      className={`inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-chip px-3 text-xs font-medium transition ${
                        selected
                          ? `${STATUS_COLOR[column.key].fill} ${STATUS_COLOR[column.key].onFill} shadow-sm`
                          : `${STATUS_COLOR[column.key].tint} text-ink-700 hover:brightness-95 dark:text-ink-200 dark:hover:brightness-125`
                      }`}
                    >
                      {!selected && (
                        <span
                          aria-hidden="true"
                          className={`h-2 w-2 rounded-full ${STATUS_COLOR[column.key].fill}`}
                        />
                      )}
                      {column.label}
                      <span className="tabular-nums opacity-75">{column.items.length}</span>
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                onClick={() => step(1)}
                disabled={index >= columns.length - 1}
                aria-label="Next status"
                title="Next status (→)"
                className={STEP_BUTTON}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="m9 18 6-6-6-6" />
                </svg>
              </button>
            </div>

            {/* `touch-action: pan-y` hands vertical scrolling to the browser and
                keeps the horizontal drag for us, so a sideways swipe changes the
                status instead of nudging the page. Touch only: a mouse has the
                buttons and the arrow keys, and a mouse drag across a card is far
                more often someone selecting its text.

                `min-h-[60svh]`: switching from a long status to a short one would
                otherwise shorten the page under you, the browser would clamp the
                scroll, and the strip you were tapping would jump down the
                screen. The floor keeps it where your thumb is. */}
            <div
              role="tabpanel"
              aria-label={current.label}
              onTouchStart={onTouchStart}
              onTouchEnd={onTouchEnd}
              className="grid min-h-[60svh] touch-pan-y content-start gap-2 sm:grid-cols-2 xl:grid-cols-3"
            >
              {current.items.map((application) => (
                <ApplicationCard key={application.id} application={application} />
              ))}
            </div>
          </div>
        )}
        </div>
      )}

      <Modal open={showTrash} onClose={() => setShowTrash(false)} title="Applications you gave up on">
        <TrackerTrash />
      </Modal>
    </div>
  );
}
