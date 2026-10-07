import { InlineMarkdown } from "../Markdown";
import { ScoreBadge } from "../ui";
import { AgeBadge, UrlStatusBadge } from "./badges";
import { oneLiner } from "./oneLiner";
import type { Job } from "../../lib/types";

/**
 * How many bullets of each kind a card shows.
 *
 * These caps are load-bearing rather than cosmetic. A draggable card carries
 * `touch-action: none` so a vertical swipe is a swipe and not a scroll — which
 * means the card must never need to scroll, because a scroll region inside it
 * would fight the gesture for the same finger. Everything past the cap is in
 * the details sheet, one tap away.
 */
const STRENGTHS = 2;
const RISKS = 2;
const REQUIREMENTS = 3;

function Bullets({
  label,
  items,
  cap,
  tone,
}: {
  label: string;
  items: string[];
  cap: number;
  tone: string;
}) {
  if (!items?.length) return null;
  const shown = items.slice(0, cap);
  return (
    <div className="min-w-0">
      <h4 className={`text-[0.65rem] font-semibold uppercase tracking-wider ${tone}`}>{label}</h4>
      <ul className="mt-1 space-y-0.5 text-sm">
        {shown.map((item, index) => (
          <li key={index} className="flex gap-1.5">
            <span aria-hidden="true" className={`mt-2 h-1 w-1 shrink-0 rounded-full ${tone} bg-current`} />
            <span className="min-w-0 line-clamp-2">
              <InlineMarkdown>{item}</InlineMarkdown>
            </span>
          </li>
        ))}
      </ul>
      {items.length > shown.length && (
        <p className="mt-0.5 text-xs text-ink-400">+{items.length - shown.length} more in details</p>
      )}
    </div>
  );
}

/**
 * One posting, filling the deck.
 *
 * Opaque on purpose: this is the content layer, and it is what the whole screen
 * is for. The glass in this app floats *over* it — the action bar, the stamps,
 * the sheet the details open in.
 *
 * The company comes first and largest. On a list, the role was the thing to
 * scan; on a deck showing one posting at a time, the question the card has to
 * answer in the first quarter-second is *who is this*.
 */
export function JobCard({ job, onDetails }: { job: Job; onDetails: () => void }) {
  return (
    <div className="squircle flex h-full w-full flex-col gap-2.5 overflow-hidden rounded-sheet border border-ink-200 bg-white p-4 shadow-xl shadow-ink-950/5 sm:gap-3 sm:p-6 dark:border-ink-800 dark:bg-ink-900">
      <div className="min-w-0">
        <div className="flex items-start justify-between gap-3">
          <h3 className="min-w-0 break-words text-2xl font-extrabold leading-[1.05] tracking-tighter sm:text-4xl">
            {job.company || "Unknown company"}
          </h3>
          <ScoreBadge score={job.fit_score} />
        </div>
        <p className="mt-1 text-sm font-semibold text-ink-700 sm:text-base dark:text-ink-200">
          {job.title}
        </p>
      </div>

      {/* The badges ride in the same row as the facts. They are the same kind
          of thing — what is true of this posting — and a 375px card cannot
          spend a line on each. */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-500 dark:text-ink-400">
        <AgeBadge days={job.posted_days_ago} />
        <UrlStatusBadge status={job.url_status} code={job.url_http_status} url={job.url} />
        {job.location && <span>{job.location}</span>}
        {job.remote && job.remote !== "unknown" && <span>{job.remote}</span>}
        {job.contract_type && <span>{job.contract_type}</span>}
        {job.duration && <span>{job.duration}</span>}
        {job.start_date && <span>starts {job.start_date}</span>}
        {job.deadline && <span className="text-amber-600">deadline {job.deadline}</span>}
        {job.source && <span className="opacity-70">via {job.source}</span>}
      </div>

      {oneLiner(job) && (
        <p className="line-clamp-3 text-sm text-ink-700 dark:text-ink-200">
          <InlineMarkdown>{oneLiner(job)}</InlineMarkdown>
        </p>
      )}

      {/* `min-h-0` and `overflow-hidden` together are what keep the card from
          outgrowing the deck on a short screen: the bullets are the part that
          gives, and everything past the caps above is in the details sheet. */}
      <div className="grid min-h-0 flex-1 gap-x-4 gap-y-2 overflow-hidden border-t border-ink-200 pt-2.5 sm:grid-cols-2 dark:border-ink-800">
        <Bullets
          label="Strengths"
          items={job.strengths}
          cap={STRENGTHS}
          tone="text-emerald-700 dark:text-emerald-400"
        />
        <Bullets label="Risks" items={job.risks} cap={RISKS} tone="text-red-700 dark:text-red-400" />
        <div className="sm:col-span-2">
          <Bullets
            label="Requirements"
            items={job.requirements}
            cap={REQUIREMENTS}
            tone="text-ink-500 dark:text-ink-400"
          />
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 text-sm">
        <button
          type="button"
          onClick={onDetails}
          // The same guard the link below carries, and for a sharper reason:
          // the deck captures the pointer on `pointerdown` so a flick that
          // leaves the card still ends on it, and a captured pointer makes the
          // browser fire `click` at the capturing element rather than at what
          // was under it. A touch pointer is captured to its own target
          // implicitly, which is why this button worked with a finger and did
          // nothing at all with a mouse.
          onPointerDown={(event) => event.stopPropagation()}
          className="rounded-chip font-medium text-accent-600 underline-offset-2 hover:underline dark:text-accent-400"
        >
          details
        </button>
        {job.url && (
          <a
            href={job.url}
            target="_blank"
            rel="noreferrer"
            // The pointer handlers live on the wrapper, and a drag that starts
            // on a link would otherwise open it on release.
            onPointerDown={(event) => event.stopPropagation()}
            className="rounded-chip text-accent-600 underline-offset-2 hover:underline dark:text-accent-400"
          >
            open posting ↗
          </a>
        )}
      </div>
    </div>
  );
}
