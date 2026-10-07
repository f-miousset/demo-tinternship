import type { ReactNode } from "react";

import { AddLinkForm } from "./AddLinkForm";
import { AddTextForm } from "./AddTextForm";
import { SearchChat, type ChatTurn } from "./SearchChat";
import type { ImportResult, RunPhase } from "../../lib/types";
import type { useRunStream } from "../../lib/useRunStream";

/**
 * The three ways to ask for a posting, in one box.
 *
 * They belong together because they are the same sentence with the specificity
 * turned down one step at a time: *this exact posting*, as a link or as the
 * text itself, and *this kind of posting* — a company, a role, a city you want
 * the agents to go and look for. All three are read and scored on the same
 * scale; where they differ is what the answer means. A posting you name is one
 * you have already chosen, so the first two put it on the Tracker and offer the
 * package; the third comes back with a deck to swipe.
 *
 * The text mode was added on 2026-09-03 for the postings the other two cannot
 * reach: the one that arrived as an email or a PDF, and the one on a board
 * whose bot protection answers a fetch — and then a real browser — with a
 * challenge rather than the page. The candidate is looking at the posting; the
 * app should not be the reason it cannot have it.
 *
 * Two placements, one definition, exactly as the paste field alone had: a card
 * under the header at `sm` and up, and the sheet behind the floating `+` below
 * it. The mode and the conversation live on the page rather than here, so
 * switching to the chat on a laptop and reopening the sheet on a phone finds
 * the same panel with the same transcript in it.
 */
export type AddMode = "link" | "text" | "chat";

type Mode = {
  key: AddMode;
  /** What the tab says on a phone, where three of these share 375px. */
  label: string;
  /** What it says from `sm` up, where the whole sentence fits. */
  longLabel: string;
  title: string;
  icon: ReactNode;
};

// The switch. A clipboard for the link, a document for the text you paste in
// its place, and a speech bubble for the thing you say — the same 24px stroked
// outline the tab bar's icons use, so the three sets read as one family.
//
// Two labels each. Three tabs of "Paste a job posting's text" do not fit across
// a 375px phone, and the honest fix is a short word there rather than a control
// that scrolls sideways: the pane underneath says the rest in a sentence, and
// `title` carries it for a pointer.
const MODES: Mode[] = [
  {
    key: "link",
    label: "Link",
    longLabel: "Paste a link",
    title: "Add one posting you already have the link to",
    icon: (
      <>
        <rect x="8" y="2" width="8" height="4" rx="1" />
        <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
      </>
    ),
  },
  {
    key: "text",
    label: "Text",
    longLabel: "Paste the text",
    title: "Paste the posting itself — for one that came by email, as a PDF, or on a site that will not open",
    icon: (
      <>
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <path d="M14 2v6h6" />
        <path d="M8 13h8M8 17h5" />
      </>
    ),
  },
  {
    key: "chat",
    label: "Ask",
    longLabel: "Ask the agents",
    title: "Tell the agents what to look for — a company, a kind of role, a city",
    icon: (
      <>
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </>
    ),
  },
];

export function AddPostingBox({
  mode,
  onMode,
  add,
  onAdded,
  turns,
  searching,
  phases,
  searchError,
  onAsk,
  autoFocus = false,
}: {
  mode: AddMode;
  onMode: (mode: AddMode) => void;
  /** One run hook for both paste forms. Two would let a link and a text import
   *  run at once and render two result cards for one deck. */
  add: ReturnType<typeof useRunStream<ImportResult>>;
  onAdded: (result: ImportResult) => void;
  turns: ChatTurn[];
  searching: boolean;
  phases: RunPhase[];
  searchError: unknown;
  onAsk: (text: string) => void;
  autoFocus?: boolean;
}) {
  return (
    <div className="space-y-3">
      {/* A segmented control, not two buttons: the two modes are one choice
          with one answer, and the track makes the unchosen half visibly
          available rather than merely absent. */}
      <div
        role="tablist"
        aria-label="How to add a posting"
        className="squircle inline-flex rounded-control bg-ink-100 p-0.5 dark:bg-ink-800"
      >
        {MODES.map((item) => {
          const active = item.key === mode;
          return (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={active}
              // The visible label shortens at 375px; the announced one does
              // not. Without this the tab reads as both spans at once —
              // "Link Paste a link" — since the breakpoint is CSS and the
              // accessibility tree is not.
              aria-label={item.longLabel}
              title={item.title}
              onClick={() => onMode(item.key)}
              // 44px on a phone, where this is a sheet a thumb operates, and
              // back to 36px on a laptop — the same pair `Button` uses, so the
              // switch is the size of the controls around it at either width.
              className={`squircle inline-flex min-h-11 items-center gap-1.5 rounded-control px-3 text-xs font-medium transition sm:min-h-9 ${
                active
                  ? "bg-white text-ink-900 shadow-sm dark:bg-ink-950 dark:text-ink-100"
                  : "text-ink-500 hover:text-ink-700 dark:text-ink-400 dark:hover:text-ink-200"
              }`}
            >
              <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                {item.icon}
              </svg>
              <span className="sm:hidden">{item.label}</span>
              <span className="hidden sm:inline">{item.longLabel}</span>
            </button>
          );
        })}
      </div>

      {mode === "link" && <AddLinkForm run={add} onAdded={onAdded} autoFocus={autoFocus} />}
      {mode === "text" && <AddTextForm run={add} onAdded={onAdded} autoFocus={autoFocus} />}
      {mode === "chat" && (
        <SearchChat
          turns={turns}
          running={searching}
          phases={phases}
          error={searchError}
          onSend={onAsk}
          autoFocus={autoFocus}
        />
      )}
    </div>
  );
}
