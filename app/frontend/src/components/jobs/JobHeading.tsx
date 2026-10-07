import { InlineMarkdown } from "../Markdown";
import { ScoreBadge } from "../ui";
import { AgeBadge, UrlStatusBadge } from "./badges";
import { oneLiner } from "./oneLiner";
import type { Job } from "../../lib/types";

/**
 * Who this posting is from, what the role is, and the one line about it.
 *
 * Shared by the details sheet on the Jobs deck and by the application page, so
 * a posting reads the same before and after you swipe right on it. It used to
 * be neither: the application page showed the job title and the company in
 * small grey type and nothing else, which meant the moment you decided to apply
 * was also the moment the app stopped telling you what you were applying to.
 *
 * The company comes first and largest for the same reason it does on the deck
 * card — the question a person answers first is *who is this*.
 */
export function JobHeading({ job }: { job: Job }) {
  return (
    <div className="space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="min-w-0 break-words text-2xl font-extrabold leading-[1.05] tracking-tighter sm:text-3xl">
            {job.company || "Unknown company"}
          </h2>
          <p className="mt-1 text-sm font-semibold text-ink-700 sm:text-base dark:text-ink-200">
            {job.title}
          </p>
        </div>
        <ScoreBadge score={job.fit_score} />
      </div>

      {/* The badges ride with the facts: they are the same kind of thing —
          what is true of this posting — and a 375px column cannot spend a
          line on each. */}
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
        <p className="text-sm text-ink-700 dark:text-ink-200">
          <InlineMarkdown>{oneLiner(job)}</InlineMarkdown>
        </p>
      )}
    </div>
  );
}
