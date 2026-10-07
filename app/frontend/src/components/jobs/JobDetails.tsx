import { Link } from "react-router-dom";

import { Markdown } from "../Markdown";
import { Badge, BulletList, KeyValue } from "../ui";
import { JobHeading } from "./JobHeading";
import type { Job } from "../../lib/types";

/**
 * Everything the card had to leave out.
 *
 * The card caps its bullets so it never has to scroll — a scroll region inside
 * a draggable card fights the swipe for the same finger. This is where the rest
 * of the posting lives, and it opens in a sheet, which may scroll freely
 * because nothing is being dragged while it is up.
 *
 * The application page shows the same component, with `heading` off because its
 * own header already carries the company and the role. One posting, one
 * rendering of it, before and after the swipe.
 */
export function JobDetails({ job, heading = true }: { job: Job; heading?: boolean }) {
  return (
    <div className="space-y-4">
      {heading && <JobHeading job={job} />}

      {job.description && (
        <Markdown className="text-sm text-ink-600 dark:text-ink-300">{job.description}</Markdown>
      )}

      {job.fit_rationale && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Why this score
          </h4>
          <Markdown className="mt-1 text-sm">{job.fit_rationale}</Markdown>
        </div>
      )}

      <div className="space-y-1">
        <KeyValue label="Compensation" value={job.compensation} />
        <KeyValue label="Language" value={job.language} />
        {/* The posting's own wording first — "3 days ago" is what it said —
            with the parsed date behind it, since that is the one that sorted. */}
        <KeyValue
          label="Posted"
          value={
            job.posted_at && job.posted_on && job.posted_at !== job.posted_on
              ? `${job.posted_at} (${job.posted_on})`
              : job.posted_at || job.posted_on
          }
        />
      </div>

      {job.strengths?.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
            Strengths
          </h4>
          <BulletList items={job.strengths} tone="good" />
        </div>
      )}
      {job.risks?.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-red-700">Risks</h4>
          <BulletList items={job.risks} tone="bad" />
        </div>
      )}
      {job.requirements?.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Requirements
          </h4>
          <BulletList items={job.requirements} />
        </div>
      )}
      {job.nice_to_have?.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Nice to have
          </h4>
          <BulletList items={job.nice_to_have} />
        </div>
      )}
      {job.keywords?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {job.keywords.map((keyword) => (
            <Badge key={keyword}>{keyword}</Badge>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        {job.url && (
          <a
            href={job.url}
            target="_blank"
            rel="noreferrer"
            className="text-accent-600 underline dark:text-accent-400"
          >
            open posting ↗
          </a>
        )}
        {job.invocation_id && (
          <Link to={`/traces/${job.run_id}`} className="text-xs text-accent-600 underline">
            why did the agent surface this? → trace
          </Link>
        )}
      </div>
    </div>
  );
}
