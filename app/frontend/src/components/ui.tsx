import { type ReactNode, useEffect, useRef } from "react";

import { InlineMarkdown } from "./Markdown";
import type { RunPhase } from "../lib/types";
import { useSheetDrag } from "../lib/useSheetDrag";

/**
 * The two brand ramps, as SVG paint servers, and the ids that name them.
 *
 * A `stroke` cannot read `background-image`, so the trick a gradient *label*
 * uses — `background-clip: text` on `.brand-text` / `.track-text` in
 * `index.css` — has no equivalent for an icon. These are the same two ramps at
 * the same 120°, and they have to be kept in step with those two classes by
 * hand.
 *
 * They live here rather than in `Layout.tsx` because two files paint from them
 * now — the nav's four icons and the theme button in the same corner — and an
 * id spelled out in two components is an id that drifts in one of them. The
 * element is rendered once, from the shell.
 *
 * `userSpaceOnUse` over the whole 24×24 box, not the default
 * `objectBoundingBox`: an icon is several paths, and per-path bounding boxes
 * would give the magnifier's handle its own full orange-to-pink ramp beside a
 * circle already halfway through one. One ramp across the icon, whatever it is
 * drawn from.
 *
 * **A `url(#…)` that resolves to nothing paints nothing** — no fallback to
 * `currentColor`, no error, just an icon that is not there. Which is why
 * `layout.test.tsx` asserts both of these are in the document.
 */
export const NAV_GRADIENT = { flame: "nav-gradient-flame", track: "nav-gradient-track" } as const;

/** What an icon puts in `stroke` to be painted by one of them. */
export const navStroke = (id: string) => `url(#${id})`;

export function NavGradients() {
  return (
    <svg width="0" height="0" aria-hidden="true" focusable="false" className="absolute">
      <defs>
        <linearGradient
          id={NAV_GRADIENT.flame}
          gradientUnits="userSpaceOnUse"
          x1="0"
          y1="0"
          x2="20.8"
          y2="12"
        >
          <stop offset="0%" stopColor="var(--color-flame-from)" />
          <stop offset="100%" stopColor="var(--color-flame-to)" />
        </linearGradient>
        <linearGradient
          id={NAV_GRADIENT.track}
          gradientUnits="userSpaceOnUse"
          x1="0"
          y1="0"
          x2="20.8"
          y2="12"
        >
          <stop offset="0%" stopColor="var(--color-track-from)" />
          <stop offset="100%" stopColor="var(--color-track-to)" />
        </linearGradient>
      </defs>
    </svg>
  );
}

/**
 * The round 44px corner button, in its two shapes: a link (Account, Settings)
 * and a button (the theme, which cycles in place).
 *
 * All three are drawn in the brand ramp at rest and take the selected tab's
 * halo when pointed at, focused, or — for the two links — on their own page.
 * The gradient is the resting state rather than the hover reward because these
 * are drawings whose labels live in a tooltip: colour is what carries them, and
 * a phone has no pointer to reveal anything with.
 *
 * `border-transparent` is load-bearing. `.nav-lit` recolours that border rather
 * than declaring one, and a rule that *adds* a 1px border grows the button by
 * two under the pointer.
 */
export const CORNER_BUTTON =
  "nav-lit nav-flame flex h-11 w-11 items-center justify-center rounded-full border border-transparent transition";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    // Deliberately opaque. A Card holds agent prose, a rendered document or a
    // form — the content layer, where glass costs contrast on the one thing
    // this app exists to produce. See documentation/design-language.md.
    //
    // `min-w-0` is what keeps a phone from scrolling sideways (2026-09-10). A
    // grid or flex item defaults to `min-width: auto`, which means "never
    // narrower than my widest unbreakable content" — so one `truncate`
    // filename, one long URL or one code token inside a Card widened its whole
    // track and, with it, the page: the base-document cards ran to 523px in a
    // 375px viewport. In normal block flow this changes nothing at all.
    <div
      className={`squircle min-w-0 rounded-card border border-ink-200 bg-white p-4 shadow-sm sm:p-5 dark:border-ink-800 dark:bg-ink-900 ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * A heading and the controls that belong to it.
 *
 * The two stack on a phone rather than sharing a row: the actions here are
 * things like the results slider and "Run Investigator", which squeezed into the
 * right-hand half of a 360px screen would be unreadable and barely tappable.
 */
export function SectionTitle({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-col items-stretch gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {subtitle && (
          <p className="mt-0.5 max-w-2xl text-sm text-ink-500 dark:text-ink-400">{subtitle}</p>
        )}
      </div>
      {action}
    </div>
  );
}

type ButtonProps = {
  children: ReactNode;
  onClick?: () => void;
  /**
   * Only ever used to stop a drag surface from swallowing this button.
   *
   * A captured pointer makes the browser fire `click` at the capturing element
   * instead of the button under the finger, so a button inside the sheet's grab
   * handle or the deck's card has to keep `pointerdown` from reaching it. See
   * `lib/useSheetDrag.ts`.
   */
  onPointerDown?: (event: React.PointerEvent<HTMLButtonElement>) => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "ghost" | "danger" | "glass";
  size?: "sm" | "md";
  type?: "button" | "submit";
  title?: string;
  className?: string;
};

export function Button({
  children,
  onClick,
  onPointerDown,
  disabled,
  variant = "primary",
  size = "md",
  type = "button",
  title,
  className = "",
}: ButtonProps) {
  const base =
    "squircle inline-flex items-center justify-center gap-2 rounded-control font-medium transition disabled:cursor-not-allowed disabled:opacity-50";
  // Taller than they look on a phone: the padding that reads right on a laptop
  // leaves a 28px target, and a finger is nearer 44px wide.
  const sizes = {
    sm: "min-h-9 px-3 py-1.5 text-xs sm:min-h-0 sm:px-2.5 sm:py-1",
    md: "min-h-11 px-4 py-2.5 text-sm sm:min-h-0 sm:px-3.5 sm:py-2",
  };
  const variants = {
    primary: "brand-gradient text-white shadow-sm shadow-accent-600/25 hover:brightness-105",
    secondary:
      "border border-ink-200 bg-white text-ink-800 hover:bg-ink-50 dark:border-ink-700 dark:bg-ink-800 dark:text-ink-100 dark:hover:bg-ink-700",
    ghost: "text-ink-600 hover:bg-ink-100 dark:text-ink-300 dark:hover:bg-ink-800",
    // A control that sits on top of something — the deck's actions, the trash
    // button over a card. Glass is correct here: it is the layer above.
    glass: "glass text-ink-800 hover:brightness-105 dark:text-ink-100",
    danger: "bg-red-600 text-white hover:bg-red-700",
  };
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      onPointerDown={onPointerDown}
      disabled={disabled}
      className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Badge({
  children,
  tone = "neutral",
  title,
  className = "",
}: {
  children: ReactNode;
  tone?: "neutral" | "good" | "warn" | "bad" | "info";
  title?: string;
  className?: string;
}) {
  const tones = {
    neutral: "bg-ink-100 text-ink-700 dark:bg-ink-800 dark:text-ink-300",
    good: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
    warn: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300",
    bad: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
    info: "bg-accent-500/15 text-accent-700 dark:text-accent-400",
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-chip px-1.5 py-0.5 text-xs font-medium ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

/** Score badge shared by job fit scores and audit scores — both are 0–10. */
export function ScoreBadge({
  score,
  label,
  threshold,
}: {
  score: number;
  label?: string;
  threshold?: number;
}) {
  const bar = threshold ?? 7;
  const tone = score >= bar ? "good" : score >= bar - 2 ? "warn" : "bad";
  return (
    <Badge
      tone={tone}
      title={threshold ? `Pass mark is ${threshold}` : undefined}
    >
      {label ? `${label} ` : ""}
      {score.toFixed(1)}
      <span className="opacity-60">/10</span>
    </Badge>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-ink-500 dark:text-ink-400">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-ink-300 border-t-accent-600" />
      {label}
    </span>
  );
}

/**
 * What a streaming run is doing, one line per stage as it starts.
 *
 * Deliberately not a checklist: the lines say what has begun, not what has
 * finished, because a run whose stages overlap would otherwise tick things off
 * while they were still happening. The newest line is the live one.
 */
export function RunProgress({
  phases,
  running,
  hint,
}: {
  phases: RunPhase[];
  running: boolean;
  hint?: string;
}) {
  if (!running && phases.length === 0) return null;
  return (
    <Card className="space-y-2">
      {hint && <p className="text-sm text-ink-500 dark:text-ink-400">{hint}</p>}
      {phases.length === 0 ? (
        <Spinner label="Starting the run…" />
      ) : (
        <ol className="space-y-1.5">
          {phases.map((phase, index) => {
            const live = running && index === phases.length - 1;
            return (
              <li key={index} className="flex items-start gap-2 text-sm">
                {live ? (
                  <Spinner />
                ) : (
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-300 dark:bg-ink-600" />
                )}
                <span className={live ? "" : "text-ink-500 dark:text-ink-400"}>
                  {phase.message}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="squircle rounded-card border border-dashed border-ink-300 p-6 text-center sm:p-8 dark:border-ink-700">
      <p className="font-medium">{title}</p>
      {hint && <p className="mx-auto mt-1 max-w-md text-sm text-ink-500 dark:text-ink-400">{hint}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
      {message}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-ink-500 dark:text-ink-400">
        {label}
      </span>
      {children}
    </label>
  );
}

/**
 * The shared field style.
 *
 * `text-sm` is a laptop measurement; index.css raises every field to 16px under
 * the `sm` breakpoint, because Safari zooms the page in on a smaller one and
 * never zooms back out.
 */
export const inputClass =
  "w-full rounded-control border border-ink-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-accent-500 focus:ring-2 focus:ring-accent-500/20 sm:py-2 dark:border-ink-700 dark:bg-ink-950 dark:text-ink-100";

export function KeyValue({ label, value }: { label: string; value: ReactNode }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex gap-2 text-sm">
      <span className="shrink-0 text-ink-500 dark:text-ink-400">{label}</span>
      <span className="min-w-0 break-words">{value}</span>
    </div>
  );
}

export function BulletList({ items, tone }: { items?: string[]; tone?: "bad" | "good" }) {
  if (!items?.length) return null;
  const colour =
    tone === "bad"
      ? "text-red-700 dark:text-red-400"
      : tone === "good"
        ? "text-emerald-700 dark:text-emerald-400"
        : "";
  return (
    // Every caller fills this from an agent's string list, and agents label
    // their bullets — "**Timing:** the deadline is before your term ends".
    <ul className={`list-disc space-y-1 pl-5 text-sm ${colour}`}>
      {items.map((item, index) => (
        <li key={index}>
          <InlineMarkdown>{item}</InlineMarkdown>
        </li>
      ))}
    </ul>
  );
}

/**
 * A sheet floating over the app.
 *
 * The control layer, so it is glass — and the one place in this app where a
 * backdrop blur is doing what Apple's material is actually for: separating a
 * temporary surface from the page it interrupts without hiding it.
 *
 * Three things it has to get right, none of which are visual: Escape closes it,
 * focus moves into it on open and returns to whatever opened it on close, and
 * the backdrop is a click target. A dialog that traps a keyboard user is worse
 * than no dialog.
 *
 * A fourth on a phone, where this is a bottom sheet rather than a centred box:
 * **pulling it down closes it**, exactly as the ✕ does. That is the gesture the
 * shape promises — a panel that rose from the bottom edge should go back to it
 * — and on a 375px screen the cross is a 24px target in the corner furthest
 * from the thumb that opened the sheet. The grabber above the title is the
 * affordance; it is also the handle, because a drag surface wrapped around the
 * whole sheet would fight the paste field, the chat composer and the scroll.
 */
export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  // Whatever had focus when this opened. Restoring it is what makes the modal
  // an interruption rather than a redirection.
  const opener = useRef<HTMLElement | null>(null);
  const drag = useSheetDrag(onClose);

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement as HTMLElement | null;
    panel.current?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    // The page behind must not scroll under a sheet the finger is on.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previous;
      opener.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-40 flex items-end justify-center bg-ink-950/40 p-0 backdrop-blur-sm sm:items-center sm:p-4"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        // A column with a fixed head and a scrolling body, rather than one
        // scrolling box: the grabber has to stay reachable after the sheet has
        // been read, and a handle that scrolls away is a handle you have to
        // scroll back to before you can use it.
        className="glass squircle flex max-h-[85vh] w-full flex-col rounded-t-sheet outline-none sm:max-w-lg sm:rounded-sheet"
        style={{
          transform: drag.dy ? `translateY(${drag.dy}px)` : undefined,
          // Follow the finger exactly while it is down; ease home when it lifts
          // without committing.
          transition: drag.dragging ? "none" : "transform 180ms ease-out",
        }}
      >
        <div
          {...drag.bind}
          // `touch-none` so a downward drag here is the gesture and not a
          // scroll of the body underneath — the two would otherwise share the
          // same finger.
          className="shrink-0 cursor-grab touch-none select-none px-4 pb-3 pt-3 active:cursor-grabbing sm:px-5 sm:pt-5"
        >
          {/* The grabber. Only on a phone: at `sm` this is a centred box that
              never touched an edge, so there is nothing to pull it back to. */}
          <div
            aria-hidden="true"
            className="mx-auto mb-3 h-1.5 w-10 rounded-full bg-ink-400 sm:hidden dark:bg-ink-500"
          />
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-base font-semibold tracking-tight">{title}</h2>
            <Button
              size="sm"
              variant="ghost"
              onClick={onClose}
              // Without this the handle captures the pointer and the browser
              // fires the click at the handle instead of at this button.
              onPointerDown={(event) => event.stopPropagation()}
              title="Close"
            >
              ✕
            </Button>
          </div>
        </div>
        <div className="safe-bottom min-h-0 flex-1 overflow-y-auto px-4 pb-4 sm:px-5 sm:pb-5">
          {children}
        </div>
      </div>
    </div>
  );
}

/**
 * The round button that floats bottom-right on a phone.
 *
 * Positioned by `.fab-dock` in index.css rather than by utilities here, because
 * its offset and the tab bar's are one measurement — they must move together or
 * they overlap on a device with a home indicator.
 */
export function FloatingAction({
  label,
  onClick,
  children,
  className = "",
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`fab-dock brand-gradient flex h-14 w-14 items-center justify-center rounded-full text-2xl leading-none text-white shadow-lg shadow-accent-600/30 transition active:scale-95 ${className}`}
    >
      {children}
    </button>
  );
}
