import type { Job } from "../../lib/types";

/**
 * The one line a deck card has room for.
 *
 * `summary` is written by whichever agent read the posting, but every row saved
 * before that field existed has none — and a card with a blank where the role
 * should be is worse than a slightly long sentence. So fall back to the first
 * sentence of `description`, then to the score's own rationale.
 */
export function oneLiner(job: Job): string {
  if (job.summary) return job.summary;
  const source = job.description || job.fit_rationale;
  if (!source) return "";
  const [first] = source.split(/(?<=[.!?])\s/);
  return first.length > 180 ? `${first.slice(0, 177)}…` : first;
}
