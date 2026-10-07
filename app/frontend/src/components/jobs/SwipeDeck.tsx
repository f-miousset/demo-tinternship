import { useCallback, useEffect } from "react";

import { JobCard } from "./JobCard";
import { useSwipe, type SwipeDirection } from "../../lib/useSwipe";
import type { Job } from "../../lib/types";

/**
 * What each direction means, in one place.
 *
 * The stamps, the buttons, the keyboard map and the confirmation line all read
 * from this — so a fifth verdict, or a renamed one, is a single edit rather
 * than five that have to agree.
 */
const VERDICTS: Record<
  SwipeDirection,
  { label: string; hint: string; glyph: string; tone: string; stamp: string; key: string }
> = {
  right: {
    label: "Save",
    hint: "Save it — it goes to the Tracker",
    glyph: "♥",
    tone: "text-emerald-600 dark:text-emerald-400",
    stamp: "border-emerald-500 text-emerald-600",
    key: "ArrowRight",
  },
  left: {
    label: "Discard",
    hint: "Discard it — it goes to the trash, and no run brings it back",
    glyph: "✕",
    tone: "text-red-600 dark:text-red-400",
    stamp: "border-red-500 text-red-600",
    key: "ArrowLeft",
  },
  up: {
    label: "Pin",
    hint: "Save it and pin it — top of its Tracker column",
    glyph: "★",
    tone: "text-accent-600 dark:text-accent-400",
    stamp: "border-accent-500 text-accent-600",
    key: "ArrowUp",
  },
  down: {
    label: "Later",
    hint: "Undecided — back of the deck",
    glyph: "↓",
    tone: "text-ink-500 dark:text-ink-400",
    stamp: "border-ink-400 text-ink-500",
    key: "ArrowDown",
  },
};

const ORDER: SwipeDirection[] = ["left", "down", "up", "right"];

/**
 * One posting at a time, and four ways to answer it.
 *
 * Which affordance carries the deck depends on the pointer. On a phone the drag
 * *is* the interface: the card follows the finger and the stamp names the
 * verdict before it commits, so the button bar below it was a second copy of
 * the same four answers eating the bottom of the screen. From `sm` up the bar
 * comes back, because a four-way drag with a mouse is the clumsier path and
 * there is room for both.
 *
 * The drag survives `prefers-reduced-motion` — `index.css` kills transitions,
 * not the transform that tracks the finger — and the arrow keys answer at every
 * size, which is what keeps a verdict reachable without a gesture. The tests
 * drive the buttons and the keys; the buttons are still in the DOM at the width
 * jsdom renders at.
 */
export function SwipeDeck({
  jobs,
  onVerdict,
  onDetails,
  busy,
}: {
  jobs: Job[];
  onVerdict: (job: Job, direction: SwipeDirection) => void;
  onDetails: (job: Job) => void;
  busy: boolean;
}) {
  const top = jobs[0];
  const next = jobs[1];

  const commit = useCallback(
    (direction: SwipeDirection) => {
      if (top && !busy) onVerdict(top, direction);
    },
    [top, busy, onVerdict],
  );

  const swipe = useSwipe(commit);

  // Arrow keys on the whole document rather than on a focused element: the deck
  // is the only thing on this screen, and requiring a tab-stop first would make
  // the keyboard path worse than the mouse one instead of equal to it.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      // Not while someone is typing a URL into the paste field.
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      const match = ORDER.find((direction) => VERDICTS[direction].key === event.key);
      if (!match) return;
      event.preventDefault();
      commit(match);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [commit]);

  if (!top) return null;

  const stamp = swipe.direction ? VERDICTS[swipe.direction] : null;

  return (
    <div className="flex flex-col items-center gap-4">
      <div className="relative w-full max-w-md" style={{ height: "clamp(24rem, 58dvh, 34rem)" }}>
        {/* The next card, peeking. It is what makes the deck read as a stack
            with more in it rather than as a single card that keeps changing. */}
        {next && (
          // `inert` as well as `aria-hidden`: the card behind still has a
          // details button and a link in it, and without this they stay in the
          // tab order — so a keyboard user tabs into a posting they cannot see.
          <div
            inert
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 scale-[0.94] opacity-60"
            style={{ transform: "translateY(0.75rem) scale(0.94)" }}
          >
            <JobCard job={next} onDetails={() => {}} />
          </div>
        )}

        <div
          {...swipe.bind}
          className="absolute inset-0 cursor-grab touch-none select-none active:cursor-grabbing"
          style={{
            transform: `translate(${swipe.dx}px, ${swipe.dy}px) rotate(${swipe.dx / 20}deg)`,
            // Snap back instantly while the finger is down; ease home when it lifts.
            transition: swipe.dragging ? "none" : "transform 180ms ease-out",
            willChange: "transform",
          }}
        >
          <JobCard job={top} onDetails={() => onDetails(top)} />

          {stamp && (
            <div
              aria-hidden="true"
              className={`glass squircle pointer-events-none absolute left-1/2 top-10 -translate-x-1/2 -rotate-6 rounded-control border-2 px-4 py-1.5 text-lg font-extrabold uppercase tracking-wider ${stamp.stamp}`}
              style={{ opacity: swipe.progress }}
            >
              {stamp.label}
            </div>
          )}
        </div>
      </div>

      {/* The action bar. Glass, because it floats over the card.
          Not on a phone: there the gesture *is* the interface, and four buttons
          under the card were spending the bottom fifth of a 375px screen
          restating what the drag already does — with the stamp naming each
          verdict as the card moves. It stays from `sm` up, where there is room
          for it and where a mouse makes a four-way drag the clumsier path. */}
      <div className="glass squircle hidden items-center gap-2 rounded-sheet p-2 sm:flex">
        {ORDER.map((direction) => {
          const verdict = VERDICTS[direction];
          return (
            <button
              key={direction}
              type="button"
              onClick={() => commit(direction)}
              disabled={busy}
              title={`${verdict.hint} (${verdict.key.replace("Arrow", "")} arrow)`}
              aria-label={verdict.hint}
              className={`squircle flex h-14 w-14 items-center justify-center rounded-control bg-white/70 text-2xl leading-none shadow-sm transition active:scale-95 disabled:opacity-40 dark:bg-ink-900/70 ${verdict.tone}`}
            >
              {verdict.glyph}
            </button>
          );
        })}
      </div>

      {/* Only where it says something the screen does not. On a phone the
          buttons are the affordance and the card invites the drag; the arrow
          keys are the part nobody discovers, and there are none to press. */}
      <p className="hidden text-xs text-ink-400 sm:block">
        Drag the card, use the buttons, or press the arrow keys.
      </p>
    </div>
  );
}
