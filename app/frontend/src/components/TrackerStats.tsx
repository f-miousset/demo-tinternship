import { useState } from "react";

import { STATUS_COLOR } from "../lib/statusColors";
import { INTERVIEW_STATUSES } from "../lib/statuses";
import type { Application, ApplicationStatus } from "../lib/types";
import { Card } from "./ui";

function percent(part: number, whole: number): number {
  return whole > 0 ? Math.round((part / whole) * 100) : 0;
}

/** The statuses that mean a company answered: any interview round, an offer, a no. */
const ANSWERS: ApplicationStatus[] = [...INTERVIEW_STATUSES, "offer", "rejected"];

/**
 * How a sent application ended up: the three answers, then `ghosted` — the
 * answer that never came. Ghosted is an outcome but not a response, so it is a
 * segment here and not part of *Got a response*. Adjacent in the same order as
 * the board, so the validated neighbour pairs still hold.
 */
const OUTCOMES: ApplicationStatus[] = [...ANSWERS, "ghosted"];

type Segment = { key: ApplicationStatus; label: string; count: number };

/**
 * One bar split into a segment per status, sized by count, with a legend
 * underneath carrying every label, count and share — so colour is never the
 * only way to read it, and a phone (which has no hover) loses nothing.
 *
 * `gap-0.5` is the 2px surface gap between segments, so two neighbours never
 * merge into one block whatever their colours. Hovering a segment or a legend
 * entry dims the rest. A segment at 0 is never drawn; its legend entry shows
 * only if the caller kept it in `segments`.
 */
function StackedBar({ title, segments }: { title: string; segments: Segment[] }) {
  const [hovered, setHovered] = useState<ApplicationStatus | null>(null);
  const total = segments.reduce((sum, s) => sum + s.count, 0);
  const drawn = segments.filter((s) => s.count > 0);
  const dim = (key: ApplicationStatus) => (hovered && hovered !== key ? "opacity-35" : "");
  const hover = (key: ApplicationStatus) => ({
    onMouseEnter: () => setHovered(key),
    onMouseLeave: () => setHovered(null),
  });

  return (
    <div>
      <p className="mb-2 text-xs uppercase tracking-wide text-ink-500">{title}</p>
      <div
        role="img"
        aria-label={`${title} — ${segments
          .map((s) => `${s.label}: ${s.count} (${percent(s.count, total)}%)`)
          .join(", ")}`}
        className="flex h-3 gap-0.5 overflow-hidden rounded-full"
      >
        {drawn.map((s) => (
          <div
            key={s.key}
            title={`${s.label}: ${s.count} (${percent(s.count, total)}%)`}
            {...hover(s.key)}
            style={{ flexGrow: s.count }}
            className={`min-w-1.5 basis-0 transition-opacity ${STATUS_COLOR[s.key].fill} ${dim(s.key)}`}
          />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-600 dark:text-ink-300">
        {segments.map((s) => (
          <li
            key={s.key}
            {...hover(s.key)}
            className={`flex items-center gap-1.5 transition-opacity ${dim(s.key)}`}
          >
            <span aria-hidden="true" className={`h-2 w-2 rounded-full ${STATUS_COLOR[s.key].fill}`} />
            {s.label}
            <span className="font-semibold text-ink-900 dark:text-ink-50">{s.count}</span>
            <span className="text-ink-500">{percent(s.count, total)}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The funnel's rows: labelled horizontal bars, each `value / of` wide, with the
 * count and its rate at the end in ink — never inside the bar.
 */
function Bars({ rows, of }: { rows: { label: string; value: number; note: string }[]; of: number }) {
  return (
    <div className="space-y-1.5">
      {rows.map((row) => (
        <div
          key={row.label}
          role="img"
          aria-label={`${row.label}: ${row.value}${row.note ? `, ${row.note}` : ""}`}
          className="grid grid-cols-[7.5rem_1fr_auto] items-center gap-2 text-xs"
        >
          <span className="text-ink-600 dark:text-ink-300">{row.label}</span>
          <div className="h-2 overflow-hidden rounded-full bg-ink-100 dark:bg-ink-800">
            <div
              className="h-full rounded-full bg-track-500"
              style={{ width: `${percent(row.value, of)}%` }}
            />
          </div>
          <span className="text-right tabular-nums">
            <span className="font-semibold text-ink-900 dark:text-ink-50">{row.value}</span>
            {row.note && <span className="ml-1.5 text-ink-500">{row.note}</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * The Tracker's tally, drawn rather than listed.
 *
 * Three charts in one card: *where is everything* (a stacked bar, a segment
 * per status, in the board's column order), *how is it going* (a three-step
 * funnel: tracked → sent → got a response, where a rejection counts as a
 * response) and *how did it end* (a second stacked bar: the four interview
 * rounds, offer, rejected and ghosted as shares of the lot, shown once there
 * is one).
 * One card, not three, so a phone still reaches the board after one short
 * block.
 */
export function TrackerStats({
  applications,
  columns,
  searching = false,
}: {
  applications: Application[];
  columns: { key: ApplicationStatus; label: string }[];
  /** A search is narrowing the board. The charts never narrow, and say so. */
  searching?: boolean;
}) {
  const total = applications.length;
  const counts: Segment[] = columns.map((column) => ({
    key: column.key,
    label: column.label,
    count: applications.filter((a) => a.status === column.key).length,
  }));
  const sent = applications.filter((a) => a.status !== "saved" && a.status !== "preparing").length;
  // A rejection is an answer too: the company read it and replied. Counting
  // only interviews and offers here made "got a response" a success rate
  // under the wrong name, and hid how many companies answer at all.
  const responded = counts
    .filter((c) => ANSWERS.includes(c.key))
    .reduce((sum, c) => sum + c.count, 0);

  const funnel = [
    { label: "Tracked", value: total, note: "" },
    { label: "Sent", value: sent, note: total > 0 ? `${percent(sent, total)}%` : "" },
    {
      label: "Got a response",
      value: responded,
      note: sent > 0 ? `${percent(responded, sent)}% of sent` : "",
    },
  ];

  // Offer and rejected always keep their legend entry — a 0% offer rate is the
  // number you most want to see — while an interview round or ghosted joins
  // once one exists: four empty rounds would bury the two that matter.
  const outcomes = counts.filter(
    (c) => OUTCOMES.includes(c.key) && (c.key === "offer" || c.key === "rejected" || c.count > 0),
  );
  const ended = outcomes.reduce((sum, c) => sum + c.count, 0);

  return (
    <Card>
      <div className="space-y-4">
        {searching && (
          <p className="text-xs text-ink-500 dark:text-ink-400">
            All {total} applications — the search narrows the board only.
          </p>
        )}
        <StackedBar title="By status" segments={counts.filter((c) => c.count > 0)} />

        {/* Each row is measured against everything tracked, so the bars shrink
            the way the hunt does and the drop between two rows is the thing
            you see. */}
        <Bars rows={funnel} of={total} />

        {ended > 0 && <StackedBar title="Outcomes" segments={outcomes} />}
      </div>
    </Card>
  );
}
