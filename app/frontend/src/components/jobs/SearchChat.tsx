import { useEffect, useRef, useState } from "react";

import { Button, ErrorNote, Spinner } from "../ui";
import { Markdown } from "../Markdown";
import type { RunPhase } from "../../lib/types";
import type { ChatTurn } from "./searchReply";
import { formatHistoryTime, useSearchHistory } from "../../lib/searchHistory";
export type { ChatTurn };

/** Fills the composer rather than sending: an example is a starting point. */
const EXAMPLES = [
  "Anything open at Mistral AI",
  "Computer-vision internships in Paris",
  "Remote data roles starting in January",
];

/**
 * Telling the agents what to look for, in words.
 *
 * The other half of the same box as the paste field, and the opposite motion:
 * pasting a link says *this exact posting*, this says *this kind of posting*.
 * What the candidate types is layered onto the standing search brief for one
 * run — it reaches the query planner, the Scout and the Matcher, so the steer
 * lands on the searches and not only on the ranking. See
 * `services/context_blocks.py::focus_block`.
 *
 * It drives the page's own Investigator run rather than a stream of its own, so
 * the "Run Investigator" button and this cannot both be in flight at once, and
 * a chat run's results appear in the same badges an ordinary one does.
 */
export function SearchChat({
  turns,
  running,
  phases,
  error,
  onSend,
  autoFocus = false,
}: {
  turns: ChatTurn[];
  running: boolean;
  phases: RunPhase[];
  error: unknown;
  onSend: (text: string) => void;
  autoFocus?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { history, add, remove, clear } = useSearchHistory();

  // Follow the conversation down as it grows. `?.` on the method as well as the
  // ref: jsdom has no `scrollIntoView`, and a chat that cannot be mounted in a
  // test is a chat nothing checks.
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [turns.length, running, phases.length]);

  function send() {
    const text = draft.trim();
    if (!text || running) return;
    setDraft("");
    setShowHistory(false);
    add(text);
    onSend(text);
  }

  function selectHistoryItem(text: string) {
    setDraft(text);
    setShowHistory(false);
    textareaRef.current?.focus();
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-ink-600 dark:text-ink-400">
          {turns.length > 0 ? "Conversation" : "Tell the agents what to look for"}
        </span>
        <button
          type="button"
          onClick={() => setShowHistory((open) => !open)}
          className={`squircle inline-flex min-h-9 items-center gap-1.5 rounded-control border px-2.5 py-1 text-xs font-medium transition sm:min-h-0 sm:py-1 ${
            showHistory
              ? "border-accent-500 bg-accent-500/10 text-accent-700 dark:border-accent-500/40 dark:bg-accent-500/20 dark:text-accent-300"
              : "border-ink-200 bg-white text-ink-700 hover:border-ink-300 hover:bg-ink-50 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-200 dark:hover:bg-ink-800"
          }`}
          title={showHistory ? "Hide sent messages history" : "Show sent messages history"}
          aria-expanded={showHistory}
          aria-label="History of sent messages"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            className="h-3.5 w-3.5"
          >
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
            <path d="M12 7v5l4 2" />
          </svg>
          <span>History</span>
          {history.length > 0 && (
            <span
              className={`rounded-chip px-1.5 py-0.2 text-[10px] font-semibold ${
                showHistory
                  ? "bg-accent-600 text-white"
                  : "bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300"
              }`}
            >
              {history.length}
            </span>
          )}
        </button>
      </div>

      {showHistory && (
        <div
          className="squircle space-y-2 rounded-card border border-ink-200 bg-white p-3 shadow-xs dark:border-ink-800 dark:bg-ink-900"
          role="region"
          aria-label="Sent messages history"
        >
          <div className="flex items-center justify-between gap-2 border-b border-ink-100 pb-2 dark:border-ink-800">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
                Sent messages
              </span>
              <span className="rounded-full bg-ink-100 px-1.5 py-0.5 text-[10px] font-medium text-ink-600 dark:bg-ink-800 dark:text-ink-300">
                {history.length}
              </span>
            </div>
            <div className="flex items-center gap-3">
              {history.length > 0 && (
                <button
                  type="button"
                  onClick={clear}
                  className="text-xs text-ink-400 transition hover:text-accent-600 dark:hover:text-accent-400"
                  title="Clear all sent messages"
                >
                  Clear all
                </button>
              )}
              <button
                type="button"
                onClick={() => setShowHistory(false)}
                className="rounded-chip p-1 text-ink-400 transition hover:bg-ink-100 hover:text-ink-700 dark:hover:bg-ink-800 dark:hover:text-ink-200"
                aria-label="Close history"
              >
                ✕
              </button>
            </div>
          </div>

          {history.length === 0 ? (
            <p className="py-4 text-center text-xs text-ink-500 dark:text-ink-400">
              No sent messages yet. Questions you send to the agents will appear here.
            </p>
          ) : (
            <ul className="max-h-56 space-y-1.5 overflow-y-auto overscroll-contain">
              {history.map((item) => (
                <li
                  key={item.id}
                  className="group flex items-center justify-between gap-2 rounded-control border border-ink-100 bg-ink-50/70 p-2 text-xs transition hover:border-accent-500/40 hover:bg-ink-100 dark:border-ink-800 dark:bg-ink-950/40 dark:hover:bg-ink-800/80"
                >
                  <button
                    type="button"
                    onClick={() => selectHistoryItem(item.text)}
                    className="min-w-0 flex-1 text-left"
                    title={`Use "${item.text}"`}
                  >
                    <p className="truncate font-medium text-ink-900 dark:text-ink-100">
                      {item.text}
                    </p>
                    <p className="text-[10px] text-ink-400 dark:text-ink-500">
                      {formatHistoryTime(item.timestamp)}
                    </p>
                  </button>

                  <div className="flex shrink-0 items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => selectHistoryItem(item.text)}
                      className="squircle rounded-chip border border-ink-200 bg-white px-2.5 py-1 text-[11px] font-medium text-ink-700 shadow-2xs transition hover:border-accent-500 hover:text-accent-600 dark:border-ink-700 dark:bg-ink-800 dark:text-ink-200 dark:hover:border-accent-500 dark:hover:text-accent-400"
                    >
                      Use
                    </button>
                    <button
                      type="button"
                      onClick={() => remove(item.id)}
                      className="rounded-chip p-1 text-ink-400 transition hover:bg-ink-200/60 hover:text-accent-600 dark:hover:bg-ink-700 dark:hover:text-accent-400"
                      aria-label={`Remove "${item.text}" from history`}
                      title="Remove from history"
                    >
                      ✕
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {turns.length > 0 || running ? (
        <div
          className="max-h-64 space-y-3 overflow-y-auto overscroll-contain rounded-card bg-ink-50 p-3 sm:max-h-72 dark:bg-ink-950/60"
          aria-live="polite"
        >
          {turns.map((turn, index) => (
            <div
              key={index}
              className={turn.role === "you" ? "flex justify-end" : "flex justify-start"}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${
                  turn.role === "you"
                    ? "whitespace-pre-wrap bg-accent-600 text-white"
                    : "bg-white dark:bg-ink-800"
                }`}
              >
                {/* Only the agents' side is markdown. What the candidate typed
                    is literal — their asterisks and line breaks are theirs. */}
                {turn.role === "you" ? turn.text : <Markdown>{turn.text}</Markdown>}
              </div>
            </div>
          ))}
          {running && (
            <div className="flex justify-start">
              <div className="max-w-[85%] rounded-2xl bg-white px-3.5 py-2 text-sm dark:bg-ink-800">
                {/* The run's own phase line, not a "typing…" animation: the
                    candidate is waiting minutes, and which of the four stages
                    is speaking is the only honest thing to show them. */}
                <Spinner label={phases[phases.length - 1]?.message ?? "Starting the run…"} />
              </div>
            </div>
          )}
          <div ref={end} />
        </div>
      ) : null}

      {/* Here as well as on the page: on a phone this panel is a sheet over
          the page, and a failure explained underneath it is one the candidate
          has to close the sheet to read. */}
      <ErrorNote error={error} />

      <div className="flex items-end gap-2">
        <label className="min-w-0 flex-1">
          <span className="sr-only">Tell the agents what to look for</span>
          <textarea
            ref={textareaRef}
            value={draft}
            autoFocus={autoFocus}
            rows={2}
            disabled={running}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                send();
              }
            }}
            placeholder="A company, a kind of role, a city… (Enter to send)"
            className="w-full resize-none rounded-control border border-ink-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-accent-500 focus:ring-2 focus:ring-accent-500/20 disabled:opacity-60 sm:py-2 dark:border-ink-700 dark:bg-ink-950 dark:text-ink-100"
          />
        </label>
        <Button className="shrink-0" onClick={send} disabled={running || !draft.trim()}>
          {running ? "Searching…" : "Search"}
        </Button>
      </div>

      {turns.length === 0 && !running ? (
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setDraft(example)}
              className="squircle rounded-chip border border-ink-200 px-2 py-1 text-xs text-ink-600 transition hover:border-accent-400 hover:text-accent-700 dark:border-ink-700 dark:text-ink-300 dark:hover:text-accent-400"
            >
              {example}
            </button>
          ))}
        </div>
      ) : null}

      <p className="text-xs text-ink-500 dark:text-ink-400">
        This steers one Investigator run: your words are layered on top of your search brief,
        which still decides what counts as a good posting. The results land in the deck below,
        scored on the same scale as any other run.
      </p>
    </div>
  );
}
