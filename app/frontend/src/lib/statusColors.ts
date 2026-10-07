import type { ApplicationStatus } from "./types";

/**
 * One colour per application status, shared by everything that draws one: the
 * Tracker's two stacked bars and the status tabs over the board. One map, so a
 * tab can never drift from the segment it names.
 *
 * `fill` was chosen with the dataviz validator rather than by eye (2026-09-26),
 * light and dark separately: every pair of neighbours clears the colour-blind
 * separation target in both themes. The single teal became a four-step ramp on
 * 2026-10-05 when `interview` split into its rounds — chosen by lightness, not
 * re-validated. The two greys fail its chroma check on
 * purpose — nothing has been sent for a saved or a preparing application, and
 * a hue would claim otherwise. Blue, the teal ramp, violet are "in play"; red and amber
 * are the two ways it ends badly; the darkest grey is the one you ended
 * yourself. Emerald is avoided for the same reason the Tracker's own colour
 * moved off it (see design-language.md), and red beside green is the pair
 * deuteranopes lose. Re-run the validator if one moves.
 *
 * `onFill` is the text that reads on `fill` — white where the fill is dark
 * enough, near-black where it is not (amber, the light greys, the two lighter
 * teals, and preparing in the dark theme). `tint` is the same hue faint, for a tab that is not selected.
 */
export const STATUS_COLOR: Record<
  ApplicationStatus,
  { fill: string; onFill: string; tint: string }
> = {
  saved: {
    fill: "bg-ink-300 dark:bg-ink-600",
    onFill: "text-ink-900 dark:text-white",
    tint: "bg-ink-300/35 dark:bg-ink-600/35",
  },
  preparing: {
    fill: "bg-ink-500 dark:bg-ink-400",
    onFill: "text-white dark:text-ink-950",
    tint: "bg-ink-500/20 dark:bg-ink-400/25",
  },
  applied: {
    fill: "bg-blue-600 dark:bg-blue-500",
    onFill: "text-white",
    tint: "bg-blue-600/15 dark:bg-blue-500/25",
  },
  // The four interview rounds are one hue, lightest first: they are one stage
  // of the pipeline seen closer up, and the ramp says "further along" without
  // borrowing a hue that means something else here. Neighbours are told apart
  // by lightness, plus the 2px gap every stacked segment already has.
  hr_pre_call: {
    fill: "bg-teal-300 dark:bg-teal-200",
    onFill: "text-ink-950",
    tint: "bg-teal-300/25 dark:bg-teal-200/25",
  },
  hr_interview: {
    fill: "bg-teal-500 dark:bg-teal-400",
    onFill: "text-ink-950",
    tint: "bg-teal-500/20 dark:bg-teal-400/25",
  },
  technical_test: {
    fill: "bg-teal-700 dark:bg-teal-600",
    onFill: "text-white",
    tint: "bg-teal-700/15 dark:bg-teal-600/25",
  },
  manager_interview: {
    fill: "bg-teal-900 dark:bg-teal-800",
    onFill: "text-white",
    tint: "bg-teal-900/15 dark:bg-teal-800/30",
  },
  offer: {
    fill: "bg-violet-600 dark:bg-violet-500",
    onFill: "text-white",
    tint: "bg-violet-600/15 dark:bg-violet-500/25",
  },
  rejected: {
    fill: "bg-red-600 dark:bg-red-500",
    onFill: "text-white",
    tint: "bg-red-600/15 dark:bg-red-500/25",
  },
  ghosted: {
    fill: "bg-amber-500",
    onFill: "text-ink-950",
    tint: "bg-amber-500/20 dark:bg-amber-500/25",
  },
  withdrawn: {
    fill: "bg-ink-700 dark:bg-ink-200",
    onFill: "text-white dark:text-ink-950",
    tint: "bg-ink-700/15 dark:bg-ink-200/20",
  },
};
